#!/usr/bin/env python3
"""
runner.py - the Mac engine. Polls Supabase for queued tasks, executes Claude Code in
isolated git worktrees, and streams status/cost/outcomes back to Supabase so the
hosted dashboard updates in realtime. Ties together every feature:

  bandit/model_router  -> cheapest capable model (learned from outcomes)
  account_pool         -> rotate accounts on usage exhaustion
  caching              -> stable cached context prefix (input-token savings)
  knowledge_embed      -> inject relevant prior solutions (semantic reuse)
  verify               -> cheap-model diff review BEFORE integrate
  cost_ledger          -> record $/task (also pushed to Supabase outcomes)

Run on your Mac:
  export SUPABASE_URL=...  SUPABASE_SERVICE_KEY=...   # service key stays on the Mac
  python3 runner.py

It NEVER force-merges: verify-fail or test-fail creates an approval card and stops.
"""
import os, sys, time, json, socket, subprocess, threading, datetime

# Auto-load .env from the runner's own directory (works regardless of CWD)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.isfile(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, bandit, verify, caching, account_pool, cost_ledger, model_router, candidate_shared
import knowledge_embed as kb
import regression, budget, speculative, pr_integrate
import context_retrieval, result_cache
import confidence, blast_radius, replay
import feedback
import kill_switch, secrets_manager, credential_broker, quality_gate
import claude_cli, waste, judge, experiment_router, decision_engine
import agentic_coders
import plan_stage

INTEGRATION_MODE = os.environ.get("INTEGRATION_MODE", "local")  # local | pr
USE_CACHE = os.environ.get("RESULT_CACHE", "true").lower() == "true"
USE_RETRIEVAL = os.environ.get("SCOPED_CONTEXT", "true").lower() == "true"
USE_CONFIDENCE = os.environ.get("CONFIDENCE_GATE", "true").lower() == "true"

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
RUNNER_ID = os.environ.get("RUNNER_ID", socket.gethostname() + "-" + str(os.getpid()))
POLL = int(os.environ.get("POLL_SECONDS", "5"))
# Concurrency ceiling. Bumped 2->4: resource_governor.can_claim() still clamps every claim by
# free RAM / kernel memory pressure / disk, so the Mac can't be overrun — this just lets the
# runner use idle headroom instead of sitting at 2. Tune MAX_PARALLEL in runner/.env per machine.
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "12"))
RATE = ("temporarily limiting", "rate limit", "429", "overloaded", "too many requests")
EXHAUST = ("usage limit", "out of credits", "insufficient_quota", "quota",
           "weekly limit", "hit your weekly", "limit · resets", "limit - resets",
           "reached your usage", "usage limit reached", "upgrade to increase",
           "5-hour limit", "hour limit reached", "session limit", "limit reached ∙ resets")
# Cross-project reuse directive injected into every task: economize by reusing, not re-drafting.
REUSE_FIRST = ("\n\n## Reuse before you draft (cost discipline)\n"
    "Before writing net-new code: (1) search THIS repo for an existing helper/component/pattern "
    "and extend it; (2) check the injected prior-solution notes above and the shared kernel "
    "(packages/darwin-kernel / vendor/darwin-kernel) for something to import or adapt; (3) if the "
    "same need clearly exists in sibling apps, write it as a small reusable module and note "
    "'CANDIDATE-SHARED: <what>' in your final message so it can be promoted to a shared capability "
    "instead of re-drafted per app. Prefer the smallest diff that reuses existing code.")
POOL = account_pool.AccountPool()
_sem = threading.Semaphore(MAX_PARALLEL)
_projects = {}


def projects(project_id=None):
    global _projects
    if not _projects or (project_id and project_id not in _projects):
        _projects = {p["id"]: p for p in db.select("projects") or []}
    return _projects


def set_state(task_id, **kw):
    kw["updated_at"] = "now()"
    db.update("tasks", {"id": task_id}, kw)


def approval(project, kind, title, **kw):
    # fault-tolerant: a flood-guard dedup rejection (HTTP 409) must NOT kill the task
    try:
        db.insert("approvals", {"project": project, "kind": kind, "title": title, **kw})
    except Exception as e:
        print(f"[approval] skipped ({title[:40]}): {e}")


def integrate(repo, branch, base, test_cmd, slug="", verify_notes="", test_summary="passed"):
    # PR-native: push, open PR, let YOUR CI (sfc/gitleaks/vercel) gate, auto-merge on green.
    if INTEGRATION_MODE == "pr":
        r = pr_integrate.open_pr(repo, branch, base, slug, verify_notes, test_summary)
        if r.get("ok"):
            # PR opened + GitHub auto-merge armed: it merges the moment CI + Vercel go green,
            # so we don't block the task slot waiting. PR_OPEN = shipped-in-flight (not failure).
            return "PR_OPEN"
        print(f"[integrate] PR mode unavailable ({r.get('error')}) -> local ff-merge fallback")
        # fall through to local merge so the work still lands even without gh/push
    # local ff-merge (also the PR-mode fallback)
    # FIX: free the branch from its leftover agent worktree first, or `git rebase` fails with
    # "already checked out" — which was being mislabeled as CONFLICT and blocked ALL auto-merges.
    try:
        import approval_merge
        approval_merge._free_branch(repo, branch)
    except Exception:
        pass
    # clean fast-forward when the branch is strictly ahead of base (the normal case) — no rebase needed
    ahead = subprocess.run(["git", "merge-base", "--is-ancestor", base, branch],
                           cwd=repo, capture_output=True).returncode == 0
    if not ahead:
        if subprocess.run(["git", "rebase", base, branch], cwd=repo, capture_output=True).returncode != 0:
            subprocess.run(["git", "rebase", "--abort"], cwd=repo, capture_output=True)
            return "CONFLICT"
    # BUILD GATE: run the project's REAL production build on the branch; do NOT merge if it's red.
    # This is the fix for "merges succeed but every Vercel deploy fails" — build-breaking code can no
    # longer reach main/master. Skips only when no build command is detected.
    try:
        import build_gate
        bcmd = build_gate.detect_build_cmd(repo)
        if bcmd:
            ok, blog = build_gate.run_build(repo, branch, bcmd)
            if not ok:
                print(f"[integrate] build RED for {branch} -> not merging: {blog[-160:]}")
                return "BUILDFAIL"
    except Exception as _be:
        print(f"[integrate] build gate skipped ({_be})")
    # merge into `base` without needing it checked out (HEAD may be another branch)
    if subprocess.run(["git", "fetch", ".", f"{branch}:{base}"], cwd=repo, capture_output=True).returncode != 0:
        return "CONFLICT"
    if os.environ.get("ORCH_PUSH_ON_MERGE", "false").lower() == "true":
        subprocess.run(["git", "push", "origin", base], cwd=repo, capture_output=True)
    try:
        import approval_merge
        approval_merge._free_branch(repo, branch)
    except Exception:
        pass
    return "MERGED"


