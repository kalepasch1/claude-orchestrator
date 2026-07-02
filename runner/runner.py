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
import db, bandit, verify, caching, account_pool, cost_ledger
import knowledge_embed as kb
import regression, budget, speculative, pr_integrate
import context_retrieval, result_cache
import confidence, blast_radius, replay
import feedback
import kill_switch, secrets_manager, credential_broker, quality_gate
import claude_cli, waste, experiment_router

INTEGRATION_MODE = os.environ.get("INTEGRATION_MODE", "local")  # local | pr
USE_CACHE = os.environ.get("RESULT_CACHE", "true").lower() == "true"
USE_RETRIEVAL = os.environ.get("SCOPED_CONTEXT", "true").lower() == "true"
USE_CONFIDENCE = os.environ.get("CONFIDENCE_GATE", "true").lower() == "true"

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
RUNNER_ID = os.environ.get("RUNNER_ID", socket.gethostname() + "-" + str(os.getpid()))
POLL = int(os.environ.get("POLL_SECONDS", "5"))
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "2"))
RATE = ("temporarily limiting", "rate limit", "429", "overloaded", "too many requests")
EXHAUST = ("usage limit", "out of credits", "insufficient_quota", "quota")
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
    db.insert("approvals", {"project": project, "kind": kind, "title": title, **kw})


def integrate(repo, branch, base, test_cmd, slug="", verify_notes="", test_summary="passed"):
    # PR-native: push, open PR, let YOUR CI (sfc/gitleaks/vercel) gate, auto-merge on green.
    if INTEGRATION_MODE == "pr":
        r = pr_integrate.open_pr(repo, branch, base, slug, verify_notes, test_summary)
        if not r.get("ok"):
            return "CONFLICT"
        outcome = pr_integrate.wait_and_merge(repo, branch)
        return {"MERGED": "MERGED", "CHECKS_FAILED": "TESTFAIL", "OPEN": "BLOCKED"}.get(outcome, "BLOCKED")
    # local ff-merge
    if subprocess.run(["git", "rebase", base, branch], cwd=repo).returncode != 0:
        subprocess.run(["git", "rebase", "--abort"], cwd=repo)
        return "CONFLICT"
    subprocess.run(["git", "checkout", branch], cwd=repo)
    if subprocess.run(test_cmd, cwd=repo, shell=True).returncode != 0:
        return "TESTFAIL"
    subprocess.run(["git", "checkout", base], cwd=repo)
    subprocess.run(["git", "merge", "--ff-only", branch], cwd=repo)
    return "MERGED"