def _detect_prod_branch(repo, proj):
    """Best-effort production branch detection for repos whose default is master instead of main."""
    for b in (proj.get("prod_branch"), proj.get("default_base"), "main", "master"):
        if not b:
            continue
        if subprocess.run(["git", "rev-parse", "--verify", b], cwd=repo,
                          capture_output=True).returncode == 0:
            return b
    return proj.get("default_base") or "main"


def _integration_base(repo, proj, task_base):
    """Merge completed code into a temporary integration branch by default.

    This keeps code mergers automatic while decoupling them from Vercel production deploys.
    release_train.py later QA's the integration branch and promotes it to prod on a slower
    cadence.
    """
    if os.environ.get("ORCH_CODE_MERGE_TARGET", "dev").lower() not in ("dev", "staging", "integration"):
        return task_base
    dev = os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev")
    try:
        if subprocess.run(["git", "rev-parse", "--verify", dev], cwd=repo,
                          capture_output=True).returncode != 0:
            prod = _detect_prod_branch(repo, proj)
            subprocess.run(["git", "branch", dev, prod], cwd=repo, capture_output=True)
    except OSError:
        return task_base
    return dev


def _commit_agent_work(wt, slug, prompt):
    """Stage + commit everything the agent changed in the worktree. Returns True if a commit
    was made, False if there was nothing to commit. Uses --no-verify so a repo's pre-commit
    hook can't block/hang the pipeline; identity is set explicitly so commits never fail on a
    missing git user.email. Author is a VALID GitHub-verified email so Vercel does not block
    the resulting deployments (an invalid author like *.local blocks every deploy fleet-wide)."""
    _git_name = os.environ.get("FLEET_GIT_AUTHOR_NAME", "Kale Aaron Pasch")
    _git_email = os.environ.get("FLEET_GIT_AUTHOR_EMAIL", "kalepasch@gmail.com")
    env = {**os.environ,
           "GIT_AUTHOR_NAME": _git_name, "GIT_AUTHOR_EMAIL": _git_email,
           "GIT_COMMITTER_NAME": _git_name, "GIT_COMMITTER_EMAIL": _git_email}
    try:
        subprocess.run(["git", "add", "-A"], cwd=wt, env=env, capture_output=True)
        # nothing staged -> agent changed nothing
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=wt, env=env).returncode == 0:
            return False
        msg = f"agent: {slug}\n\n{(prompt or '')[:300]}"
        r = subprocess.run(["git", "commit", "--no-verify", "-m", msg], cwd=wt, env=env,
                           capture_output=True, text=True)
        return r.returncode == 0
    except Exception as e:
        print(f"[commit] {slug}: {e}")
        return False


def run_task(t):
    with _sem:
        proj = projects(t["project_id"]).get(t["project_id"], {})
        repo = proj.get("repo_path", os.getcwd())
        name = proj.get("name", "repo")
        # Fall back to the project's REAL default branch (master vs main), not a hardcoded
        # "main" — otherwise diff/rebase against a nonexistent branch returns empty.
        task_base = t.get("base_branch") or proj.get("default_base") or "main"
        base = _integration_base(repo, proj, task_base)
        slug = t["slug"]
        kind = t.get("kind", "build")
        test_cmd = proj.get("test_cmd") or os.environ.get("TEST_CMD", "npm test")

        # kill switch: stop all spend on this project (or globally) at a click
        if kill_switch.is_paused(name):
            set_state(t["id"], state="QUEUED", note="paused by kill switch")
            time.sleep(5); return

        # budget guardrail: telemetry by default; hard-stops only when explicitly enabled
        if not budget.allow(name):
            set_state(t["id"], state="BLOCKED", note="budget cap reached")
            return

        # waste guardrail: spend with nothing shipped (the $400 pattern) -> pause this
        # project + file an approval, immediately, before burning more tokens.
        waste_reason = waste.check(name)
        if waste_reason:
            kill_switch.pause(scope="project", project=name, reason=waste_reason, by="waste")
            set_state(t["id"], state="BLOCKED", note="waste guard: " + waste_reason)
            approval(name, "self", f"Waste guard paused {name}",
                     why=waste_reason,
                     value="Stops non-improving spend the moment it appears.",
                     risk="Project is paused until you review and resume.",
                     command="")
            try:
                import notify; notify.send(f"[waste] {waste_reason}")
            except Exception:
                pass
            return

        # result cache: identical (repo+prompt+commit) work is reused, not re-run
        sig = result_cache.signature(name, t["prompt"], repo, base) if USE_CACHE else None
        if sig:
            hit = result_cache.lookup(sig)
            if hit:
                set_state(t["id"], state="DONE", note=f"cache hit: reused {hit.get('branch')}")
                record(t, name, slug, kind, "cache", POOL.current(), 0, True, False, "", time.time())
                return

        # context prefix + scoped file focus + blast radius + semantic reuse + lessons
        prefix = caching.load_prefix(repo)
        focus = context_retrieval.focus_note(repo, t["prompt"]) if USE_RETRIEVAL else ""
        blast = blast_radius.note_for_task(repo, t["prompt"]) if USE_RETRIEVAL else ""
        # cross-project capability transfer: inject reusable published recipes for this task
        reuse = ""
        try:
            import capability
            reuse = capability.reuse_note(t["prompt"], project=name)
        except Exception:
            reuse = ""
        prompt = prefix + focus + blast + reuse + regression.inject(kb.inject(t["prompt"])) + feedback.INSTRUCTION + REUSE_FIRST
        t0 = time.time()

        # deterministic replay: re-run a captured run snapshot
        if kind == "replay" and t["prompt"].startswith("REPLAY:"):
            run_id = t["prompt"].split(":", 1)[1].strip()
            set_state(t["id"], state="RUNNING", note=f"replaying run {run_id}")
            try:
                replay.replay(run_id, repo)
                set_state(t["id"], state="DONE", note=f"replay complete: run {run_id}")
            except Exception as e:
                set_state(t["id"], state="BLOCKED", note=f"replay error: {e}")
            return

        # key rotation: ROTATE_KEY:<provider>:<name>  (enqueued by dashboard "Rotate" button)
        if t["prompt"].startswith("ROTATE_KEY:"):
            import rotate_keys
            parts = t["prompt"].split(":", 2)
            prov, kname = (parts[1] if len(parts) > 1 else ""), (parts[2] if len(parts) > 2 else "")
            set_state(t["id"], state="RUNNING", note=f"rotating {prov}/{kname}")
            result = rotate_keys.rotate(prov, kname, name)
            if result.get("ok"):
                set_state(t["id"], state="DONE", note=result.get("note", "rotated"))
            else:
                set_state(t["id"], state="BLOCKED", note=result.get("note", "manual rotation needed"))
            return

        # security panic: REVOKE_AND_STOP:<provider>  (dashboard "Stop + Revoke" button)
        if t["prompt"].startswith("REVOKE_AND_STOP:"):
            import rotate_keys  # kill_switch is already imported at module level
            prov = t["prompt"].split(":", 1)[1].strip()
            set_state(t["id"], state="RUNNING", note=f"revoking {prov} keys + stopping runner")
            try:
                # revoke all active secrets for this provider
                secrets = db.select("secrets", {"select": "*", "provider": f"eq.{prov}",
                                                "status": "eq.active"}) or []
                for s in secrets:
                    rotate_keys.rotate(prov, s["name"], s.get("project"))
                kill_switch.pause(scope="global", reason=f"security panic: {prov} keys revoked", by="runner")
                set_state(t["id"], state="DONE", note=f"revoked {len(secrets)} {prov} key(s), runner paused")
            except Exception as e:
                set_state(t["id"], state="BLOCKED", note=f"panic revoke error: {e}")
            return

        # speculative N-best: race a few approaches, keep the cheapest that passes
        if kind == "speculative":
            env = dict(os.environ); env.update(POOL.env_for(POOL.current()))
            res = speculative.run(repo, slug, base, prompt, test_cmd, env=env)
            w = res["winner"]
            if not w:
                set_state(t["id"], state="BLOCKED", note="no speculative variant passed")
                regression.record(name, slug, kind, "speculative N-best", "all variants failed tests", "")
                record(t, name, slug, kind, "speculative", POOL.current(), 1, False, False, "", t0); return
            result = integrate(repo, w["branch"], base, test_cmd, slug, "n-best winner", "passed")
            set_state(t["id"], state=result, model=w["model"], note=f"speculative winner {w['vslug']} ({w['model']})")
            record(t, name, slug, kind, w["model"], POOL.current(), 1, True, result == "MERGED", "", t0); return
        attempt = 0
        while attempt < 4:
            attempt += 1
            # COST-FIRST model routing: cheapest model that can do the job, escalate one tier
            # per failed attempt. Opus is used ONLY for genuinely heavy work or after retries —
            # an intake "opus"/"sonnet" tag is treated as advisory, NOT a license to burn Opus.
            # An explicit "haiku" hint is honored (lets authors force the cheap tier).
            routed = model_router.route(t["prompt"], attempt)
            hint = (t.get("model") or "").lower()
            if hint in ("haiku", model_router.HAIKU) and attempt == 1:
                model = model_router.HAIKU
            else:
                model = routed["model"]
            # cost SLO: cost_slo.py sets projects.cost_bias when an app is over its $/merge target.
            # honor it by forcing a cheaper tier (1 = no Opus, 2 = Haiku only) until the SLO recovers.
            bias = int(proj.get("cost_bias") or 0)
            if bias >= 2:
                model = model_router.HAIKU
            elif bias >= 1 and model == model_router.OPUS:
                model = model_router.SONNET
            coder = "claude" if t.get("_force_claude") else agentic_coders.pick(t, slot_index=attempt - 1)
            visible_model = model if coder == "claude" else f"{coder}:{model}"
            acct = POOL.current()
            set_state(t["id"], state="RUNNING", model=visible_model, attempt=attempt,
                      account=(acct or {}).get("name"), note=f"agentic coder: {coder}")
            subprocess.run([os.path.join(os.path.dirname(__file__), "setup-worktrees.sh"), slug, base],
                           cwd=repo, capture_output=True)
            wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", slug)
            env = dict(os.environ); env.update(POOL.env_for(acct))
            # inject this project's external-provider secrets (values never logged)
            try:
                env.update(secrets_manager.inject_env(name))
            except Exception:
                pass
            # Agentic file edits go through the coder seam. Claude Code remains the default
            # backend because it enforces the spend circuit; configured second coders can take
            # independent safe tasks and fall back to Claude on failure.
            # MULTI-MODEL PLAN: a cheaper NON-Claude strategy model plans before the coder drafts.
            # Makes model optimization visible (recorded as task_class='plan' in telemetry) and cuts
            # Claude token burn (Claude drafts against a plan instead of strategizing from scratch).
            draft_prompt = prompt
            try:
                if plan_stage.should_plan(t, prompt):
                    _plan_text, _plan_model = plan_stage.make_plan(t, prompt, name)
                    if _plan_text:
                        draft_prompt = plan_stage.inject(prompt, _plan_text, _plan_model)
                        set_state(t["id"], note=f"strategy: {_plan_model} -> draft: {coder}")
            except Exception:
                draft_prompt = prompt  # fail-soft: never block drafting on the plan step
            try:
                r = agentic_coders.run(coder, draft_prompt, model,
                                       cwd=wt if os.path.isdir(wt) else repo, env=env,
                                       project=name, max_turns=60, permission="acceptEdits",
                                       timeout=int(os.environ.get("TASK_TIMEOUT", "900")))
                r.setdefault("coder", coder)
            except subprocess.TimeoutExpired:
                set_state(t["id"], state="BLOCKED", note="timed out (>15m) — killed to free the slot")
                record(t, name, slug, kind, visible_model, acct, attempt, False, False, "timeout", t0); return
            except claude_cli.CircuitOpen as e:
                # spend ceiling hit: hold the task and pause everything until you intervene
                kill_switch.pause(scope="global", reason=f"cost circuit open: {e}", by="claude_cli")
                set_state(t["id"], state="QUEUED", note=f"cost circuit open: {e}; paused")
                time.sleep(10); return
            if r.get("skipped") == "kill_switch":
                set_state(t["id"], state="QUEUED", note="paused by kill switch (mid-run)")
                time.sleep(5); return
            rc = r["returncode"]
            run_cost = {"usd": r["cost_usd"], "input_tokens": r["input_tokens"],
                        "output_tokens": r["output_tokens"]}
            out = (r["text"] or "") + ("\n" + r["stderr"] if r.get("stderr") else "")
            low = out.lower()
            set_state(t["id"], log_tail=out[-2000:])
            # bidirectional learning: harvest the agent's feedback about the orchestration
            try:
                feedback.extract_and_store(out, project=name, slug=slug, task_id=t["id"])
            except Exception:
                pass
            # auto-resolve missing credentials (prompts you only if payment/manual is needed)
            try:
                credential_broker.detect_from_output(out, name)
            except Exception:
                pass

            if any(s in low for s in EXHAUST):
                nxt = POOL.mark_exhausted(acct)
                set_state(t["id"], state="RETRY", note=f"account exhausted -> {nxt}")
                if nxt and nxt != (acct or {}).get("name"):
                    attempt -= 1
                continue
            if any(s in low for s in RATE):
                back = min(300, 2 ** attempt * 5)
                set_state(t["id"], state="RETRY", note=f"rate-limited, backoff {back}s")
                time.sleep(min(back, 30)); continue

            tests_ok = rc == 0
            if not tests_ok:
                if coder != "claude":
                    t["_force_claude"] = True
                    set_state(t["id"], state="RETRY",
                              note=f"{coder} failed; retrying once through Claude Code")
                    continue
                set_state(t["id"], state="BLOCKED", note="agent run failed")
                regression.record(name, slug, kind, t["prompt"][:500], out[-500:], "agent run failed; re-scope or escalate model")
                record(t, name, slug, kind, visible_model, acct, attempt, False, False, out, t0, cost=run_cost); return

            # COMMIT the agent's edits. Agents edit the worktree (acceptEdits) but don't commit;
            # verify/confidence/integrate all diff `base...HEAD` (commit-based), so without this
            # every diff is empty -> verify trivially "passes", confidence defaults to 0.5, and
            # ff-merge ships nothing. This is what kept integration at 0.
            if not _commit_agent_work(wt, slug, t["prompt"]):
                # SESSION PROOF: distinguish "agent got no instructions" (stall) from a genuine no-op,
                # and retry ONCE with the full prompt re-injected before blocking. (2026-07-02: 8+
                # branches shipped nothing because the prompt never reached the agent.)
                try:
                    import session_proof
                    if not t.get("_proof_retry") and session_proof.STALL_RX.search(out or ""):
                        t["_proof_retry"] = True
                        prompt = session_proof.reinjection_prompt(t)
                        set_state(t["id"], state="RUNNING", note="session-proof: stall detected — re-injecting prompt")
                        continue
                except Exception:
                    pass
                set_state(t["id"], state="BLOCKED", note="agent produced no committable changes")
                regression.record(name, slug, kind, t["prompt"][:500], "no file changes", "agent investigated but changed nothing; re-scope task")
                record(t, name, slug, kind, visible_model, acct, attempt, True, False, out, t0, cost=run_cost); return
            # SESSION PROOF (positive path): verify the diff is real work echoing the task
            try:
                import session_proof
                proof = session_proof.verify_session(t, out, wt if os.path.isdir(wt) else repo, f"agent/{slug}")
                if not proof.get("ok") and not t.get("_proof_retry"):
                    t["_proof_retry"] = True
                    prompt = session_proof.reinjection_prompt(t)
                    set_state(t["id"], state="RUNNING", note=f"session-proof failed ({'; '.join(proof.get('reasons', [])[:2])}) — retrying once")
                    continue
            except Exception:
                pass

            # blast radius: find dependents of changed files, pass to verifier
            radius = blast_radius.radius_after(wt, base)
            deps = radius.get("dependents", [])

            # verification swarm BEFORE integrate (blast-radius-aware)
            v = verify.review_diff(wt, base, dependents=deps if deps else None, project=name)
            if v["verdict"] == "fail":
                set_state(t["id"], state="BLOCKED", note="verify: " + v["notes"])
                approval(name, "verify", f"Verification flagged {slug}",
                         why=v["notes"], risk="cheap-model review wants a human look",
                         detail=out[-3000:])
                regression.record(name, slug, kind, t["prompt"][:500], "verify: " + v["notes"], v["notes"])
                record(t, name, slug, kind, visible_model, acct, attempt, True, False, out, t0, cost=run_cost); return

            # quality gate: mutation + property tests (blocking if MUTATION_CMD/PROPERTY_CMD set)
            qg = quality_gate.run(wt)
            if not qg["pass"]:
                set_state(t["id"], state="BLOCKED", note="quality gate: " + qg["notes"])
                approval(name, "verify", f"Quality gate failed: {slug}",
                         why=qg["notes"], risk="mutation or property test score below threshold",
                         detail=out[-2000:])
                regression.record(name, slug, kind, t["prompt"][:500],
                                  "quality gate: " + qg["notes"], qg["notes"])
                record(t, name, slug, kind, visible_model, acct, attempt, True, False, out, t0, cost=run_cost); return

            # cross-model QA + legal-risk panel — a different model family reviews the diff
            _diff_for_judge = ""
            try:
                _diff_for_judge = subprocess.check_output(
                    ["git", "diff", f"{base}...HEAD"], cwd=wt, text=True, errors="replace")[:60000]
            except Exception:
                pass
            try:
                jv = judge.review(t["prompt"][:2000], _diff_for_judge, model, project=name)
            except Exception as _je:
                jv = {"verdict": "pass", "score": 6, "notes": f"judge unavailable ({_je})",
                      "legal_counsel_required": False, "legal_risk": ""}

            if jv["verdict"] != "pass":
                set_state(t["id"], state="BLOCKED", note="judge: " + jv["notes"][:200])
                approval(name, "verify", f"Cross-model review flagged {slug}",
                         why=jv["notes"], risk="judge panel rejected the diff",
                         detail=out[-2000:])
                regression.record(name, slug, kind, t["prompt"][:500],
                                  "judge: " + jv["notes"], "cross-model review failed; re-scope or fix")
                record(t, name, slug, kind, visible_model, acct, attempt, True, False, out, t0, cost=run_cost)
                return

            if jv.get("legal_counsel_required"):
                set_state(t["id"], state="BLOCKED", note="legal review required: " + jv["legal_risk"][:200])
                approval(name, "material", f"Legal review needed: {slug}",
                         why=jv["legal_risk"],
                         value="work passed tests + code review; legal clearance needed before merge",
                         risk="legal exposure identified by cross-model judge panel — DO NOT merge without counsel",
                         detail=out[-2000:], approvals_required=1)
                record(t, name, slug, kind, visible_model, acct, attempt, True, False, out, t0, cost=run_cost)
                return

            # Code merges are automatic after tests + verification + judge. Confidence is still
            # recorded, but it no longer creates human "Approve merge" cards; true legal-counsel
            # findings above remain operator gates.
            conf = {"confidence": None, "reason": ""}
            decision = "auto"
            if USE_CONFIDENCE:
                try:
                    proj_thresh = proj.get("confidence_threshold")
                    decision, conf = confidence.gate(wt, base, threshold=proj_thresh, project=name)
                except Exception as _ce:
                    conf = {"confidence": None, "reason": f"confidence unavailable ({_ce})"}
            if decision != "auto":
                conf = {**conf, "reason": (conf.get("reason") or "") + " [auto-merged to dev branch; no code-merge approval required]"}
                decision = "auto"
            if t.get("material"):
                if USE_CONFIDENCE:
                    conf = {**conf, "reason": (conf.get("reason") or "") + " [material: merged to dev branch; production release remains batch-gated]"}
            conf_score = conf.get("confidence")
            replay.capture(t["id"], name, slug, kind, visible_model, (acct or {}).get("name"),
                           repo, base, prompt, conf_score)

            result = integrate(repo, f"agent/{slug}", base, test_cmd, slug, v["notes"], "passed")
            POOL.mark_ok(acct)
            integrated = result == "MERGED"
            if integrated and sig:
                result_cache.store(sig, name, slug, f"agent/{slug}", v["notes"])
            # BUILDFAIL is not a task state — record it as BLOCKED with a build-fix note so auto_remediate
            # re-plans it (fix the build errors) instead of shipping build-breaking code.
            state_val = "BLOCKED" if result == "BUILDFAIL" else result
            set_state(t["id"], state=state_val, confidence=conf_score,
                      note=(f"integrate BUILDFAIL — production build red; fix build/type errors before merge"
                            if result == "BUILDFAIL"
                            else f"verify pass (conf={conf_score}); integrate={result} ({INTEGRATION_MODE})"))
            if result in ("CONFLICT", "TESTFAIL", "BUILDFAIL"):
                approval(name, "integrate", f"{slug} {result.lower()} on integrate",
                         why=f"could not auto-integrate ({result})", detail=out[-2000:])
                regression.record(name, slug, kind, t["prompt"][:500], f"integrate {result}",
                                  "run the prod build locally and fix all type/build errors before finishing")
            record(t, name, slug, kind, visible_model, acct, attempt, True, integrated, out, t0, cost=run_cost)
            return
        set_state(t["id"], state="BLOCKED", note="exhausted retries")