def run_task(t):
    with _sem:
        proj = projects(t["project_id"]).get(t["project_id"], {})
        repo = proj.get("repo_path", os.getcwd())
        name = proj.get("name", "repo")
        base = t.get("base_branch", "main")
        slug = t["slug"]
        kind = t.get("kind", "build")
        test_cmd = proj.get("test_cmd") or os.environ.get("TEST_CMD", "npm test")

        # kill switch: stop all spend on this project (or globally) at a click
        if kill_switch.is_paused(name):
            set_state(t["id"], state="QUEUED", note="paused by kill switch")
            time.sleep(5); return

        # budget guardrail: hold the task if the project hit its monthly cap
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
        prompt = prefix + focus + blast + regression.inject(kb.inject(t["prompt"])) + feedback.INSTRUCTION
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
            import rotate_keys, kill_switch
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
            model = t.get("model") or bandit.choose(db, kind, t["prompt"])
            acct = POOL.current()
            set_state(t["id"], state="RUNNING", model=model, attempt=attempt,
                      account=(acct or {}).get("name"))
            subprocess.run([os.path.join(os.path.dirname(__file__), "setup-worktrees.sh"), slug, base],
                           cwd=repo, capture_output=True)
            wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", slug)
            env = dict(os.environ); env.update(POOL.env_for(acct))
            # inject this project's external-provider secrets (values never logged)
            try:
                env.update(secrets_manager.inject_env(name))
            except Exception:
                pass
            # ALL model spend goes through claude_cli: it honors the kill switch, hard-caps
            # $/hour, $/day and calls/hour, and captures REAL cost via --output-format json.
            try:
                r = claude_cli.run(prompt, model,
                                   cwd=wt if os.path.isdir(wt) else repo, env=env,
                                   project=name, max_turns=60, permission="acceptEdits")
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
                set_state(t["id"], state="BLOCKED", note="agent run failed")
                regression.record(name, slug, kind, t["prompt"][:500], out[-500:], "agent run failed; re-scope or escalate model")
                record(t, name, slug, kind, model, acct, attempt, False, False, out, t0, cost=run_cost); return

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
                record(t, name, slug, kind, model, acct, attempt, True, False, out, t0, cost=run_cost); return

            # quality gate: mutation + property tests (blocking if MUTATION_CMD/PROPERTY_CMD set)
            qg = quality_gate.run(wt)
            if not qg["pass"]:
                set_state(t["id"], state="BLOCKED", note="quality gate: " + qg["notes"])
                approval(name, "verify", f"Quality gate failed: {slug}",
                         why=qg["notes"], risk="mutation or property test score below threshold",
                         detail=out[-2000:])
                regression.record(name, slug, kind, t["prompt"][:500],
                                  "quality gate: " + qg["notes"], qg["notes"])
                record(t, name, slug, kind, model, acct, attempt, True, False, out, t0, cost=run_cost); return

            # confidence-gated autonomy: high -> auto-merge; low -> human; high-risk -> two-key
            conf = {"confidence": None}
            decision = "auto"
            if USE_CONFIDENCE:
                proj_thresh = proj.get("confidence_threshold")
                decision, conf = confidence.gate(wt, base, threshold=proj_thresh, project=name)
            # MATERIAL tasks (money/auth/schema/filings/prod) never auto-merge — force approval.
            if t.get("material"):
                decision = "two_key"
                conf = {**conf, "reason": (conf.get("reason") or "") + " [material: human approval required]"}
            conf_score = conf.get("confidence")
            replay.capture(t["id"], name, slug, kind, model, (acct or {}).get("name"),
                           repo, base, prompt, conf_score)
            if decision != "auto":
                req = 2 if decision == "two_key" else 1
                set_state(t["id"], state="BLOCKED", confidence=conf_score,
                          note=f"awaiting {'two-key ' if req == 2 else ''}approval (confidence {conf_score})")
                approval(name, "material" if decision == "two_key" else "verify",
                         f"Approve merge of {slug}", why=conf.get("reason"),
                         value="agent work passed tests + verification",
                         risk=("HIGH-RISK path — needs two approvers" if req == 2 else "below auto-merge confidence"),
                         detail=out[-2000:], approvals_required=req)
                record(t, name, slug, kind, model, acct, attempt, True, False, out, t0, cost=run_cost); return

            result = integrate(repo, f"agent/{slug}", base, test_cmd, slug, v["notes"], "passed")
            POOL.mark_ok(acct)
            integrated = result == "MERGED"
            if integrated and sig:
                result_cache.store(sig, name, slug, f"agent/{slug}", v["notes"])
            set_state(t["id"], state=result, confidence=conf_score,
                      note=f"verify pass (conf={conf_score}); integrate={result} ({INTEGRATION_MODE})")
            if result in ("CONFLICT", "TESTFAIL"):
                approval(name, "integrate", f"{slug} {result.lower()} on integrate",
                         why=f"could not auto-integrate ({result})", detail=out[-2000:])
                regression.record(name, slug, kind, t["prompt"][:500], f"integrate {result}", "stay within file scope; rebase early")
            record(t, name, slug, kind, model, acct, attempt, True, integrated, out, t0, cost=run_cost)
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
    db.insert("outcomes", outcome)
    # federated capability feedback: real-world outcomes flow back to capability_evals
    cap_slug = t.get("capability_slug")
    if cap_slug:
        _update_capability_eval(cap_slug, tests_ok and integrated)


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
    ("merge-60",      "approval_merge.py",  "interval", 60),    # complete approved merges
    ("intake-120",    "intake_watcher.py",  "interval", 120),   # auto-ingest dropped task lists


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
    ("governor-180",  "resource_governor.py","interval",180),   # keep the Mac alive
    ("sessions-120",  "session_watcher.py", "interval", 120),   # read paused/finished sessions
    ("loops-300",     "loops.py",           "interval", 300),   # per-app learning/remediation loops
    ("metaloop-daily","meta_loop.py",       "daily",    (4, 0)),# loop on a loop
    ("feedback-daily","feedback_review.py", "daily",    (5, 0)),# agent->orchestrator improvements
    ("miner-daily",   "improvement_miner.py","daily",   (3, 30)),# autonomous A/B experiment portfolio
    ("usage-daily",   "usage_meter.py",     "daily",    (6, 0)),# external API/subscription spend
]
_sched_last: dict = {}

# Jobs that NEVER call a model and are safe (even desirable) to run while paused:
# protect the Mac, and keep read-only spend/health telemetry flowing.
_SAFE_WHEN_PAUSED = {"resource_governor.py", "usage_meter.py", "anomaly.py", "roi", "txn"}

# Optional autonomous-improvement jobs that are NOT yet routed through claude_cli (so their
# spend isn't counted against the $40/day cap). OFF unless ENABLE_PROACTIVE_LOOPS=true.
_PROACTIVE = {"scout", "spec", "chaos", "self_review.py", "maturity.py", "demand_mining.py",
              "capability_radar.py", "meta_loop.py", "feedback_review.py", "improvement_miner.py"}
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
    _log = os.path.expanduser(f"~/Library/Logs/claude-orchestrator/{job.replace('.py','').replace('_','-')}")
    os.makedirs(os.path.dirname(_log + ".log"), exist_ok=True)
    cmd = ([sys.executable, os.path.join(_dir, job)] if job.endswith(".py")
           else [sys.executable, os.path.join(_dir, "periodic.py"), job])
    with open(_log + ".log", "a") as lf, open(_log + ".err", "a") as ef:
        subprocess.Popen(cmd, stdout=lf, stderr=ef, cwd=_dir, env=os.environ.copy())
    return True

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


def main():
    print(f"runner {RUNNER_ID} online -> {os.environ.get('SUPABASE_URL','(set SUPABASE_URL)')}")
    active = []
    _sched_t = 0.0
    import resource_governor
    while True:
        active = [th for th in active if th.is_alive()]
        try:
            db.heartbeat(RUNNER_ID, socket.gethostname(), len(active))
            # live throttle: the resource governor lowers this under disk/RAM pressure
            eff_limit = min(MAX_PARALLEL, resource_governor.current_limit())
            # global kill switch: halt all task claiming instantly
            if kill_switch.is_paused():
                eff_limit = 0
            if len(active) < eff_limit:
                t = db.claim_task(RUNNER_ID)
                if t:
                    th = threading.Thread(target=run_task, args=(t,), daemon=True)
                    th.start(); active.append(th); continue
        except Exception as e:
            print("poll error:", e)
        if time.time() - _sched_t >= 60:
            _sched_t = time.time()
            _scheduler_tick()
        time.sleep(POLL)


if __name__ == "__main__":
    main()