def _update_capability_eval(cap_slug, passed):
    """Write the real-world outcome back to capability_evals and recompute eval_pass_rate."""
    try:
        cap_rows = db.select("capabilities", {"select": "id", "slug": f"eq.{cap_slug}"}) or []
        if not cap_rows:
            return
        cap_id = cap_rows[0]["id"]
        # record a real-world eval (last_pass = whether tests+integrate succeeded)
        db.insert("capability_evals", {"capability_id": cap_id, "name": "real-world",
                                       "last_pass": passed, "updated_at": "now()"})
        # recompute pass-rate across all evals for this capability
        evals = db.select("capability_evals", {"select": "last_pass",
                                               "capability_id": f"eq.{cap_id}"}) or []
        scored = [e for e in evals if e.get("last_pass") is not None]
        if scored:
            rate = round(sum(1 for e in scored if e["last_pass"]) / len(scored), 3)
            vers = db.select("capability_versions",
                             {"select": "id", "capability_id": f"eq.{cap_id}",
                              "order": "created_at.desc", "limit": "1"}) or []
            if vers:
                db.update("capability_versions", {"id": vers[0]["id"]}, {"eval_pass_rate": rate})
    except Exception as e:
        print(f"capability eval update failed for {cap_slug}: {e}")


def record(t, project, slug, kind, model, acct, attempt, tests_ok, integrated, out, t0, cost=None):
    # Prefer REAL cost from claude_cli (json envelope); fall back to regex parse of text.
    row = cost if cost is not None else cost_ledger_row(project, slug, model, out)
    outcome = {
        "task_id": t["id"], "project": project, "slug": slug, "kind": kind,
        "model": model, "account": (acct or {}).get("name"), "attempts": attempt,
        "rate_limited": any(s in out.lower() for s in RATE),
        "tests_passed": tests_ok, "integrated": integrated,
        "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"],
        "usd": row["usd"], "wall_ms": int((time.time() - t0) * 1000)}
    # Track experiment assignment if this task is part of an A/B trial
    exp_meta = t.get("experiment_id")
    if exp_meta:
        outcome["experiment_id"] = exp_meta
        outcome["experiment_variant"] = t.get("experiment_variant", "control")
    try:
        db.insert("outcomes", outcome)
    except Exception as e:
        print(f"[record] outcomes insert skipped: {e}")
    # federated capability feedback: real-world outcomes flow back to capability_evals
    cap_slug = t.get("capability_slug")
    if cap_slug:
        _update_capability_eval(cap_slug, tests_ok and integrated)
    # close the "draft once for all apps" loop: scoop CANDIDATE-SHARED tags from the agent's
    # output -> shared_candidates; propose promotion once a pattern spans >=2 apps.
    try:
        candidate_shared.harvest(project, slug, kind, out)
    except Exception as e:
        print(f"[record] candidate_shared skipped: {e}")


def cost_ledger_row(project, slug, model, out):
    import re
    def n(s): return int(s.replace(",", ""))
    itok = sum(n(x[1]) for x in re.findall(r"(input|prompt)[ _]tokens[\"':\s]+([0-9,]+)", out, re.I))
    otok = sum(n(x[1]) for x in re.findall(r"(output|completion)[ _]tokens[\"':\s]+([0-9,]+)", out, re.I))
    pin, pout = cost_ledger.PRICES.get(model, (3.0, 15.0))
    return {"input_tokens": itok, "output_tokens": otok,
            "usd": round(itok / 1e6 * pin + otok / 1e6 * pout, 4)}


# ── Built-in periodic scheduler ───────────────────────────────────────────────
# Runs all periodic jobs as subprocesses of this process, which inherits the
# Terminal FDA grant (bypassing launchd TCC restrictions on ~/Documents/).
#
# job: if ends in .py → python3 runner/<job>; else → python3 periodic.py <job>
# schedule_type: 'interval' (seconds) | 'daily' (H,M) | 'weekly' (weekday,H,M)
_SCHEDULE = [
    ("txn-300",       "txn",                "interval", 300),
    ("policy-45",     "approval_policy.py", "interval", 45),    # owner policy: auto-approve all but narrow legal
    ("janitor-300",   "queue_janitor.py",   "interval", 300),   # auto-clear blockers: wedged runs, empty diffs, stranded cards, stale locks
    ("train-60",      "merge_train.py",     "interval", 60),    # serialized rebase→test→merge→push (THE integration path)
    ("ownermodel-300","owner_decision_model.py","interval",300),# draft/auto-apply gated decisions from owner precedent
    ("ev-900",        "ev_scheduler.py",    "interval", 900),   # EV-per-token queue ordering + zero-EV parking
    ("selfdeploy-180","self_deploy.py",     "interval", 180),   # canary-gated exec-into-new-code (no human restarts)
    ("intake-120",    "intake_watcher.py",  "interval", 120),   # auto-ingest dropped task lists
    ("drafts-90",     "decision_drafts.py", "interval", 90),    # auto-draft on founder directives


    ("anomaly-3600",  "anomaly.py",         "interval", 3600),
    ("roi-daily",     "roi",                "daily",    (0, 15)),
    ("deploy-daily",  "deploy",             "daily",    (2, 30)),
    ("maturity-daily","maturity.py",        "daily",    (2, 30)),
    ("selfrev-daily", "self_review.py",     "daily",    (3, 0)),
    ("batch-night",   "batch",              "daily",    (23, 30)),
    ("batch-morning", "batch",              "daily",    (8, 0)),
    ("spec-weekly",   "spec",               "weekly",   (0, 2, 0)),
    ("scout-weekly",  "scout",              "weekly",   (0, 3, 0)),
    ("chaos-weekly",  "chaos",              "weekly",   (6, 2, 0)),
    ("demand-weekly", "demand_mining.py",   "weekly",   (1, 4, 0)),
    ("radar-weekly",  "capability_radar.py","weekly",   (1, 3, 0)),
    ("digest-weekly", "portfolio_strategy_digest.py","weekly",(0, 1, 0)),# portfolio strategy clustering
    ("governor-60",   "resource_governor.py","interval",60),    # keep the Mac alive (faster cadence)
    ("sessions-120",  "session_watcher.py", "interval", 120),   # read paused/finished sessions
    ("loops-300",     "loops.py",           "interval", 300),   # per-app learning/remediation loops
    ("unstick-180",   "unstick",            "interval", 180),   # auto-requeue transient-blocked tasks
    ("dagfix-600",    "dagfix",             "interval", 600),   # heal dep graph: ghost/redundant/orphan
    ("batchmech-900", "batchmech",          "interval", 900),   # fold mechanical tasks (cold-start save)
    ("selftune-daily","selftune",           "daily",    (7, 0)),# outcome-driven confidence tuning
    ("cluster-300",   "cluster",            "interval", 300),   # batch pending approvals for humans
    ("appreview-1800","appreview",          "interval", 1800),  # perpetual cross-app AI/API triage review
    ("conventions-wk","conventions",        "weekly",   (0, 4, 30)),# refresh CLAUDE.md (caching compounds)
    ("billing-300",   "billingguard",       "interval", 300),   # trip kill switch on ANY real API spend
    ("forecast-600",  "forecast",           "interval", 600),   # project EOD spend; pre-empt runaways
    ("arbitrage-3600","arbitrage",          "interval", 3600),  # ride the cheapest capable provider frontier
    ("autoscale-300", "autoscale",          "interval", 300),   # scale up/down signal vs fleet capacity
    ("mergetrain-1200","mergetrain",        "interval", 1200),  # batch-merge non-overlapping green branches
    ("draftact-300",  "draftactions",       "interval", 300),   # pre-draft exact commands for action items
    ("prebrief-300",  "prebrief",           "interval", 300),   # plain-English legal decision briefs
    ("bizradar-900",  "bizradar",           "interval", 900),   # early business-model decision radar
    ("autoexec-60",   "autoexec",           "interval", 60),    # auto-run proven-safe steps + queued ones
    ("legaltri-300",  "legaltriage",        "interval", 300),   # classify legal cards; auto-clear routine
    ("decbriefs-300", "decisionbriefs",     "interval", 300),   # war-room briefs for legal/strategic decisions
    ("improve-3600",  "improve",            "interval", 3600),  # always-on '20-500X better?' idea miner
    ("improve-3am",   "improve",            "daily",    (3, 15)),# deeper improvement sweep in the research window
    ("improvemeas-dy","improvemeasure",     "daily",    (5, 20)),# learn which improvement kinds pay off
    ("committees-900","committees",         "interval", 900),   # expert committees weigh in on proposals/decisions
    ("committeecal-dy","committeecal",       "daily",    (5, 40)),# reweight committees + seats by predictive accuracy
    ("committeedock-dy","committeedocket",   "daily",    (4, 10)),# continuous docket: re-review shipped features
    ("committeedig-wk","committeedigest",    "daily",    (6, 5)), # owner brief of sharpest dissents/reversals
    ("committeeroll-1h","committeerollout",  "interval", 3600),  # advance canaries / auto-rollback + conclude A/Bs
    ("committeeboard-6h","committeeboard",   "interval", 21600), # portfolio bandit: allocate build effort + mine hypotheses
    ("committeewatch-3am","committeewatch",  "daily",    (3, 25)),# event-driven reg/security/competitor watch
    ("committeemins-dy","committeeminutes",  "daily",    (7, 0)), # plain-English board minutes for the owner
    ("committeekg-2am","committeekg",        "daily",    (2, 40)),# build the cross-committee knowledge graph
    ("committeemeta-wk","committeemeta",     "daily",    (2, 55)),# meta-review of the expert-assembly system
    ("remediate-180", "remediate",          "interval", 180),   # drive BLOCKED to zero (auto self-remedy)
    ("objective-3600","objective",          "interval", 3600),  # meta-controller: tune knobs toward north-star
    ("selfcheck-600", "selfcheck",          "interval", 600),   # periodic invariant assert + auto-heal
    ("push-180",      "pushdecisions",      "interval", 180),   # push new decisions/actions to email + Smarter
    ("selfheal-120",  "selfheal",           "interval", 120),   # auto-file fixes for prod incidents
    ("newapp-300",    "newapp",             "interval", 300),   # process one-command new-app requests
    ("autopilot-3600","autopilot",          "interval", 3600),  # portfolio autopilot (weights + attention)
    ("abedge-600",    "abedge",             "interval", 600),   # edge A/B promote/rollback on live traffic
    ("roadmap-weekly","roadmap",            "weekly",   (1, 6, 0)),# revenue-ranked weekly focus proposals
    ("worktreegc-300","worktreegc",         "interval", 300),   # remove stale agent worktrees (unblocks merges)
    ("releasetrain-600","releasetrain",     "interval", 600),   # accumulate on staging, QA, release to prod
    ("deployverify-120","deployverify",     "interval", 120),   # confirm Vercel deploy / auto-rollback
    ("stripe-daily",  "stripe",             "daily",    (6, 0)),  # pull real MRR from Stripe -> app_revenue
    ("ownerreport-wk","ownerreport",        "weekly",   (1, 7, 0)),# Monday owner report -> email
    ("revattr-daily", "revattr",            "daily",    (5, 45)),# attribute merges to revenue movement
    ("specwriter-wk", "specwriter",         "weekly",   (0, 5, 0)),# apps self-write SPEC.md
    ("prewarm-120",   "prewarm",            "interval", 120),   # warm next worktrees/context (0 spend)
    ("preflight-90",  "preflight",          "interval", 90),    # cheap multi-provider triage before agentic spend
    ("governor-900",  "governor",           "interval", 900),   # EV-based capacity allocation
    ("costslo-1800",  "costslo",            "interval", 1800),  # hold per-app $/merge SLOs
    ("promote-daily", "promote",            "daily",    (6, 30)),# productize proven capabilities
    ("dedup-600",     "dedup",              "interval", 600),   # collapse near-duplicate queued tasks
    ("canaryecon-600","canaryecon",         "interval", 600),   # promote/rollback canaries on cost+quality
    ("learnmerges-dy","learnmerges",        "daily",    (5, 30)),# reinforce from merged diffs
    ("metaloop-daily","meta_loop.py",       "daily",    (4, 0)),# loop on a loop
    ("feedback-daily","feedback_review.py", "daily",    (5, 0)),# agent->orchestrator improvements
    ("experiments-daily", "experiment_portfolio.py","daily", (3, 30)),# autonomous A/B experiment portfolio
    ("usage-daily",   "usage_meter.py",     "daily",    (6, 0)),# external API/subscription spend
]
_sched_last: dict = {}

# Jobs that NEVER call a model and are safe (even desirable) to run while paused:
# protect the Mac, and keep read-only spend/health telemetry flowing.
_SAFE_WHEN_PAUSED = {"resource_governor.py", "usage_meter.py", "anomaly.py", "roi", "txn",
                     "approval_policy.py", "queue_janitor.py",
                     "unstick", "dagfix", "batchmech", "selftune", "cluster",
                     "governor", "costslo", "promote", "prewarm", "billingguard",
                     "dedup", "canaryecon", "forecast", "arbitrage", "autoscale", "bizradar",
                     "pushdecisions", "selfheal", "newapp", "autopilot", "abedge",
                     "stripe", "ownerreport", "worktreegc", "remediate", "selfcheck"}

# Optional autonomous-improvement jobs that are NOT yet routed through claude_cli (so their
# spend isn't counted against the $40/day cap). OFF unless ENABLE_PROACTIVE_LOOPS=true.
_PROACTIVE = {"scout", "spec", "chaos", "self_review.py", "maturity.py", "demand_mining.py",
              "capability_radar.py", "meta_loop.py", "feedback_review.py", "conventions", "learnmerges",
              "experiment_portfolio.py"}
_PROACTIVE_ON = os.environ.get("ENABLE_PROACTIVE_LOOPS", "false").lower() == "true"

def _fire_periodic(job: str) -> None:
    # don't run uncounted proactive spenders unless explicitly enabled
    if job in _PROACTIVE and not _PROACTIVE_ON:
        return False
    # honor the kill switch for every scheduled job that could spend tokens, so a global
    # pause stops ALL spend (not just the main task loop) without restarting the runner.
    if job not in _SAFE_WHEN_PAUSED:
        try:
            if kill_switch.is_paused():
                print(f"[sched] {job} skipped (paused)", flush=True)
                return False
        except Exception:
            pass
    _dir = os.path.dirname(os.path.abspath(__file__))
    _home = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
    cmd = ([sys.executable, os.path.join(_dir, job)] if job.endswith(".py")
           else [sys.executable, os.path.join(_dir, "periodic.py"), job])
    # FAIL-SOFT logging: a scheduled job must NEVER be skipped just because its log file can't be
    # opened (e.g. ORCH_LOG_DIR points at a root-owned ~/Library/Logs path -> EPERM). Try the
    # configured dir, then runner/logs, then /tmp; if none is writable, run the job with output
    # discarded. Previously an EPERM here silently skipped merge_train/release_train/intake/etc.,
    # stalling the entire deploy pipeline.
    _base = os.environ.get("ORCH_LOG_DIR") or os.path.join(_home, "logs")
    _log = None
    for cand in (_base, os.path.join(_dir, "logs"), "/tmp/claude-orchestrator-logs"):
        try:
            os.makedirs(cand, exist_ok=True)
            _probe = os.path.join(cand, ".wtest")
            with open(_probe, "a"):
                pass
            os.remove(_probe)
            _log = os.path.join(cand, job.replace(".py", "").replace("_", "-"))
            break
        except Exception:
            continue
    try:
        if _log:
            with open(_log + ".log", "a") as lf, open(_log + ".err", "a") as ef:
                subprocess.Popen(cmd, stdout=lf, stderr=ef, cwd=_dir, env=os.environ.copy())
        else:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             cwd=_dir, env=os.environ.copy())
        return True
    except Exception as e:
        print(f"[sched] {job} launch failed: {e}")
        return False

def _scheduler_tick() -> None:
    now = time.time()
    dt = datetime.datetime.now()
    for key, job, stype, args in _SCHEDULE:
        last = _sched_last.get(key, 0)
        if stype == "interval":
            fire = (now - last) >= args
        elif stype == "daily":
            h, m = args
            fire = (dt.hour == h and dt.minute == m and now - last > 3600)
        else:  # weekly
            wd, h, m = args
            fire = (dt.weekday() == wd and dt.hour == h and dt.minute == m
                    and now - last > 3600 * 24)
        if fire:
            _sched_last[key] = now
            try:
                if _fire_periodic(job):
                    print(f"[sched] {job}", flush=True)
            except Exception as e:
                print(f"[sched] {job} error: {e}", flush=True)
# ─────────────────────────────────────────────────────────────────────────────


def _block_or_retry(t, note):
    """Reliability core: a TRANSIENT failure (network/rate/overload/timeout/notional-budget) is
    auto-requeued with backoff instead of being left terminal-BLOCKED — which is what froze
    `tomorrow`'s whole dependency tree behind a few foundation failures. Terminal failures
    (agent failed, verify/judge/legal) still BLOCK for a human. Returns the action taken."""
    try:
        import retry_policy
        tr = int(t.get("transient_retries") or 0)
        d = retry_policy.decide(note, tr)
        if d["action"] == "requeue":
            set_state(t["id"], state="QUEUED", note=d["note"], transient_retries=d["transient_retries"])
            time.sleep(min(d["backoff_s"], 20))  # brief in-thread backoff; frees the slot after
            return "requeue"
        set_state(t["id"], state="BLOCKED", note=d["note"], transient_retries=d["transient_retries"])
        return "block"
    except Exception:
        try:
            set_state(t["id"], state="BLOCKED", note=(note or "")[:300])
        except Exception:
            pass
        return "block"


def _run_task_safe(t):
    """Wrapper so an unhandled exception in run_task can NEVER leave a task stuck in RUNNING
    (which would leak a zombie, drain the queue, and defeat priority ordering). On any failure
    the task is auto-requeued if transient, else marked BLOCKED with the error captured."""
    try:
        run_task(t)
    except Exception as e:
        _block_or_retry(t, f"runner exception: {e}"[:300])


_LOCK_FD = None


def _acquire_singleton():
    """Guarantee ONE runner per machine. Multiple runners each size concurrency off total
    free RAM independently, so N runners can start N×MAX_PARALLEL heavy tasks at once and
    crash the Mac (and they share/exhaust the call budget). An exclusive file lock makes any
    extra launch (double-start, launchd relaunch) exit immediately. The lock auto-releases
    when the holding process dies, so a crash frees it."""
    global _LOCK_FD
    import fcntl
    home = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
    os.makedirs(home, exist_ok=True)
    lock_path = os.path.join(home, "runner.lock")
    # Open without truncating first. Losing contenders used to open with "w", fail the
    # flock, and still erase the active PID. That made startup hooks think no runner was
    # alive and spawn duplicate keepalives forever.
    _LOCK_FD = open(lock_path, "a+")
    try:
        fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_FD.seek(0)
        _LOCK_FD.truncate()
        _LOCK_FD.write(str(os.getpid()))
        _LOCK_FD.flush()
        return True
    except (BlockingIOError, OSError):
        return False


def main():
    if not _acquire_singleton():
        print("another runner already holds the lock — exiting (singleton guard).")
        return
    # HARD BILLING FIREWALL (first thing, before any model path): on Max subscription mode this strips
    # ANTHROPIC_API_KEY from the process + all child subprocesses, so batch_pass / api-accounts / edge
    # calls physically cannot bill the API. This is the systemic fix for the ~$500 June invoice.
    try:
        import subscription_guard
        g = subscription_guard.enforce()
        if g.get("enforced"):
            msg = (f"[billing-firewall] subscription mode: stripped {g['stripped'] or 'no'} API key(s) "
                   f"— API billing is now impossible for this run.")
            print(msg)
            if g["stripped"]:
                try:
                    approval("PORTFOLIO", "self", "Billing firewall stripped an API key at startup",
                             why=f"Found and removed {g['stripped']} so nothing can bill the API on your "
                                 f"Max plan. If this key is unused, delete it from .env and the Console.",
                             value="Prevents a repeat of the ~$500 API invoice.",
                             risk="None — subscription usage is unaffected.")
                except Exception:
                    pass
        else:
            print(f"[billing-firewall] WARNING: API billing is ALLOWED ({g.get('reason')}). "
                  f"You will be charged API rates. Unset ORCH_ALLOW_API_BILLING to block.")
    except Exception as _e:
        print(f"[billing-firewall] guard failed to load: {_e}")
    print(f"runner {RUNNER_ID} online -> {os.environ.get('SUPABASE_URL','(set SUPABASE_URL)')}")
    # STARTUP SELF-CHECK + AUTO-HEAL: assert firewall/worktrees/zombies/claimable/RAM and fix what it
    # can, posting a health line so a silent stall can never go unseen again.
    try:
        import startup_selfcheck
        startup_selfcheck.run(RUNNER_ID)
    except Exception as _e:
        print(f"[self-check] failed: {_e}")
    active = []
    _sched_t = 0.0
    _mem_log_t = 0.0
    _reload_t = 0.0
    import resource_governor
    while True:
        active = [th for th in active if th.is_alive()]
        # HOT RELOAD: pick up changed modules + .env live, so improvements take effect with NO restart.
        if time.time() - _reload_t > 5:
            _reload_t = time.time()
            try:
                import hot_reload
                hot_reload.maybe_reload()
            except Exception:
                pass
        # SELF-DEPLOY: graceful exec-into-new-code when self_deploy requested it (canary-gated)
        # and no tasks are mid-flight; keepalive.sh restarts us into the new commit.
        try:
            _rr = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".restart_requested")
            if not active and os.path.exists(_rr):
                print("[self-deploy] restart requested — exiting for keepalive to reload new code")
                os.remove(_rr)
                sys.exit(0)
        except SystemExit:
            raise
        except Exception:
            pass
        try:
            db.heartbeat(RUNNER_ID, socket.gethostname(), len(active))
            # live throttle: the resource governor lowers this under disk/RAM pressure
            # read MAX_PARALLEL live from env each loop so concurrency is tunable via .env + hot_reload
            # WITHOUT a restart (RAM permitting; resource_governor still clamps to protect the Mac).
            eff_limit = min(int(os.environ.get("MAX_PARALLEL", MAX_PARALLEL)), resource_governor.current_limit())
            # global kill switch: halt all task claiming instantly
            if kill_switch.is_paused():
                eff_limit = 0
            if len(active) < eff_limit:
                # REAL-TIME memory gate: checked every loop (not just every governor tick),
                # so a sudden RAM drop can't crash the Mac between 60s governor runs.
                ok, why = resource_governor.can_claim(len(active))
                if not ok:
                    if time.time() - _mem_log_t > 60:
                        print(f"[mem-gate] holding new claims: {why}")
                        _mem_log_t = time.time()
                else:
                    t = db.claim_task(RUNNER_ID)
                    if t:
                        # REUSE-FIRST: adapt an already-solved implementation instead of rebuilding
                        try:
                            import reuse_first
                            t = reuse_first.pre_claim_hook(t)
                        except Exception:
                            pass
                        th = threading.Thread(target=_run_task_safe, args=(t,), daemon=True)
                        th.start(); active.append(th); continue
        except Exception as e:
            print("poll error:", e)
        if time.time() - _sched_t >= 60:
            _sched_t = time.time()
            _scheduler_tick()
        time.sleep(POLL)


if __name__ == "__main__":
    main()
