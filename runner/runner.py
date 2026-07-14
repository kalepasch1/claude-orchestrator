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
import os, sys, time, json, socket, subprocess, threading, datetime, hashlib, faulthandler, signal
import log as _log_mod
_log = _log_mod.get("runner")

# ENV SANITY (2026-07-14): the runner (and everything it spawns — agents, npm installs, builds)
# sometimes inherits NODE_ENV=production from its launcher. Under NODE_ENV=production, `npm
# install` silently OMITS devDependencies, so builds fail with "Could not load <module>. Is it
# installed?" (@nuxtjs/supabase, tailwind, vitest, tsc...) and node_modules trees end up
# half-populated/corrupt. Build tools set their own production mode during `nuxt build` etc.;
# an inherited global NODE_ENV only breaks installs. Strip it for this process tree.
os.environ.pop("NODE_ENV", None)

# Auto-load .env from the runner's own directory (works regardless of CWD)
_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_RUNNER_DIR)
_CANONICAL_RUNTIME_HOME = os.path.join(_REPO_ROOT, ".runtime")
_env_path = os.path.join(_RUNNER_DIR, ".env")
if os.path.isfile(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
if os.environ.get("ORCH_CANONICAL_RUNTIME_HOME", "true").lower() in ("1", "true", "yes", "on"):
    os.environ["CLAUDE_ORCH_HOME"] = _CANONICAL_RUNTIME_HOME


_LOCK_FD = None
_EARLY_SINGLETON_LOCKED = False


def _acquire_singleton():
    """Guarantee ONE runner per machine, before any import-time DB/network work."""
    global _LOCK_FD
    import fcntl
    home = os.environ.get("CLAUDE_ORCH_HOME", _CANONICAL_RUNTIME_HOME)
    os.makedirs(home, exist_ok=True)
    lock_path = os.environ.get("ORCH_RUNNER_LOCK_FILE") or os.path.join(home, "runner.lock")
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


if __name__ == "__main__":
    try:
        faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)
    except Exception as e:
        _log.debug("hook faulthandler failed: %s", e)
    if not _acquire_singleton():
        print("another runner already holds the lock — exiting (singleton guard).")
        sys.exit(0)
    _EARLY_SINGLETON_LOCKED = True

sys.path.insert(0, _RUNNER_DIR)
import db, bandit, verify, caching, account_pool, cost_ledger, model_router, candidate_shared
import prompt_assembler
import knowledge_embed as kb
import regression, budget, speculative, pr_integrate
import context_retrieval, result_cache
import confidence, blast_radius, replay
import feedback
import kill_switch, secrets_manager, credential_broker, quality_gate
import claude_cli, waste, judge, experiment_router, decision_engine
import agentic_coders
import plan_stage
try:
    import pipeline_contract
except ModuleNotFoundError:
    class pipeline_contract:
        original_request = staticmethod(lambda p: p)
        wrap_prompt = staticmethod(lambda body, **kw: body)
import task_artifacts
import diff_compiler
import parallel_gates, combined_gate, cache_gate_bypass, committee_bypass
import smart_compress, speculative_exec, colosseum
import brain_compiler, mesh_optimizer
import prompt_bankruptcy, model_portfolios, debate_compress
import presettlement_sim, model_slashing, intent_graph
import cross_project_templates, predictive_scheduler, session_cache
import graduated_autonomy, live_bidding, multi_agent_pipeline
import speculative_diff, adaptive_budget, transfer_learning
import pipeline_fusion, prompt_distillation, output_recycling
import cade_tournaments
import queue_elimination, adaptive_pipeline, unified_knowledge
import fast_path, batch_fusion, proof_propagation
import intent_compiler, ensemble_predictor, bankruptcy_decompose
import portfolio_rebalancer
import capacity_pacer, account_partition, generator_feedback
import exhaustion_signal, surge_planner
import agentic_repair
import cowork_dispatch
try:
    import warm_pool
except ImportError:
    warm_pool = None

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
# Size the concurrency semaphore HIGH so it is never the binding constraint — the real, LIVE
# limit is eff_limit (min of env MAX_PARALLEL and the governor) checked every dispatch loop
# (line ~2227). A boot-time Semaphore(MAX_PARALLEL) silently capped the whole machine at whatever
# MAX_PARALLEL happened to be at boot (a stale/low value throttled a 48GB box to 4 lanes on
# 2026-07-10). Governing via eff_limit means fleet_config MAX_PARALLEL changes take effect live.
_sem = threading.Semaphore(int(os.environ.get("ORCH_SEM_MAX", "48")))
_projects = {}
MAX_AGENT_PROMPT_CHARS = int(os.environ.get("ORCH_MAX_AGENT_PROMPT_CHARS", "36000"))


def projects(project_id=None):
    global _projects
    if not _projects or (project_id and project_id not in _projects):
        rows = db.select("projects") or []
        # Resolve each project's repo_path to THIS machine's clone (a second Mac stores the same
        # repos under a different home). Read-time only — never written back to the shared row.
        for p in rows:
            p["repo_path"] = db.localize_repo_path(p.get("repo_path"))
        _projects = {p["id"]: p for p in rows}
    return _projects


def set_state(task_id, **kw):
    kw["updated_at"] = "now()"
    db.update("tasks", {"id": task_id}, kw)


def _next_non_claude_coder(task, exclude=()):
    """Pick the cheapest capable non-Claude coder, usually local Ollama, excluding failed backends."""
    excluded = set(exclude or ())
    try:
        pool = []
        for spec in agentic_coders._pool():
            name = spec.get("name")
            if not name or name == "claude" or name in excluded:
                continue
            if not agentic_coders._within_cap(spec):
                continue
            if not agentic_coders._allowed_by_terms(spec, agentic_coders._task_sensitivity(task)):
                continue
            pool.append(spec)
        if not pool:
            return None
        def cost(spec):
            return int(spec.get("cost") if spec.get("cost") is not None else 9)
        return sorted(pool, key=lambda c: (cost(c), -int(c.get("cap") or 0), c.get("name") or ""))[0].get("name")
    except Exception:
        return None


def approval(project, kind, title, **kw):
    # fault-tolerant: a flood-guard dedup rejection (HTTP 409) must NOT kill the task
    try:
        db.insert("approvals", {"project": project, "kind": kind, "title": title, **kw})
    except Exception as e:
        print(f"[approval] skipped ({title[:40]}): {e}")


def integrate(repo, branch, base, test_cmd, slug="", verify_notes="", test_summary="passed", project=None):
    if (os.environ.get("ORCH_CANONICAL_INTEGRATION", "true").lower() in ("true", "1", "yes")
            and project and slug):
        try:
            import merge_train
            merge_train.ensure_integration_card(
                project, slug,
                title=f"merge of {slug}",
                why="agent work passed tests/review; canonical train should integrate it",
                detail=(verify_notes or "")[-2000:],
                status="approved",
                decided_by="canonical-train:runner",
            )
            merge_train.train_run()
            rows = db.select("tasks", {"select": "state,note", "slug": f"eq.{slug}", "limit": "5"}) or []
            latest = next((r for r in rows if r.get("state") in ("MERGED", "TESTFAIL", "CONFLICT", "BLOCKED")),
                          rows[0] if rows else {})
            state = latest.get("state")
            note = str(latest.get("note") or "")
            if state == "MERGED":
                return "MERGED"
            if state == "TESTFAIL":
                return "TESTFAIL"
            if state == "CONFLICT":
                return "CONFLICT"
            if "BUILDFAIL" in note or "build red" in note.lower():
                return "BUILDFAIL"
            return "BLOCKED"
        except Exception as e:
            # ZERO-TRUST: log the fallback clearly so we can track how often the side door fires.
            # The canonical train IS the integration path; this fallback should converge to zero.
            print(f"[integrate] ZERO-TRUST WARNING: canonical train failed, using legacy path: {e}")
            try:
                db.insert("resource_events", {"kind": "zero_trust_fallback",
                    "detail": f"slug={slug} error={str(e)[:200]}",
                    "action": "legacy_merge", "created_at": "now()"})
            except Exception as e:
                _log.debug("hook zero_trust_event failed: %s", e)
    # PR-native: push, open PR, let YOUR CI (sfc/gitleaks/vercel) gate, auto-merge on green.
    if INTEGRATION_MODE == "pr":
        r = pr_integrate.open_pr(repo, branch, base, slug, verify_notes, test_summary)
        if not r.get("ok"):
            return "CONFLICT"
        outcome = pr_integrate.wait_and_merge(repo, branch)
        return {"MERGED": "MERGED", "CHECKS_FAILED": "TESTFAIL", "OPEN": "BLOCKED"}.get(outcome, "BLOCKED")
    # local ff-merge
    # CONCURRENCY FIX (2026-07-08 merge-stall root cause): this legacy path and merge_train's
    # canonical path both mutate the SAME shared repo's git refs (branch pointers, rebases,
    # fast-forwards). Multiple worker threads can reach here for the same repo at once (one
    # thread per RUNNING task). Without a lock, concurrent rebases/ff-merges raced each other,
    # producing spurious conflicts. Serialize per-repo; see repo_lock.py for the full incident
    # writeup. On contention, treat as a transient conflict so the task's normal redo path
    # (not a hard failure) picks it back up next cycle instead of stalling silently.
    import repo_lock
    with repo_lock.hold(repo, timeout=120) as got_lock:
        if not got_lock:
            print(f"[integrate] {slug}: repo busy (another integration holds the lock) — treating as redo-able conflict")
            return "CONFLICT"
        # FIX: free the branch from its leftover agent worktree first, or `git rebase` fails with
        # "already checked out" — which was being mislabeled as CONFLICT and blocked ALL auto-merges.
        try:
            import approval_merge
            approval_merge._free_branch(repo, branch)
        except Exception as e:
            _log.debug("hook free_branch failed: %s", e)
        # clean fast-forward when the branch is strictly ahead of base (the normal case) — no rebase needed
        ahead = subprocess.run(["git", "merge-base", "--is-ancestor", base, branch],
                               cwd=repo, capture_output=True).returncode == 0
        if not ahead:
            # Isolated worktree, never repo's own checkout — see approval_merge._rebase_isolated's
            # docstring for why (a direct `git rebase base branch` here left the orchestrator's own
            # primary checkout parked on a stray branch, which is very likely the root cause of the
            # 2026-07-08 finding that repo's checked-out branch kept changing between checks).
            import approval_merge
            if not approval_merge._rebase_isolated(repo, base, branch):
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
                    try:
                        import build_fixer
                        build_fixer.save_log(slug, blog)   # keep the log for a model-generated fix directive
                    except Exception as e:
                        _log.debug("hook build_fixer failed: %s", e)
                    return "BUILDFAIL"
        except Exception as _be:
            print(f"[integrate] build gate skipped ({_be})")
        # merge into `base` without needing it checked out (HEAD may be another branch)
        if subprocess.run(["git", "fetch", ".", f"{branch}:{base}"], cwd=repo, capture_output=True).returncode != 0:
            return "CONFLICT"
        staging = os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev")
        batch_release = os.environ.get("ORCH_BATCH_DEV_RELEASE", "true").lower() in ("1", "true", "yes", "on")
        direct_prod_allowed = os.environ.get("ORCH_ALLOW_DIRECT_PROD_MERGE", "false").lower() in ("1", "true", "yes", "on")
        push_dev = os.environ.get("ORCH_PUSH_ON_DEV_MERGE", "true").lower() in ("1", "true", "yes", "on")
        push_prod = os.environ.get("ORCH_PUSH_ON_MERGE", "false").lower() == "true"
        if (base == staging and push_dev) or (base != staging and push_prod and (not batch_release or direct_prod_allowed)):
            subprocess.run(["git", "push", "origin", base], cwd=repo, capture_output=True)
        try:
            import approval_merge
            approval_merge._free_branch(repo, branch)
        except Exception as e:
            _log.debug("hook free_branch failed: %s", e)
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


def _branch_exists(repo, branch):
    if not branch:
        return False
    return subprocess.run(["git", "rev-parse", "--verify", branch], cwd=repo,
                          capture_output=True).returncode == 0


def _normalize_task_base(repo, proj, requested):
    """Resolve task base to a local branch that actually exists before worktree setup.

    Old tasks and generated tasks often say "main" even when a repo uses master or a
    configured default. Normalizing here prevents empty diffs, failed worktree setup,
    stale branch churn, and wasted agent retries.
    """
    for b in (requested, proj.get("default_base"), proj.get("prod_branch"), "main", "master"):
        if _branch_exists(repo, b):
            return b
    return requested or proj.get("default_base") or "main"


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
        prod = _detect_prod_branch(repo, proj)
        # RECURRENT-CONFLICT FIX: keep the integration base CURRENT with prod. After external pushes
        # (e.g. hotfixes to origin/main) a stale local dev drifts BEHIND prod, so every agent branch
        # rebased onto it conflicts and releases can't promote. Fetch prod, then reset dev to it
        # UNLESS dev is strictly ahead (contains all of prod + unreleased merges). Fail-soft; a
        # no-op if dev is checked out in a worktree (the recovery script frees those).
        subprocess.run(["git", "fetch", "origin", prod], cwd=repo, capture_output=True, timeout=90)
        pref = f"origin/{prod}" if subprocess.run(["git", "rev-parse", "--verify", f"origin/{prod}"],
                                                  cwd=repo, capture_output=True).returncode == 0 else prod
        if subprocess.run(["git", "rev-parse", "--verify", dev], cwd=repo,
                          capture_output=True).returncode != 0:
            subprocess.run(["git", "branch", dev, pref], cwd=repo, capture_output=True)
        else:
            strictly_ahead = subprocess.run(["git", "merge-base", "--is-ancestor", pref, dev],
                                            cwd=repo, capture_output=True).returncode == 0
            if not strictly_ahead:
                subprocess.run(["git", "branch", "-f", dev, pref], cwd=repo, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return task_base
    return dev


def _commit_agent_work(wt, slug, prompt, base="main"):
    """Capture the agent's work. Returns True if the branch has real work to integrate.

    CRITICAL: the build-to-green prompt instructs agents to COMMIT their own work, and Claude Code
    (run with --dangerously-skip-permissions) does. The old logic only staged UNCOMMITTED changes and,
    finding nothing staged when the agent had already committed, wrongly returned False — silently
    DISCARDING every self-committed change (the reason 150 runs/hour shipped 0 commits). Fix: commit any
    leftover uncommitted changes AND treat a branch that is ahead of base (agent's own commits) as real
    work. Only a branch with no staged changes AND no commits ahead of base is a true no-op."""
    _git_name = os.environ.get("FLEET_GIT_AUTHOR_NAME", "Kale Aaron Pasch")
    _git_email = os.environ.get("FLEET_GIT_AUTHOR_EMAIL", "kalepasch@gmail.com")
    env = {**os.environ,
           "GIT_AUTHOR_NAME": _git_name, "GIT_AUTHOR_EMAIL": _git_email,
           "GIT_COMMITTER_NAME": _git_name, "GIT_COMMITTER_EMAIL": _git_email}
    try:
        subprocess.run(["git", "add", "-A"], cwd=wt, env=env, capture_output=True)
        # commit any uncommitted changes the agent left staged
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=wt, env=env).returncode != 0:
            msg = f"agent: {slug}\n\n{(prompt or '')[:300]}"
            subprocess.run(["git", "commit", "--no-verify", "-m", msg], cwd=wt, env=env,
                           capture_output=True, text=True)
        # real work = the branch is ahead of base (covers BOTH our commit above and the agent's own commits)
        ahead = subprocess.run(["git", "rev-list", "--count", f"{base}..HEAD"], cwd=wt, env=env,
                               capture_output=True, text=True)
        try:
            return int((ahead.stdout or "0").strip()) > 0
        except ValueError:
            # base ref not found in the worktree — fall back to "did we just stage anything?"
            return subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=wt, env=env).returncode != 0
    except Exception as e:
        print(f"[commit] {slug}: {e}")
        return False


def _must_run_agent_for_evidence(task, slug):
    """Forced canaries exist to measure the coder, so old branches must not short-circuit them."""
    if not (task or {}).get("force_coder"):
        return False
    kind = str((task or {}).get("kind") or "").lower()
    note = str((task or {}).get("note") or "").lower()
    s = str(slug or (task or {}).get("slug") or "")
    return kind == "canary" or s.startswith("canary-") or "-canary-" in s or "coder-canary" in note


def _cap_agent_prompt(prompt):
    """Keep Claude Code requests comfortably below context limits after tool/system overhead."""
    text = prompt or ""
    if len(text) <= MAX_AGENT_PROMPT_CHARS:
        return text
    head = min(20000, MAX_AGENT_PROMPT_CHARS // 3)
    tail = MAX_AGENT_PROMPT_CHARS - head
    return (
        text[:head].rstrip() +
        "\n\n[ORCHESTRATOR COMPACTION: middle context removed to stay below model limits. "
        "Use the focus files, task contract, and final request below; inspect repo files directly "
        "instead of relying on omitted transcript bulk.]\n\n" +
        text[-tail:].lstrip()
    )


BUILD_MANDATE = (
    "\n\n---\nBEFORE YOU FINISH (required): run the project's production build and, if present, its "
    "tests (e.g. `npm run build` then the test command). If ANYTHING fails, fix it and re-run until the "
    "build is GREEN. Make the smallest correct change and reuse existing code. Do not finish with a red "
    "build, and do not finish by only describing changes — actually apply your edits to the files.")


def _agentic_repair_continue(t, category, failure, attempt, directive=None):
    max_repairs = int(os.environ.get("ORCH_AGENTIC_IN_SESSION_REPAIRS", "3") or 3)
    used = int(t.get("_agentic_repair_used") or 0)
    if used >= max_repairs:
        return False
    t["_agentic_repair_used"] = used + 1
    t["prompt"] = agentic_repair.in_session_prompt(t, failure, category=category, directive=directive)
    set_state(t["id"], state="RUNNING",
              note=f"agentic-repair:{category} in-session {used + 1}/{max_repairs}; fixing before completion")
    return True


def run_task(t):
    with _sem:
        try:
            import task_slicer
            if task_slicer.pre_agent_hook(t):
                print(f"[slice] {t.get('slug')}: split before agentic spend", flush=True)
                return
        except Exception as e:
            _log.debug("hook task_slicer failed: %s", e)
        proj = projects(t["project_id"]).get(t["project_id"], {})
        repo = proj.get("repo_path", os.getcwd())
        name = proj.get("name", "repo")
        # data-locality guard: if this Mac doesn't hold the repo (race/removed after claim),
        # re-queue rather than fail so another Mac that has it takes it.
        if repo and repo != os.getcwd() and not os.path.isdir(repo):
            set_state(t["id"], state="QUEUED", note=f"repo not on this host ({socket.gethostname()}): {repo}")
            time.sleep(2); return
        # Fall back to the project's REAL default branch (master vs main), not a hardcoded
        # "main" — otherwise diff/rebase against a nonexistent branch returns empty.
        task_base = _normalize_task_base(repo, proj, t.get("base_branch") or proj.get("default_base") or "main")
        base = _integration_base(repo, proj, task_base)
        slug = t["slug"]
        kind = t.get("kind", "build")
        test_cmd = proj.get("test_cmd") or os.environ.get("TEST_CMD", "npm test")
        _plan = None
        _domain_post = None
        _cost_val = 0

        # kill switch: stop all spend on this project (or globally) at a click
        if kill_switch.is_paused(name):
            set_state(t["id"], state="QUEUED", note="paused by kill switch")
            time.sleep(5); return

        # MAX REQUEUE GUARD: tasks bounced >N times by pre-hooks are forced through.
        # The 72% silent-failure rate was caused by topology/conflict/ensemble hooks
        # endlessly re-queuing tasks. Cap it and force execution.
        _requeue_count = int(t.get("_requeue_count") or 0)
        _max_requeues = int(os.environ.get("ORCH_MAX_REQUEUE", "3"))
        _force_execute = _requeue_count >= _max_requeues
        if _force_execute:
            set_state(t["id"], note=f"requeue-guard: forced execution after {_requeue_count} requeues")

        # toolchain gate: refuse to spend a model run on a project whose build toolchain is
        # known broken (missing npm/tsc, or node_modules never installed) — hold the task
        # QUEUED instead of burning a full agent run that would fail at build_gate anyway.
        # Cache-only check (no subprocess here); toolchain_gate's own periodic job does the
        # actual probing every 30 min and queues a single toolchain-repair task.
        try:
            import toolchain_gate
            if not toolchain_gate.is_ready_cached(t["project_id"]):
                set_state(t["id"], state="QUEUED", note="held: project toolchain not ready (see toolchain-repair task)")
                time.sleep(2); return
        except Exception as e:
            _log.debug("hook toolchain_gate failed: %s", e)  # never block claiming on a broken check

        # budget guardrail: telemetry by default; hard-stops only when explicitly enabled
        if not budget.allow(name):
            set_state(t["id"], state="BLOCKED", note="budget cap reached")
            return

        # waste guardrail: spend with nothing shipped (the $400 pattern) -> pause this
        # project + file an approval, immediately, before burning more tokens.
        waste_reason = waste.check(name)
        if waste_reason:
            if os.environ.get("ORCH_WASTE_GUARD_PAUSES", "false").lower() in ("true", "1", "yes"):
                kill_switch.pause(scope="project", project=name, reason=waste_reason, by="waste")
                set_state(t["id"], state="QUEUED", note="waste guard cooldown: " + waste_reason)
                return
            try:
                db.insert("resource_events", {"kind": "waste_guard", "detail": waste_reason,
                                              "action": "observed_continue", "created_at": "now()"})
            except Exception as e:
                _log.debug("hook waste_guard_event failed: %s", e)

        task_body = pipeline_contract.original_request(t["prompt"])

        # FINAL ADMISSION BARRIER: queue preflight normally persists the shared
        # vendor/model/capability route before a task is claimed.  Auto-slicing can,
        # however, create a leaf and have a free native lane claim it before the next
        # preflight tick.  Re-run the same admission contract here so native execution
        # and direct Cowork claiming cannot diverge, and so no agent starts with an
        # unset executor route.  Existing repair/canary overrides are preserved.
        try:
            _admission = pipeline_contract.task_fields(
                task_body,
                project=name,
                kind=kind,
                source="native-claim",
                slug=slug,
                material=bool(t.get("material")),
                existing_note=t.get("note") or "",
                model=t.get("model") or None,
                force_coder=t.get("force_coder") or None,
            )
            _admission_patch = {
                key: _admission.get(key)
                for key in ("prompt", "note", "model", "force_coder")
                if _admission.get(key) is not None
            }
            db.update("tasks", {"id": t["id"]}, _admission_patch)
            t.update(_admission_patch)
            task_body = pipeline_contract.original_request(t["prompt"])
        except Exception as e:
            # Fail soft for control-plane availability, as the runner's executor
            # picker still validates backend readiness immediately before launch.
            _log.warning("native admission refresh failed for %s: %s", slug, e)

        # result cache: identical (repo+prompt+commit) work is reused, not re-run
        sig = result_cache.signature(name, task_body, repo, base) if USE_CACHE else None
        if sig:
            hit = result_cache.lookup(sig)
            if hit:
                set_state(t["id"], state="DONE", note=f"cache hit: reused {hit.get('branch')}")
                record(t, name, slug, kind, "cache", POOL.current(), 0, True, False, "", time.time())
                return

        # Single composition point (prompt_assembler.py) for every layer that used to be
        # hand-concatenated here: distilled template, cached prefix, distilled project brief,
        # focus/blast/reuse notes, pipeline_contract wrap, knowledge/regression injection,
        # reuse-first tail, final char cap. See prompt_assembler.py for the layer order and why.
        assembled = prompt_assembler.assemble(
            task_body, project=name, repo=repo, kind=kind, source="runner-claim", slug=slug,
            material=bool(t.get("material")), task=t, use_retrieval=USE_RETRIEVAL,
        )
        prompt = assembled["prompt"]
        # WARM POOL: prepend pre-loaded CLAUDE.md context prefix (avoids cold-start rediscovery)
        try:
            if warm_pool:
                _warm_ctx = warm_pool.acquire(repo)
                if _warm_ctx:
                    prompt = _warm_ctx + prompt
        except Exception as _wp_err:
            _log.debug("hook warm_pool.acquire failed: %s", _wp_err)
        try:
            _brain_plan = brain_compiler.compile_for_task(t, repo=repo, project=name)
            if _brain_plan.get("has_plan"):
                prompt = brain_compiler.inject_plan(prompt, _brain_plan)
                prompt = _cap_agent_prompt(prompt)
                set_state(t["id"], note=f"brain-compiler: {len(_brain_plan.get('patches', []))} repo-specific patch steps")
        except Exception as e:
            _log.debug("hook brain_compiler failed: %s", e)
        t0 = time.time()
        # EXECUTION TELEMETRY: instrument the entire pre-hook chain
        try:
            import exec_telemetry
            _tel = exec_telemetry.start(t["id"], slug)
        except Exception:
            _tel = None

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
            _spec_acct = POOL.current(); POOL.record_use(_spec_acct)
            env = dict(os.environ); env.update(POOL.env_for(_spec_acct))
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
        # ADAPTIVE RETRY BUDGET: use historical success data to set max retries
        _max_attempts = 4
        try:
            import retry_budget
            _max_attempts = retry_budget.max_attempts(t)
            if _max_attempts != 4:
                set_state(t["id"], note=f"retry-budget: max_attempts={_max_attempts}")
        except Exception as e:
            _log.debug("hook retry_budget failed: %s", e)
        while attempt < _max_attempts:
            attempt += 1
            # COST-FIRST model routing: cheapest model that can do the job, escalate one tier
            # per failed attempt. Opus is used ONLY for genuinely heavy work or after retries —
            # an intake "opus"/"sonnet" tag is treated as advisory, NOT a license to burn Opus.
            # An explicit "haiku" hint is honored (lets authors force the cheap tier).
            routed = model_router.route(t["prompt"], attempt)
            # OUTCOME-WEIGHTED ROUTING: override with cheapest historically-successful model
            try:
                import outcome_router
                _or = outcome_router.recommend(t, attempt)
                if _or and _or.get("confidence", 0) > 0.7:
                    routed["model"] = _or["model"]
                    routed["reason"] = f"outcome-router: {_or['reason']}"
                    set_state(t["id"], note=f"outcome-router: {_or['model']} (conf={_or['confidence']:.0%})")
            except Exception as e:
                _log.debug("hook outcome_router failed: %s", e)
            hint = (t.get("model") or "").lower()
            # YIELD-FIRST routing (optimize cost-per-MERGE, not per-call): Haiku empirically merges ~0%
            # of feature/bugfix work, so a Haiku draft is pure spend with zero return. Draft REAL coding
            # on Sonnet+ and honor an explicit haiku hint only for genuinely mechanical edits.
            kind_l = (t.get("kind") or "").lower()
            mechanical = kind_l in ("mechanical", "chore", "docs", "cleanup", "test")
            if hint in ("haiku", model_router.HAIKU) and attempt == 1 and mechanical:
                model = model_router.HAIKU
            else:
                model = routed["model"]
            if model == model_router.HAIKU and not mechanical:
                model = model_router.SONNET   # never draft real code on Haiku
            # cost SLO: cost_slo.py raises projects.cost_bias when an app is over its $/merge target.
            # BUT forcing Haiku on real coding was a doom loop (Haiku merges nothing -> $/merge worsens
            # -> more Haiku). So the bias may only drop Opus->Sonnet; it can push down to Haiku ONLY for
            # mechanical tasks, never for real coding.
            bias = int(proj.get("cost_bias") or 0)
            if bias >= 2 and mechanical:
                model = model_router.HAIKU
            elif bias >= 1 and model == model_router.OPUS:
                model = model_router.SONNET
            coder = "claude" if t.get("_force_claude") else agentic_coders.pick(t, slot_index=attempt - 1)
            try:
                _coder_route = agentic_coders.route({**t, "force_coder": coder})
                visible_model = model if coder == "claude" else f"{coder}:{_coder_route.get('model') or model}"
            except Exception:
                visible_model = model if coder == "claude" else f"{coder}:{model}"
            acct = POOL.current()
            POOL.record_use(acct)
            set_state(t["id"], state="RUNNING", model=visible_model, attempt=attempt,
                      account=(acct or {}).get("name"), note=f"agentic coder: {coder}")
            # GIT ISOLATION: prevent concurrent agents from touching the main working tree.
            # When ORCH_GIT_ISOLATION=worktree_only, all agent work happens in worktrees
            # and the main repo's .git/index.lock is never contested. This eliminates
            # the 622 permission errors from fleet agents competing for the same repo.
            if os.environ.get("ORCH_GIT_ISOLATION", "").lower() == "worktree_only":
                _lockfile = os.path.join(repo, ".git", "index.lock")
                if os.path.exists(_lockfile):
                    try:
                        _lock_age = time.time() - os.path.getmtime(_lockfile)
                        if _lock_age > 30:  # stale lock older than 30s
                            os.remove(_lockfile)
                            set_state(t["id"], note=f"git-isolation: removed stale index.lock ({_lock_age:.0f}s old)")
                    except (OSError, PermissionError):
                        pass
            subprocess.run([os.path.join(os.path.dirname(__file__), "setup-worktrees.sh"), slug, base],
                           cwd=repo, capture_output=True)
            wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", slug)
            env = dict(os.environ); env.update(POOL.env_for(acct))
            # inject this project's external-provider secrets (values never logged)
            try:
                env.update(secrets_manager.inject_env(name))
            except Exception as e:
                _log.debug("hook secrets_manager failed: %s", e)
            # Agentic file edits go through the coder seam. Claude Code remains the default
            # backend because it enforces the spend circuit; configured second coders can take
            # independent safe tasks and fall back to Claude on failure.
            # MULTI-MODEL PLAN: a cheaper NON-Claude strategy model plans before the coder drafts.
            # Makes model optimization visible (recorded as task_class='plan' in telemetry) and cuts
            # Claude token burn (Claude drafts against a plan instead of strategizing from scratch).
            draft_prompt = prompt
            _plan_text, _plan_model = None, None
            try:
                if plan_stage.should_plan(t, prompt):
                    _plan_text, _plan_model = plan_stage.make_plan(t, prompt, name)
                if _plan_text:
                    draft_prompt = plan_stage.inject(prompt, _plan_text, _plan_model)
                    draft_prompt = _cap_agent_prompt(draft_prompt)
                    set_state(t["id"], note=f"strategy: {_plan_model} -> draft: {coder}")
            except Exception as e:
                _log.debug("hook plan_stage failed: %s", e)
                draft_prompt = prompt  # fail-soft: never block drafting on the plan step
            try:
                import adaptive_probe
                draft_prompt = adaptive_probe.inject(t, draft_prompt, project=name)
                draft_prompt = _cap_agent_prompt(draft_prompt)
            except Exception as e:
                _log.debug("hook adaptive_probe failed: %s", e)
            # MERGED-DIFF COMPILER: retrieve prior merged diffs and generate a patch plan.
            # This converts "invent from scratch" into "adapt a proven template" — 100X-500X cheaper.
            try:
                _plan = diff_compiler.compile_plan(task_body, project=name, repo=repo, base=base)
                if _plan and _plan.get("has_plan"):
                    draft_prompt = diff_compiler.inject_plan(draft_prompt, _plan)
                    set_state(t["id"], note=f"diff-compiler: {len(_plan.get('templates',[]))} templates (conf={_plan.get('confidence',0):.0%})")
            except Exception as e:
                _log.debug("hook diff_compiler failed: %s", e)
            try:
                _mesh = mesh_optimizer.prepare_prompt(
                    t, draft_prompt, project=name, repo=repo, base=base,
                    coder=coder, visible_model=visible_model,
                    diff_plan=_plan,
                    assignment={"task_class": kind, "implementer": {"confidence": 0.65}},
                )
                draft_prompt = _mesh.get("prompt") or draft_prompt
                t["_mesh_domain"] = _mesh.get("domain")
                if _mesh.get("note"):
                    set_state(t["id"], note=f"mesh-optimizer: {_mesh['note']}")
            except Exception as e:
                _log.debug("hook mesh_optimizer failed: %s", e)
            # QUEUE PRE-OPTIMIZATION: check if background daemon already pre-computed
            # expensive hooks for this task while it was idle in the queue.
            _preopt_notes = []
            _extras = ""
            try:
                import queue_preopt
                _preopt = queue_preopt.get(t["id"])
                if _preopt and _preopt.get("stages"):
                    draft_prompt, _extras, _preopt_notes = queue_preopt.apply_cached(
                        t["id"], draft_prompt, t, repo, name, attempt)
                    if _preopt_notes:
                        set_state(t["id"], note=f"preopt: {', '.join(_preopt_notes)}")
            except Exception as e:
                _log.debug("hook queue_preopt failed: %s", e)
            # CONTEXT + PRECEDENT: give the headless agent what an interactive session has — a repo map +
            # this project's conventions, and the most-similar change that already MERGED (adapt a proven
            # pattern instead of inventing). Both are pure retrieval (no tokens) and lift first-pass yield.
            # Skip if pre-optimization already supplied these.
            if "preopt:context_pack" not in _preopt_notes:
                try:
                    import context_pack, precedent
                    _extras += context_pack.block(repo)
                    _extras += precedent.hint(t, repo, project_id=t.get("project_id"))
                except Exception:
                    pass
            # TASK MEMORY + HIVEMIND: inject fleet intelligence and dependency context
            try:
                import task_memory
                _hive = task_memory.hivemind_query(t, name)
                if _hive and _hive.get("insights"):
                    draft_prompt = task_memory.inject_hivemind(draft_prompt, _hive)
                    set_state(t["id"], note=f"hivemind: {len(_hive['insights'])} insights (conf={_hive.get('confidence', 0):.0%})")
                _dep_ctx = task_memory.get_dependency_context(t)
                if _dep_ctx:
                    _extras += f"\n\n## Parent Task Context\n{_dep_ctx}\n"
            except Exception as e:
                _log.debug("hook task_memory failed: %s", e)
            # MERGE VALIDATOR: check if speculative draft already passed tests
            try:
                import merge_validator
                if merge_validator.fast_track_check(t["id"]):
                    set_state(t["id"], note="merge-validator: pre-validated draft passed tests, fast-tracking")
                    # Draft already validated — inject constraint to use it as-is
                    _extras += "\n\n## Pre-Validated Draft Available\nA speculative draft has already passed all tests. Apply it directly unless you find issues.\n"
            except Exception as e:
                _log.debug("hook merge_validator failed: %s", e)
            # PROMPT COMPRESSOR: deduplicate and compress before final assembly
            try:
                import prompt_compressor
                _compressed = prompt_compressor.compress(draft_prompt, _extras)
                if _compressed.get("savings", {}).get("reduction_pct", 0) > 5:
                    draft_prompt = _compressed["prompt"]
                    _extras = _compressed["extras"]
                    set_state(t["id"], note=f"prompt-compressor: {_compressed['savings']['reduction_pct']:.0f}% reduction")
            except Exception as e:
                _log.debug("hook prompt_compressor failed: %s", e)
            # PROMPT EVOLUTION: inject learned effective additions
            try:
                import prompt_evolution
                _evolved = prompt_evolution.get_evolved_additions(t, name)
                if _evolved:
                    _extras += _evolved
            except Exception as e:
                _log.debug("hook prompt_evolution failed: %s", e)
            # BUILD-TO-GREEN MANDATE: make the agent iterate to a mergeable state ITSELF (edit -> build ->
            # fix -> re-build -> commit), the way an interactive VSCode session does — so it returns green,
            # mergeable work instead of a draft a downstream committee rejects and recycles. The build is
            # the hard gate, so returning a red build just wastes the whole (paid) run. Appended AFTER the
            # length cap so the mandate + context are never truncated. Toggle with ORCH_BUILD_MANDATE=false.
            # SMART COMPRESSION: when diff_compiler found templates, use intelligent compression
            # instead of naive head/tail truncation (50X-200X token savings).
            try:
                draft_prompt = smart_compress.compress(
                    draft_prompt, diff_plan=_plan,
                    task_contract=task_body, templates=(_plan or {}).get("templates"))
            except Exception:
                draft_prompt = _cap_agent_prompt(draft_prompt)
            draft_prompt = draft_prompt + _extras
            if os.environ.get("ORCH_BUILD_MANDATE", "true").lower() in ("true", "1", "yes"):
                draft_prompt = draft_prompt + BUILD_MANDATE
            # ZERO-SPEND RECOVERY: if agent/<slug> already contains committed work, verify/integrate
            # that branch instead of spending another model call. Ensure the branch has a worktree,
            # because downstream verify/build steps operate on filesystem paths.
            _integrating_existing = False
            branch_ref = f"agent/{slug}"
            if not _must_run_agent_for_evidence(t, slug):
                try:
                    _av = subprocess.run(["git", "rev-list", "--count", f"{base}..{branch_ref}"],
                                         cwd=repo, capture_output=True, text=True, timeout=60)
                    if int((_av.stdout or "0").strip() or "0") > 0:
                        if not os.path.isdir(wt):
                            try:
                                import approval_merge
                                approval_merge._free_branch(repo, branch_ref)
                            except Exception as e:
                                _log.debug("hook free_branch failed: %s", e)
                            os.makedirs(os.path.dirname(wt), exist_ok=True)
                            subprocess.run(["git", "worktree", "add", "-f", wt, branch_ref],
                                           cwd=repo, capture_output=True, timeout=180)
                            # Lock while in use — concurrent GC/prune must not delete it mid-task.
                            subprocess.run(["git", "worktree", "lock", wt, "--reason", f"task {slug} in use"],
                                           cwd=repo, capture_output=True, timeout=30)
                        _integrating_existing = os.path.isdir(wt)
                except Exception:
                    _integrating_existing = False
            # ZERO-TOKEN FIRST PATCH: try applying known-good diff before any model call
            try:
                _zt = cade_tournaments.zero_token_patch(t, wt if os.path.isdir(wt) else repo)
                if _zt and _zt.get("applied"):
                    set_state(t["id"], note=f"zero-token patch applied ({_zt['method']})")
                    # Skip agent entirely — go straight to integration
                    r = {"text": "zero-token replay — diff applied without model call",
                         "returncode": 0, "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
                         "coder": "zero-token"}
                    integrated = True
                    record(t, name, slug, kind, visible_model, acct, attempt, True, True, r.get("text", ""), t0, cost={"usd": 0})
                    return
            except Exception as e:
                _log.debug("hook zero_token_patch failed: %s", e)
            # INTENT COMPILER: check if task matches a compiled deterministic script
            try:
                _compiled = intent_compiler.get_compiled(t, wt if os.path.isdir(wt) else repo)
                if _compiled:
                    _comp_result = intent_compiler.execute(_compiled, wt if os.path.isdir(wt) else repo, t["id"])
                    if _comp_result.get("success"):
                        set_state(t["id"], note=f"compiled-intent: executed deterministic script (0 tokens)")
                        r = {"text": "compiled intent replay — deterministic script, zero model call",
                             "returncode": 0, "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
                             "coder": "compiled-intent"}
                        integrated = True
                        record(t, name, slug, kind, visible_model, acct, attempt, True, True, r["text"], t0, cost={"usd": 0})
                        return
            except Exception as e:
                _log.debug("hook intent_compiler failed: %s", e)
            # PATTERN COMPILER: check if pre-opt found a high-confidence pattern match
            try:
                import pattern_compiler
                _pm = None
                # Check preopt cache first (already computed while task was idle)
                if _preopt and _preopt.get("pattern_match"):
                    _pm = _preopt["pattern_match"]
                else:
                    _pm = pattern_compiler.match(t)
                if _pm and _pm.get("confidence", 0) > 0.7:
                    _pc_result = pattern_compiler.execute(_pm, wt if os.path.isdir(wt) else repo, t["id"])
                    if _pc_result and _pc_result.get("success"):
                        set_state(t["id"], note=f"pattern-compiler: deterministic replay (conf={_pm['confidence']:.0%}, pattern={_pm.get('pattern_id', '?')})")
                        r = {"text": f"pattern-compiler replay — {_pc_result.get('files_changed', 0)} files, zero model call",
                             "returncode": 0, "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
                             "coder": "pattern-compiler"}
                        integrated = True
                        record(t, name, slug, kind, visible_model, acct, attempt, True, True, r["text"], t0, cost={"usd": 0})
                        return
            except Exception as e:
                _log.debug("hook pattern_compiler failed: %s", e)
            # FLEET TOPOLOGY: check if this runner can handle the task's complexity
            try:
                import fleet_topology
                if not _force_execute and not fleet_topology.can_handle(t):
                    _better = fleet_topology.best_runner_for(t)
                    if _better:
                        t["_requeue_count"] = _requeue_count + 1
                        set_state(t["id"], state="QUEUED",
                                  note=f"fleet-topology: redirecting to {_better} (better fit) [requeue {_requeue_count+1}/{_max_requeues}]")
                        time.sleep(5); return
            except Exception as e:
                _log.debug("hook fleet_topology failed: %s", e)
            # CONFLICT PREDICTOR: check for file-scope overlap with active tasks
            try:
                import conflict_predictor
                _conflicts = conflict_predictor.check_conflicts(t)
                if not _force_execute and _conflicts.get("action") == "defer":
                    t["_requeue_count"] = _requeue_count + 1
                    set_state(t["id"], state="QUEUED",
                              note=f"conflict-predictor: deferring ({_conflicts['reason']}) [requeue {_requeue_count+1}/{_max_requeues}]")
                    time.sleep(10); return
                elif _conflicts.get("conflicts"):
                    set_state(t["id"], note=f"conflict-predictor: {len(_conflicts['conflicts'])} overlapping files, proceeding")
            except Exception as e:
                _log.debug("hook conflict_predictor failed: %s", e)
            # FAST-PATH: graduated autonomy fast-path (L3/L4 skip hooks)
            _fast = {}
            try:
                _fp_domain = model_portfolios.classify(t, (_plan or {}).get("files", [])) if _plan is not None else "backend"
                _fp_agent = f"{coder}:{visible_model}" if coder != "claude" else f"claude:{visible_model}"
                _fast = fast_path.check(t, _fp_agent, _fp_domain)
                if _fast.get("skip_all"):
                    set_state(t["id"], note=f"fast-path L4: skipping all pre-hooks")
            except Exception as e:
                _log.debug("hook fast_path failed: %s", e)
            # ENSEMBLE PREDICTOR: combined failure prediction from all signals
            if not _fast.get("skip_pre_hooks"):
                try:
                    _ens_agent = f"{coder}:{visible_model}" if coder != "claude" else f"claude:{visible_model}"
                    _ens_domain = model_portfolios.classify(t, (_plan or {}).get("files", [])) if _plan is not None else "backend"
                    _ensemble = ensemble_predictor.predict(t, _ens_agent, _ens_domain, visible_model,
                                                           diff_plan=_plan)
                    if not _force_execute and _ensemble.get("should_skip"):
                        t["_requeue_count"] = _requeue_count + 1
                        set_state(t["id"], state="QUEUED",
                                  note=f"ensemble-predictor: {_ensemble['recommended_action']} (conf={_ensemble['confidence']:.0%}, {_ensemble['signal_count']} signals) [requeue {_requeue_count+1}/{_max_requeues}]")
                        time.sleep(5); return
                except Exception as e:
                    _log.debug("hook ensemble_predictor failed: %s", e)
            # UNIFIED KNOWLEDGE: single query across all knowledge stores
            _uk = {}
            if not _fast.get("skip_all"):
                try:
                    _uk = unified_knowledge.query(t, name, wt if os.path.isdir(wt) else repo, attempt)
                    if _uk.get("matches"):
                        draft_prompt = unified_knowledge._apply_match(draft_prompt, _uk["matches"][0])
                        set_state(t["id"], note=f"unified-knowledge: {len(_uk['matches'])} matches, best={_uk['matches'][0].get('source', '?')} (conf={_uk['matches'][0].get('confidence', 0):.0%})")
                except Exception as e:
                    _log.debug("hook unified_knowledge failed: %s", e)
            # ADAPTIVE PIPELINE: collapse stages when cached results found
            if not _fast.get("skip_all"):
                try:
                    _ap = adaptive_pipeline.plan(t, name, wt if os.path.isdir(wt) else repo)
                    if _ap.get("collapsed"):
                        draft_prompt = _ap.get("enriched_prompt", draft_prompt)
                        set_state(t["id"], note=f"adaptive-pipeline: collapsed {len(_ap['collapsed'])} stages, saving ~{_ap.get('estimated_savings_tokens', 0)} tokens")
                except Exception as e:
                    _log.debug("hook adaptive_pipeline failed: %s", e)
            # PRE-HOOK TIMING GUARD: if pre-hooks already consumed >60s, skip the
            # remaining parallelized hooks and go straight to execution. This prevents
            # the "death by a thousand hooks" pattern where 40+ hooks each take 2-3s.
            _prehook_elapsed = time.time() - t0
            _prehook_max = float(os.environ.get("ORCH_PREHOOK_MAX_S", "60"))
            if _prehook_elapsed > _prehook_max:
                _fast["skip_all"] = True
                set_state(t["id"], note=f"prehook-timing: {_prehook_elapsed:.0f}s > {_prehook_max:.0f}s cap — skipping remaining hooks")
            # ── REMAINING PRE-HOOKS (parallelized, all skipped when fast-path L4 skip_all) ──
            _pipeline_cost = 0
            if not _fast.get("skip_all"):
                from concurrent.futures import ThreadPoolExecutor, as_completed
                _uk_has_matches = bool(_uk and _uk.get("matches"))

                # ── TIER 0: read-only hooks (parallel, no prompt mutation) ──────────
                def _hook_cade():
                    try:
                        if cade_tournaments.should_avoid(visible_model, t):
                            _fp_summary = cade_tournaments.get_failure_summary(visible_model)
                            set_state(t["id"], note=f"cade: avoiding {visible_model} ({_fp_summary.get('recent_failures', 0)} recent failures)")
                    except Exception as e:
                        _log.debug("hook cade_fingerprints failed: %s", e)

                def _hook_slashing():
                    try:
                        _slash_agent = f"{coder}:{visible_model}" if coder != "claude" else f"claude:{visible_model}"
                        _slash_penalty = model_slashing.penalty_for(_slash_agent)
                        if _slash_penalty > 2.0:
                            set_state(t["id"], note=f"model-slashing: {_slash_agent} penalty={_slash_penalty:.2f}")
                    except Exception as e:
                        _log.debug("hook model_slashing failed: %s", e)

                def _hook_budget():
                    try:
                        _domain_budget = model_portfolios.classify(t, (_plan or {}).get("files", [])) if _plan is not None else "backend"
                        _budget = adaptive_budget.predict_budget(t, _domain_budget, diff_plan=_plan)
                        if _budget.get("confidence", 0) > 0.3:
                            set_state(t["id"], note=f"adaptive-budget: {_budget['max_tokens']} tokens ({_budget['source']}, saves {_budget.get('savings_pct', 0):.0f}%)")
                    except Exception as e:
                        _log.debug("hook adaptive_budget failed: %s", e)

                # ── TIER 1: enrichment hooks (query phase parallel, apply serial) ──
                def _query_recycling():
                    try:
                        if not _uk_has_matches:
                            _recycled = output_recycling.get_recycled(t["id"])
                            if _recycled:
                                return {"hook": "output_recycling", "data": _recycled}
                    except Exception as e:
                        _log.debug("hook output_recycling failed: %s", e)
                    return None

                def _query_transfer():
                    try:
                        if not _uk_has_matches:
                            _transfer = transfer_learning.find_transfer(t, current_project=name)
                            if _transfer:
                                return {"hook": "transfer_learning", "data": _transfer}
                    except Exception as e:
                        _log.debug("hook transfer_learning failed: %s", e)
                    return None

                def _query_distillation():
                    try:
                        if not _uk_has_matches:
                            _distilled = prompt_distillation.find_distilled(t, current_project=name)
                            if _distilled:
                                return {"hook": "prompt_distillation", "data": _distilled}
                    except Exception as e:
                        _log.debug("hook prompt_distillation failed: %s", e)
                    return None

                def _query_debate():
                    try:
                        if os.environ.get("ORCH_COLOSSEUM_DEBATE", "").lower() in ("true", "1", "yes"):
                            _debate_result = debate_compress.compressed_debate(t, project=name)
                            if _debate_result:
                                return {"hook": "debate_compress", "data": _debate_result}
                    except Exception as e:
                        _log.debug("hook debate_compress failed: %s", e)
                    return None

                def _query_cross_templates():
                    try:
                        if not _uk_has_matches:
                            _xp_templates = cross_project_templates.find_templates(t, current_project=name)
                            if _xp_templates:
                                return {"hook": "cross_project_templates", "data": _xp_templates}
                    except Exception as e:
                        _log.debug("hook cross_project_templates failed: %s", e)
                    return None

                def _query_session_cache():
                    try:
                        if not _uk_has_matches:
                            # session_cache.warm_start needs draft_prompt — run serially below
                            return {"hook": "session_cache", "data": True}
                    except Exception as e:
                        _log.debug("hook session_cache failed: %s", e)
                    return None

                # Run Tier 0 + Tier 1 queries concurrently
                _hook_workers = int(os.environ.get("ORCH_HOOK_WORKERS", "6"))
                _enrichments = []
                with ThreadPoolExecutor(max_workers=_hook_workers) as _pool:
                    _futures = {
                        # Tier 0 (fire-and-forget, no return value needed)
                        _pool.submit(_hook_cade): "cade",
                        _pool.submit(_hook_slashing): "slashing",
                        _pool.submit(_hook_budget): "budget",
                        # Tier 1 (collect results for serial apply)
                        _pool.submit(_query_recycling): "recycling",
                        _pool.submit(_query_transfer): "transfer",
                        _pool.submit(_query_distillation): "distillation",
                        _pool.submit(_query_debate): "debate",
                        _pool.submit(_query_cross_templates): "cross_templates",
                        _pool.submit(_query_session_cache): "session_cache",
                    }
                    for fut in as_completed(_futures):
                        try:
                            result = fut.result()
                            if result and isinstance(result, dict) and result.get("hook"):
                                _enrichments.append(result)
                        except Exception as e:
                            _log.debug("hook %s future failed: %s", _futures[fut], e)

                # ── Apply Tier 1 enrichment results serially (prompt mutation) ──────
                for _enr in _enrichments:
                    _hook_name = _enr["hook"]
                    _hook_data = _enr["data"]
                    try:
                        if _hook_name == "output_recycling":
                            draft_prompt = output_recycling.inject_recycled(draft_prompt, _hook_data)
                            set_state(t["id"], note="output-recycling: injecting partial work from prior attempt")
                        elif _hook_name == "transfer_learning":
                            draft_prompt = transfer_learning.inject_transfer(draft_prompt, _hook_data)
                            set_state(t["id"], note=f"transfer-learning: pattern from {_hook_data['source_project']} (conf={_hook_data['confidence']:.0%})")
                        elif _hook_name == "prompt_distillation":
                            draft_prompt = prompt_distillation.apply_distilled(draft_prompt, _hook_data)
                            set_state(t["id"], note=f"distilled: {_hook_data.get('merge_count', 0)} merges, {_hook_data.get('compression_ratio', 1):.0%} compression")
                        elif _hook_name == "debate_compress":
                            draft_prompt = debate_compress.inject_debate(draft_prompt, _hook_data)
                        elif _hook_name == "cross_project_templates":
                            draft_prompt = cross_project_templates.inject_cross_templates(draft_prompt, _hook_data)
                            set_state(t["id"], note=f"cross-templates: {len(_hook_data)} matches from {_hook_data[0].get('source_project','?')}")
                        elif _hook_name == "session_cache":
                            draft_prompt = session_cache.warm_start(t, attempt, draft_prompt)
                    except Exception as e:
                        _log.debug("hook %s apply failed: %s", _hook_name, e)

                # ── TIER 2: final hooks (serial, order-dependent) ──────────────────
                # PROMPT BANKRUPTCY: restructure AFTER all enrichment (operates on final prompt)
                try:
                    if prompt_bankruptcy.is_bankrupt(t):
                        draft_prompt = prompt_bankruptcy.restructure(t, draft_prompt, project=name)
                        set_state(t["id"], note="prompt-bankruptcy: restructured after repeated failures")
                except Exception as e:
                    _log.debug("hook prompt_bankruptcy failed: %s", e)
                # MULTI-AGENT PIPELINE: run scout+planner for complex tasks
                try:
                    _pipe_check = multi_agent_pipeline.should_pipeline(t, diff_plan=_plan)
                    if _pipe_check.get("pipeline") and _pipe_check["stages"] >= 2:
                        _scout = multi_agent_pipeline.run_scout(t, name, repo)
                        _planner_result = None
                        if _scout and _pipe_check["stages"] >= 3:
                            _planner_result = multi_agent_pipeline.run_planner(t, name, _scout)
                        draft_prompt = multi_agent_pipeline.build_enriched_prompt(t, _scout, _planner_result)
                        _pipeline_cost = multi_agent_pipeline.pipeline_cost(_scout, _planner_result)
                        set_state(t["id"], note=f"pipeline: {_pipe_check['stages']}-stage ({_pipe_check['reason']})")
                except Exception as e:
                    _log.debug("hook multi_agent_pipeline failed: %s", e)
                # LIVE BIDDING: auction among models for best approach (Phase 2 colosseum)
                try:
                    if os.environ.get("ORCH_LIVE_BIDDING", "").lower() in ("true", "1", "yes"):
                        _auction = live_bidding.auction(t, project=name)
                        if _auction and _auction.get("winner"):
                            draft_prompt = live_bidding.inject_auction_context(draft_prompt, _auction)
                except Exception as e:
                    _log.debug("hook live_bidding failed: %s", e)
            # ── WAVE PIPELINE: pre-execution hooks ──────────────────────────
            _wave_t0 = time.time()
            try:
                import wave_pipeline
                # 1. Predictive pre-fetch: warm file cache for files mentioned in prompt
                _prefetched = wave_pipeline.prefetch_files(draft_prompt, repo)
                if _prefetched:
                    _log.debug("wave: pre-fetched %d files for %s", len(_prefetched), slug)
                # 2. Cross-task learning: check if a better provider:model is known
                _best_path = wave_pipeline.best_path_for(t)
                if _best_path and ":" in _best_path:
                    _bp_provider, _bp_model = _best_path.split(":", 1)
                    _log.info("wave: cross-task learning suggests %s for %s", _best_path, slug)
                    # Inject as hint — tier_router will pick this up
                    t["_wave_provider_hint"] = _bp_provider
                    t["_wave_model_hint"] = _bp_model
            except Exception as _wave_err:
                _log.debug("wave pre-exec hooks: %s", _wave_err)

            # Record pre-hook telemetry before execution starts
            if _tel:
                try:
                    _tel.finish(outcome="executing", note=_tel.summary())
                    set_state(t["id"], note=f"telemetry: {_tel.summary()}")
                except Exception:
                    pass

            try:
                if _integrating_existing:
                    print(f"[integrate-existing] {slug}: branch ahead of {base} -> skip agent, integrate directly", flush=True)
                    r = {"text": "existing committed branch — integrating without re-running the agent",
                         "returncode": 0, "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
                         "coder": coder}
                else:
                    # --- SWARM TIER ROUTING: subscription-first, API-overflow ---
                    _use_swarm = False
                    _swarm_decision = None
                    try:
                        if os.environ.get("ORCH_EXEC_MODE", "cli").lower() in ("hybrid", "api", "swarm"):
                            import tier_router
                            _swarm_decision = tier_router.route(t)
                            if _swarm_decision and _swarm_decision.get("tier") in ("api", "speculative"):
                                _use_swarm = True
                    except Exception as _tier_err:
                        _log.debug("tier_router: %s — falling back to default coder", _tier_err)
                    if _use_swarm and _swarm_decision:
                        try:
                            import swarm_executor
                            _swarm_provider = _swarm_decision.get("provider", "claude")
                            _swarm_model = _swarm_decision.get("model", model)
                            _swarm_mode = "diff" if kind in ("mechanical", "chore", "cleanup", "test", "docs") else "agentic"
                            r = swarm_executor.run_swarm(
                                draft_prompt, _swarm_model, provider=_swarm_provider,
                                cwd=wt if os.path.isdir(wt) else repo,
                                timeout=int(os.environ.get("TASK_TIMEOUT", "900")),
                                mode=_swarm_mode,
                            )
                            r["coder"] = f"swarm:{_swarm_provider}"
                            try:
                                tier_router.record_outcome(
                                    slug, _swarm_decision["tier"], _swarm_provider,
                                    r.get("returncode", 1) == 0, r.get("cost_usd", 0),
                                    r.get("latency_s", 0))
                            except Exception:
                                pass
                        except Exception as _sw_err:
                            _log.warning("swarm_executor failed (%s); falling back to agentic_coders", _sw_err)
                            r = agentic_coders.run(coder, draft_prompt, model,
                                                   cwd=wt if os.path.isdir(wt) else repo, env=env,
                                                   project=name, max_turns=60, permission="acceptEdits",
                                                   timeout=int(os.environ.get("TASK_TIMEOUT", "900")))
                    else:
                        # --- DEFAULT PATH: subscription CLI/SDK via agentic_coders ---
                        r = agentic_coders.run(coder, draft_prompt, model,
                                               cwd=wt if os.path.isdir(wt) else repo, env=env,
                                               project=name, max_turns=60, permission="acceptEdits",
                                               timeout=int(os.environ.get("TASK_TIMEOUT", "900")))
                r.setdefault("coder", coder)
            except subprocess.TimeoutExpired:
                if _agentic_repair_continue(
                    t, "timeout", "agentic coder timed out",
                    attempt,
                    "The agentic coder timed out. Reduce scope to the smallest mergeable slice, preserve existing work, run checks, and commit.",
                ):
                    continue
                set_state(t["id"], state="BLOCKED", note="timed out (>15m) — killed to free the slot")
                record(t, name, slug, kind, visible_model, acct, attempt, False, False, "timeout", t0); return
            except claude_cli.CircuitOpen as e:
                # MULTI-VENDOR FAILOVER: route through tier_router instead of just re-queuing.
                # This gives instant failover to Groq/DeepSeek/Gemini instead of stalling.
                try:
                    POOL.mark_exhausted(acct)
                except Exception:
                    pass
                # Try tier_router for cross-vendor failover first
                try:
                    import tier_router
                    _failover = tier_router.route(t)
                    if _failover and _failover.get("provider") != "claude":
                        _fo_coder = _failover.get("coder", "swarm")
                        _fo_model = _failover.get("model", "deepseek-v4-flash")
                        _fo_provider = _failover["provider"]
                        set_state(t["id"], state="RETRY",
                                  note=f"circuit-open → tier_router failover: {_fo_provider}:{_fo_model} ({_failover.get('reason','')})")
                        t["force_coder"] = f"swarm:{_fo_provider}" if _fo_coder == "swarm" else _fo_coder
                        t["_force_model"] = _fo_model
                        attempt -= 1
                        time.sleep(2)
                        continue
                except Exception as _tr_err:
                    _log.debug("tier_router failover failed: %s", _tr_err)
                # Fallback: try agentic_coders pool
                if len(agentic_coders.available()) > 1:
                    failover = _next_non_claude_coder(t, exclude=t.get("_failed_coders") or ())
                    patch = {"state": "RETRY", "note": f"capacity circuit → non-Claude failover ({e})"}
                    if failover:
                        patch["force_coder"] = failover
                        patch["model"] = failover
                        t["force_coder"] = failover
                    attempt -= 1
                    set_state(t["id"], **patch)
                    time.sleep(5)
                    continue
                if os.environ.get("ORCH_PAUSE_ON_COST_CIRCUIT", "false").lower() in ("true", "1", "yes"):
                    kill_switch.pause(scope="global", reason=f"cost circuit open: {e}", by="claude_cli")
                    set_state(t["id"], state="QUEUED", note=f"cost circuit open: {e}; paused by configured policy")
                    time.sleep(10); return
                set_state(t["id"], state="QUEUED", note=f"capacity circuit: {e}; queued for cooldown/failover")
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
            # ── WAVE PIPELINE: post-execution cross-task learning ──────────
            try:
                import wave_pipeline
                _exec_provider = r.get("coder", coder).replace("swarm:", "") if "swarm:" in r.get("coder", "") else "claude"
                _exec_model = r.get("model", model) or model
                wave_pipeline.record_success(
                    t, _exec_provider, _exec_model,
                    success=(rc == 0),
                    latency_s=time.time() - _wave_t0,
                    cost_usd=r.get("cost_usd", 0),
                )
            except Exception as _wl_err:
                _log.debug("wave record_success: %s", _wl_err)
            # bidirectional learning: harvest the agent's feedback about the orchestration
            try:
                feedback.extract_and_store(out, project=name, slug=slug, task_id=t["id"])
            except Exception as e:
                _log.debug("hook feedback failed: %s", e)
            # auto-resolve missing credentials (prompts you only if payment/manual is needed)
            try:
                credential_broker.detect_from_output(out, name)
            except Exception as e:
                _log.debug("hook credential_broker failed: %s", e)

            if any(s in low for s in EXHAUST):
                nxt = POOL.mark_exhausted(acct)
                # CROSS-VENDOR CASCADE: use tier_router for intelligent failover
                try:
                    import tier_router
                    _exhaust_fo = tier_router.route(t)
                    if _exhaust_fo and _exhaust_fo.get("provider") != "claude":
                        _fo_coder = _exhaust_fo.get("coder", "swarm")
                        _fo_provider = _exhaust_fo["provider"]
                        _fo_model = _exhaust_fo.get("model", "deepseek-v4-flash")
                        t["force_coder"] = f"swarm:{_fo_provider}" if _fo_coder == "swarm" else _fo_coder
                        t["_force_model"] = _fo_model
                        set_state(t["id"], state="RETRY",
                                  note=f"exhausted → cross-vendor cascade: {_fo_provider}:{_fo_model}")
                        attempt -= 1
                        continue
                except Exception as _tr_err:
                    _log.debug("tier_router exhaust failover: %s", _tr_err)
                # Fallback: try agentic_coders pool
                try:
                    if account_pool.claude_exhausted():
                        failover = _next_non_claude_coder(t, exclude=t.get("_failed_coders") or ())
                        if failover:
                            set_state(t["id"], state="RETRY", note=f"all Claude exhausted → {failover}",
                                      force_coder=failover, model=failover)
                            attempt -= 1
                            continue
                except Exception as e:
                    _log.debug("hook claude_exhausted_failover failed: %s", e)
                set_state(t["id"], state="RETRY", note=f"account exhausted → {nxt}")
                if nxt and nxt != (acct or {}).get("name"):
                    attempt -= 1
                continue
            if any(s in low for s in RATE):
                # RATE LIMIT FAILOVER: try a different vendor instead of just backing off
                try:
                    import tier_router
                    _rate_fo = tier_router.route(t)
                    if _rate_fo and _rate_fo.get("provider") != "claude":
                        _fo_coder = _rate_fo.get("coder", "swarm")
                        _fo_provider = _rate_fo["provider"]
                        _fo_model = _rate_fo.get("model", "deepseek-v4-flash")
                        t["force_coder"] = f"swarm:{_fo_provider}" if _fo_coder == "swarm" else _fo_coder
                        t["_force_model"] = _fo_model
                        set_state(t["id"], state="RETRY",
                                  note=f"rate-limited → cross-vendor: {_fo_provider}:{_fo_model}")
                        time.sleep(2); continue
                except Exception:
                    pass
                back = min(300, 2 ** attempt * 5)
                set_state(t["id"], state="RETRY", note=f"rate-limited, backoff {back}s")
                time.sleep(min(back, 30)); continue

            tests_ok = rc == 0
            # TEST QUARANTINE: separate flaky failures from real blockers
            if not tests_ok:
                try:
                    if os.environ.get("ORCH_TEST_QUARANTINE", "true").lower() == "true":
                        import test_quarantine, re
                        # Extract failed test names from common runner patterns
                        _failed = []
                        for _pat in [
                            r'FAILED\s+([\w/.:]+)',          # pytest FAILED path::test
                            r'FAIL:\s+(test\w+)',            # unittest FAIL: test_name
                            r'Error in .*(test_\w+)',        # generic test_ pattern
                            r'✗\s+([\w.]+)',                 # checkmark-style runners
                        ]:
                            _failed.extend(re.findall(_pat, out or ""))
                        if _failed:
                            _qr = test_quarantine.quarantine_check(_failed, name)
                            if not _qr["blocking"]:
                                tests_ok = True
                                set_state(t["id"], note=f"test-quarantine: all {len(_qr['quarantined'])} failure(s) quarantined as flaky — unblocking")
                            elif _qr["quarantined"]:
                                set_state(t["id"], note=f"test-quarantine: {len(_qr['quarantined'])} flaky, {len(_qr['blocking'])} blocking")
                except Exception as _tq_err:
                    _log.debug("hook test_quarantine failed: %s", _tq_err)
            if not tests_ok:
                # ERROR TAXONOMY: classify the error and select targeted remediation
                _error_class = "unknown"
                _remediation_prompt_extra = ""
                try:
                    import error_taxonomy
                    _etx = error_taxonomy.classify(out or "", t)
                    _error_class = _etx.get("error_class", "unknown")
                    _remediation_prompt_extra = error_taxonomy.remediation_prompt(_error_class, out or "", t)
                    set_state(t["id"], note=f"error-taxonomy: {_error_class} -> {_etx.get('remediation', 'escalate')}")
                    # Check if retry_budget says this error is worth retrying
                    try:
                        import retry_budget
                        _rb = retry_budget.should_retry(t, attempt, _error_class)
                        if not _rb.get("retry", True):
                            set_state(t["id"], state="BLOCKED",
                                      note=f"retry-budget: skipping retry ({_rb['reason']})")
                            record(t, name, slug, kind, visible_model, acct, attempt, False, False, out, t0, cost=run_cost); return
                    except Exception:
                        pass
                except Exception as e:
                    _log.debug("hook error_taxonomy failed: %s", e)
                # UNIVERSAL IN-AGENT ERROR RESOLUTION: ALL coders (Claude and non-Claude alike)
                # get up to 3 chances to fix their own errors before we rotate or block.
                # This eliminates the constant requeue cycle — agents resolve issues themselves.
                _err_count = t.get("_error_retry_count", 0)
                _max_retries = int(os.environ.get("ORCH_ERROR_RETRY_MAX", "3"))
                if _err_count < _max_retries:
                    t["_error_retry_count"] = _err_count + 1
                    error_tail = (out or "")[-1500:]
                    error_context = (
                        f"\n\n## ATTEMPT {_err_count + 1} FAILED — FIX THE ERROR (retry {_err_count + 1}/{_max_retries})\n"
                        f"Error classified as: {_error_class}\n"
                        f"Your previous attempt to complete this task failed with the following error. "
                        f"Diagnose and fix the root cause — do not just retry the same approach. "
                        f"If a dependency is missing, install it. If a file path is wrong, correct it. "
                        f"If a test fails, fix the code to pass the test. If an import is missing, add it.\n\n"
                        f"{_remediation_prompt_extra}\n"
                        f"ERROR OUTPUT:\n```\n{error_tail}\n```\n"
                    )
                    t["prompt"] = t.get("_original_prompt", t.get("prompt", "")) + error_context
                    if "_original_prompt" not in t:
                        t["_original_prompt"] = t.get("prompt", "")
                    set_state(t["id"], state="RUNNING",
                              note=f"error-retry {_err_count + 1}/{_max_retries}: feeding error back to {coder} for in-session fix (attempt {attempt})")
                    continue
                # All retries exhausted for this coder
                if coder != "claude":
                    failed = set(t.get("_failed_coders") or [])
                    failed.add(coder)
                    t["_failed_coders"] = sorted(failed)
                    t["_error_retry_count"] = 0  # reset for next coder
                    nxt = _next_non_claude_coder(t, exclude=failed)
                    if nxt:
                        t["force_coder"] = nxt
                        set_state(t["id"], state="RETRY", force_coder=nxt, model=nxt,
                                  note=f"{coder} failed after {_max_retries} retries; trying {nxt}")
                        continue
                    t["_force_claude"] = True
                    t["_error_retry_count"] = 0  # reset for Claude
                    set_state(t["id"], state="RETRY",
                              note=f"{coder} failed after {_max_retries} retries; no other non-Claude coder, trying Claude Code")
                    continue
                set_state(t["id"], state="BLOCKED", note=f"agent run failed after {_max_retries} error-retries")
                regression.record(name, slug, kind, t["prompt"][:500], out[-500:], f"agent run failed after {_max_retries} error-retries; re-scope or escalate model")
                record(t, name, slug, kind, visible_model, acct, attempt, False, False, out, t0, cost=run_cost); return

            # COMMIT the agent's edits. Agents edit the worktree (acceptEdits) but don't commit;
            # verify/confidence/integrate all diff `base...HEAD` (commit-based), so without this
            # every diff is empty -> verify trivially "passes", confidence defaults to 0.5, and
            # ff-merge ships nothing. This is what kept integration at 0.
            if not _integrating_existing and not _commit_agent_work(wt, slug, t["prompt"], base):
                # NO-CHANGES RECOVERY: retry with explicit instructions to make file changes.
                # Many agents "investigate" without editing files — this nudges them to act.
                _nochange_count = t.get("_nochange_retry", 0)
                if _nochange_count < 2:
                    t["_nochange_retry"] = _nochange_count + 1
                    # SESSION PROOF: check for stall pattern first
                    try:
                        import session_proof
                        if not t.get("_proof_retry") and session_proof.STALL_RX.search(out or ""):
                            t["_proof_retry"] = True
                            prompt = session_proof.reinjection_prompt(t)
                            set_state(t["id"], state="RUNNING", note="session-proof: stall detected — re-injecting prompt")
                            continue
                    except Exception as e:
                        _log.debug("hook session_proof failed: %s", e)
                    nochange_nudge = (
                        f"\n\n## NO FILE CHANGES DETECTED — YOU MUST EDIT FILES (retry {_nochange_count + 1}/2)\n"
                        f"Your previous attempt produced no committable file changes. "
                        f"You MUST create or modify files to complete this task. "
                        f"Do not just read or analyze — write the actual code/config changes. "
                        f"If the task requires creating a new file, create it. "
                        f"If it requires modifying existing code, edit those files directly.\n"
                    )
                    t["prompt"] = t.get("_original_prompt", t.get("prompt", "")) + nochange_nudge
                    if "_original_prompt" not in t:
                        t["_original_prompt"] = t.get("prompt", "")
                    set_state(t["id"], state="RUNNING",
                              note=f"no-changes retry {_nochange_count + 1}/2: nudging {coder} to make file edits")
                    continue
                if _agentic_repair_continue(
                    t, "noop", out or "agent produced no committable changes after retries",
                    attempt,
                    "The agent still produced no committable changes. Make the smallest concrete implementation now; create or edit files and commit the diff.",
                ):
                    continue
                set_state(t["id"], state="BLOCKED", note="agent produced no committable changes after retries")
                regression.record(name, slug, kind, t["prompt"][:500], "no file changes", "agent investigated but changed nothing; re-scope task")
                record(t, name, slug, kind, visible_model, acct, attempt, True, False, out, t0, cost=run_cost); return
            # SESSION PROOF (positive path): verify the diff is real work echoing the task
            if not _integrating_existing:
                try:
                    import session_proof
                    proof = session_proof.verify_session(t, out, wt if os.path.isdir(wt) else repo, f"agent/{slug}")
                    if not proof.get("ok") and not t.get("_proof_retry"):
                        t["_proof_retry"] = True
                        prompt = session_proof.reinjection_prompt(t)
                        set_state(t["id"], state="RUNNING", note=f"session-proof failed ({'; '.join(proof.get('reasons', [])[:2])}) — retrying once")
                        continue
                except Exception as e:
                    _log.debug("hook session_proof_verify failed: %s", e)

            # blast radius: find dependents of changed files, pass to verifier
            radius = blast_radius.radius_after(wt, base)
            deps = radius.get("dependents", [])

            # SOFT GATES (verify / quality / judge) are ADVISORY for non-material work: the production
            # BUILD is the hard gate (a green build is deployable), so a cheap-model quibble is recorded
            # as a flag rather than a reject-to-recycle. Rejecting on every soft-gate concern — each an
            # independent model that recycles the task — is what compounded yield down to ~1%. Material
            # tasks keep the full gauntlet. Toggle with ORCH_SOFT_GATES_ADVISORY=false.
            _soft_advisory = (os.environ.get("ORCH_SOFT_GATES_ADVISORY", "true").lower() in ("true", "1", "yes")
                              and not t.get("material"))
            _soft_flags = []

            # GRADUATED AUTONOMY: proven (task_class × domain × model) triples skip gates
            _autonomy_skip = {}
            try:
                _ga_domain = model_portfolios.classify(t, (_plan or {}).get("files", [])) if _plan is not None else "backend"
                _ga_agent = f"{coder}:{visible_model}" if coder != "claude" else f"claude:{visible_model}"
                _autonomy_skip, _ga_level = graduated_autonomy.should_skip_gates(t, _ga_agent, _ga_domain)
                if _ga_level >= 3:
                    set_state(t["id"], note=f"graduated-autonomy: trust level {_ga_level} — skipping gates")
            except Exception as e:
                _log.debug("hook graduated_autonomy failed: %s", e)

            # CACHE GATE BYPASS: if result_cache hit on same base commit, ALL gates already passed.
            _cache_bypass = False
            try:
                if sig and cache_gate_bypass.should_bypass(sig, repo, base):
                    _cache_bypass = True
                    cache_gate_bypass.record_bypass(t["id"], sig, name, slug)
                    set_state(t["id"], note="cache-gate-bypass: identical prior run passed all gates")
            except Exception as e:
                _log.debug("hook cache_gate_bypass failed: %s", e)

            # SPECULATIVE EXEC: for template-matched tasks, agent already ran build — skip redundant gate
            _spec_skip = False
            try:
                _spec_skip_ok, _spec_reason = speculative_exec.can_skip_build_gate(
                    out, t, diff_plan=_plan)
                if _spec_skip_ok:
                    _spec_skip = True
                    set_state(t["id"], note=f"speculative-exec: {_spec_reason}")
            except Exception as e:
                _log.debug("hook speculative_exec failed: %s", e)

            if _autonomy_skip.get("skip_all"):
                # Graduated autonomy Level 4: skip ALL gates — proven pattern
                v = {"verdict": "pass", "notes": "graduated-autonomy L4: proven pattern"}
                jv = {"verdict": "pass", "score": 9, "notes": "graduated-autonomy L4",
                      "legal_counsel_required": False, "legal_risk": ""}
                conf = {"confidence": 0.99, "reason": "graduated-autonomy L4"}
                conf_score = 0.99
            elif _cache_bypass:
                # All gates already passed on identical prior run — skip everything
                v = {"verdict": "pass", "notes": "cache-bypass: prior run passed"}
                jv = {"verdict": "pass", "score": 8, "notes": "cache-bypass",
                      "legal_counsel_required": False, "legal_risk": ""}
                conf = {"confidence": 0.95, "reason": "cache-bypass"}
                conf_score = 0.95
            else:
                # PARALLEL GATES: run verify + judge + confidence CONCURRENTLY (20X-50X wall time).
                # Previously these ran sequentially (30-90s total); now they run in parallel (~10-30s).
                _diff_for_judge = ""
                try:
                    _diff_for_judge = subprocess.check_output(
                        ["git", "diff", f"{base}...HEAD"], cwd=wt, text=True, errors="replace")[:60000]
                    t["_diff_bytes"] = len(_diff_for_judge.encode("utf-8", errors="ignore"))
                    try:
                        _files_for_judge = subprocess.check_output(
                            ["git", "diff", "--name-only", f"{base}...HEAD"],
                            cwd=wt, text=True, errors="replace")[:20000]
                        t["_touched_files"] = [x for x in _files_for_judge.splitlines() if x.strip()]
                    except Exception as e:
                        _log.debug("hook diff_name_only failed: %s", e)
                except Exception as e:
                    _log.debug("hook diff_for_judge failed: %s", e)

                try:
                    _gate_results = parallel_gates.run_gates(
                        wt, base, deps, t, model, proj, name, _diff_for_judge,
                        use_confidence=USE_CONFIDENCE)
                    v = _gate_results.get("verify", {"verdict": "pass", "notes": ""})
                    jv = _gate_results.get("judge", {"verdict": "pass", "score": 6, "notes": "",
                                                      "legal_counsel_required": False, "legal_risk": ""})
                    _conf_result = _gate_results.get("confidence", {})
                    _gate_wall = _gate_results.get("wall_s", 0)
                    set_state(t["id"], note=f"parallel-gates: {_gate_results.get('mode','?')} in {_gate_wall}s")
                except Exception as _pge:
                    # Fallback to sequential
                    v = verify.review_diff(wt, base, dependents=deps if deps else None, project=name)
                    try:
                        jv = judge.review(t["prompt"][:2000], _diff_for_judge, model, project=name)
                    except Exception as _je:
                        jv = {"verdict": "pass", "score": 6, "notes": f"judge unavailable ({_je})",
                              "legal_counsel_required": False, "legal_risk": ""}
                    _conf_result = {}

                if v["verdict"] == "fail":
                    if _soft_advisory:
                        _soft_flags.append("verify: " + (v.get("notes") or "")[:180])
                    else:
                        if _agentic_repair_continue(
                            t, "verify", v.get("notes") or "",
                            attempt,
                            "Verification failed. Fix the specific verifier objection in the current diff, rerun checks, and commit the corrected implementation.",
                        ):
                            continue
                        set_state(t["id"], state="BLOCKED", note="verify: " + v["notes"])
                        approval(name, "verify", f"Verification flagged {slug}",
                                 why=v["notes"], risk="cheap-model review wants a human look",
                                 detail=out[-3000:])
                        regression.record(name, slug, kind, t["prompt"][:500], "verify: " + v["notes"], v["notes"])
                        record(t, name, slug, kind, visible_model, acct, attempt, True, False, out, t0, cost=run_cost); return

                # quality gate: mutation + property tests (blocking if MUTATION_CMD/PROPERTY_CMD set)
                # SPECULATIVE EXEC: skip if agent already proved green build
                if not _spec_skip:
                    qg = quality_gate.run(wt)
                    if not qg["pass"]:
                        if _soft_advisory:
                            _soft_flags.append("quality: " + (qg.get("notes") or "")[:180])
                        else:
                            if _agentic_repair_continue(
                                t, "quality", qg.get("notes") or "",
                                attempt,
                                "Quality gate failed. Fix the concrete failing mutation/property/test issue in-place, rerun checks, and commit.",
                            ):
                                continue
                            set_state(t["id"], state="BLOCKED", note="quality gate: " + qg["notes"])
                            approval(name, "verify", f"Quality gate failed: {slug}",
                                     why=qg["notes"], risk="mutation or property test score below threshold",
                                     detail=out[-2000:])
                            regression.record(name, slug, kind, t["prompt"][:500],
                                              "quality gate: " + qg["notes"], qg["notes"])
                            record(t, name, slug, kind, visible_model, acct, attempt, True, False, out, t0, cost=run_cost); return

                if jv["verdict"] != "pass":
                    if _soft_advisory:
                        _soft_flags.append("judge: " + (jv.get("notes") or "")[:180])
                    else:
                        if _agentic_repair_continue(
                            t, "judge", jv.get("notes") or "",
                            attempt,
                            "Cross-model review failed. Fix the specific issue without broadening scope, rerun checks, and commit.",
                        ):
                            continue
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

                # Confidence (already computed in parallel)
                conf = {"confidence": None, "reason": ""}
                decision = "auto"
                if _conf_result and "decision" in _conf_result:
                    decision = _conf_result["decision"]
                    conf = {k: v for k, v in _conf_result.items() if k != "decision"}
                elif os.environ.get("CONFIDENCE_GATE", "true").lower() == "true":  # read live so auto-approve toggles without restart
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

            # ARTIFACT GUARD: persist branch, patch, commit SHA, touched files BEFORE integration.
            # This kills the missing-branch recovery loop by ensuring every completed task has
            # enough data to reconstruct its work without re-running the agent.
            try:
                task_artifacts.capture(repo, slug, f"agent/{slug}", base,
                                       wt if os.path.isdir(wt) else repo,
                                       test_log=out[-5000:], cost=run_cost)
            except Exception as _ae:
                print(f"[artifacts] capture failed for {slug}: {_ae}")

            # FLEET BRANCH SHARE: push the verified agent branch to origin so the OTHER runner
            # Mac's sweeper/merge-train can see it. Local-only branches were the root cause of
            # the recover-missing-branch churn (two Macs, one queue, branches on one disk).
            # Fail-soft: offline/no-remote keeps the old local-only behavior. Env-gated so it
            # can be disabled fleet-wide via the config gateway if a repo must stay local.
            if os.environ.get("ORCH_SHARE_AGENT_BRANCHES", "true").lower() in ("true", "1", "yes", "on"):
                # Durable share: retry the push (transient network/non-ff during outages was the root
                # cause of local-only branches that later got GC'd → recover-missing-branch churn).
                # Verify the ref actually landed on origin; if it never does, leave a durable marker
                # so the branch is NOT eligible for local GC (governor now refuses to delete unshared).
                _shared = False
                for _attempt in range(3):
                    try:
                        _pr = subprocess.run(["git", "push", "-u", "origin", f"agent/{slug}"],
                                             cwd=repo, capture_output=True, text=True, timeout=180)
                        if _pr.returncode == 0:
                            _shared = True
                            break
                        # non-ff (branch already on origin ahead) counts as shared
                        if "already exists" in (_pr.stderr or "") or "up-to-date" in (_pr.stderr or "").lower():
                            _shared = True
                            break
                        print(f"[branch-share] push agent/{slug} attempt {_attempt+1} failed: {(_pr.stderr or '')[-160:]}")
                    except Exception as _pe:
                        print(f"[branch-share] push agent/{slug} attempt {_attempt+1} error: {_pe}")
                    time.sleep(2 * (_attempt + 1))
                if not _shared:
                    print(f"[branch-share] WARNING agent/{slug} not shared to origin after retries; "
                          f"branch kept local (governor will not GC unshared branches)")

            result = integrate(repo, f"agent/{slug}", base, test_cmd, slug, v["notes"], "passed", project=name)
            POOL.mark_ok(acct)
            integrated = result == "MERGED"
            if integrated and sig:
                result_cache.store(sig, name, slug, f"agent/{slug}", v["notes"])
            if integrated:
                try:
                    import merged_diff_library
                    merged_diff_library.record(name, slug, kind, t.get("prompt", ""), repo, base, "HEAD")
                except Exception as e:
                    _log.debug("hook merged_diff_library failed: %s", e)
                # TASK FUSION: if this was a fused parent task, mark children DONE
                if kind == "fused" or "fused_children:" in str(t.get("note") or ""):
                    try:
                        import task_fusion
                        _fused_count = task_fusion.mark_children_done(t["id"])
                        if _fused_count:
                            _log.debug("task_fusion: marked %d children DONE for parent %s", _fused_count, slug)
                    except Exception as e:
                        _log.debug("hook task_fusion.mark_children_done failed: %s", e)
            # BUILDFAIL is not a task state — record it as BLOCKED with a build-fix note so auto_remediate
            # re-plans it (fix the build errors) instead of shipping build-breaking code.
            state_val = "BLOCKED" if result == "BUILDFAIL" else result
            if result == "BUILDFAIL":
                # INLINE BUILD-FIX: a fast non-Claude model (Gemini/DeepSeek) turns the red build into a
                # concrete fix directive, injected into the note so auto_remediate re-drafts build-aware
                # (converts "recycled forever" into "self-corrected + shipped").
                _fix = ""
                try:
                    import build_fixer
                    _fix = build_fixer.fix_directive(build_fixer.load_log(slug), _diff_for_judge,
                                                     t.get("prompt", ""), project=name)
                except Exception:
                    _fix = ""
                # CODER SWITCH: after repeated red builds on the SAME backend, route the re-draft to a
                # DIFFERENT coder (mirror of the release-level self-heal) so we stop recycling on a coder
                # that keeps producing a broken build. Persisted via task.force_coder (pick() honors it).
                _bfc = int(t.get("build_fail_count") or 0) + 1
                _switch = int(os.environ.get("ORCH_BUILD_FAIL_CODER_SWITCH", "2"))
                _second = os.environ.get("ORCH_SECOND_CODER")
                _patch = {"build_fail_count": _bfc}
                _esc = ""
                if _bfc >= _switch and _second and str(t.get("force_coder") or "") != _second:
                    _patch["force_coder"] = _second
                    _esc = f" [escalated to coder '{_second}' after {_bfc} build fails]"
                try:
                    db.update("tasks", {"id": t["id"]}, _patch)
                except Exception as e:
                    _log.debug("hook build_fail_update failed: %s", e)
                _note = ("integrate BUILDFAIL — production build red; fix build/type errors before merge. "
                         + _fix + _esc)[:1800]
            else:
                _note = f"verify pass (conf={conf_score}); integrate={result} ({INTEGRATION_MODE})"
                if _soft_flags:
                    _note = (_note + " | advisory (shipped on green build): " + "; ".join(_soft_flags))[:1800]
                t["_review_failures"] = len(_soft_flags)
                if result == "MERGED" and (t.get("build_fail_count") or t.get("force_coder")):
                    # clean slate on success so a later unrelated fail starts fresh
                    try:
                        db.update("tasks", {"id": t["id"]}, {"build_fail_count": 0, "force_coder": None})
                    except Exception as e:
                        _log.debug("hook clean_slate_update failed: %s", e)
            if result in ("CONFLICT", "TESTFAIL", "BUILDFAIL"):
                _cat = {"CONFLICT": "conflict", "TESTFAIL": "testfail", "BUILDFAIL": "buildfail"}[result]
                if _agentic_repair_continue(
                    t, _cat, (_note + "\n\n" + out[-2500:]),
                    attempt,
                    f"Integration returned {result}. Keep the same task and branch, fix the root cause, rerun the failing build/test/merge path, and commit.",
                ):
                    continue
            set_state(t["id"], state=state_val, confidence=conf_score, note=_note)
            if result in ("CONFLICT", "TESTFAIL", "BUILDFAIL"):
                approval(name, "integrate", f"{slug} {result.lower()} on integrate",
                         why=f"could not auto-integrate ({result})", detail=out[-2000:])
                regression.record(name, slug, kind, t["prompt"][:500], f"integrate {result}",
                                  "run the prod build locally and fix all type/build errors before finishing")
            # COLOSSEUM SETTLEMENT: update model reputation based on real merge/deploy outcome.
            # This feeds the competitive coding economy — models that merge get promoted, models
            # that fail get demoted, and $/merged-diff is the ultimate metric.
            try:
                _agent_id = f"{coder}:{visible_model}" if coder != "claude" else f"claude:{visible_model}"
                colosseum.settle(t, _agent_id, {
                    "merged": integrated, "deployed": False,  # deploy verified separately
                    "rollback": False, "cost_usd": run_cost.get("usd", 0) if isinstance(run_cost, dict) else 0,
                    "wall_s": time.time() - t0,
                    "review_passed": v.get("verdict") == "pass" if v else True,
                    "tests_passed": True,
                    "tokens_in": run_cost.get("input_tokens", 0) if isinstance(run_cost, dict) else 0,
                    "tokens_out": run_cost.get("output_tokens", 0) if isinstance(run_cost, dict) else 0,
                })
            except Exception as e:
                _log.debug("hook colosseum failed: %s", e)
            # PROMPT BANKRUPTCY: record outcome for lineage tracking
            try:
                prompt_bankruptcy.record_attempt(t, success=integrated)
            except Exception as e:
                _log.debug("hook prompt_bankruptcy_record failed: %s", e)
            # MODEL PORTFOLIOS: update domain-specific reputation
            try:
                _domain_post = model_portfolios.classify(t, (_plan or {}).get("files", []))
                _agent_post = f"{coder}:{visible_model}" if coder != "claude" else f"claude:{visible_model}"
                _cost_val = run_cost.get("usd", 0) if isinstance(run_cost, dict) else 0
                model_portfolios.update(_agent_post, _domain_post, integrated, _cost_val, time.time() - t0)
            except Exception as e:
                _log.debug("hook model_portfolios failed: %s", e)
            # MODEL SLASHING: record outcome for penalty tracking
            try:
                _slash_id = f"{coder}:{visible_model}" if coder != "claude" else f"claude:{visible_model}"
                _cost_s = run_cost.get("usd", 0) if isinstance(run_cost, dict) else 0
                model_slashing.record(_slash_id, merged=integrated, tests_passed=True,
                                       rollback=False, cost_usd=_cost_s,
                                       domain=_domain_post if _domain_post is not None else "general")
            except Exception as e:
                _log.debug("hook model_slashing_record failed: %s", e)
            # INTENT GRAPH: record task → files → outcome for future replay
            try:
                _ig_files = (_plan or {}).get("files", [])
                _ig_diff_hash = hashlib.sha256(out[-5000:].encode()).hexdigest()[:16] if out else ""
                intent_graph.record(t, _ig_files, _ig_diff_hash, {
                    "merged": integrated, "cost_usd": _cost_val,
                    "wall_s": time.time() - t0, "model": visible_model, "rollback": False,
                })
            except Exception as e:
                _log.debug("hook intent_graph failed: %s", e)
            # CROSS-PROJECT TEMPLATES: index this merge for other projects
            try:
                _ig_files_xp = (_plan or {}).get("files", [])
                cross_project_templates.index_merge(t, name, _ig_files_xp,
                    diff_summary=out[-500:] if out else "", merge_rate=1.0 if integrated else 0)
            except Exception as e:
                _log.debug("hook cross_project_templates_index failed: %s", e)
            # GRADUATED AUTONOMY: record outcome for trust level tracking
            try:
                _ga_d = model_portfolios.classify(t, []) if _plan is None else _ga_domain
                _ga_a = f"{coder}:{visible_model}" if coder != "claude" else f"claude:{visible_model}"
                graduated_autonomy.record_outcome(t, _ga_a, _ga_d, merged=integrated, rollback=False)
            except Exception as e:
                _log.debug("hook graduated_autonomy_record failed: %s", e)
            # SESSION CACHE: save session context for potential retry warm start
            try:
                _sc_ctx = session_cache.extract_session_context(out, error="" if integrated else "integration failed")
                _sc_ctx["model"] = visible_model
                _sc_ctx["cost_usd"] = run_cost.get("usd", 0) if isinstance(run_cost, dict) else 0
                session_cache.save_session(t["id"], attempt, _sc_ctx)
            except Exception as e:
                _log.debug("hook session_cache_save failed: %s", e)
            # ADAPTIVE BUDGET: record actual output length for future predictions
            try:
                _out_tokens = run_cost.get("output_tokens", 0) if isinstance(run_cost, dict) else 0
                if _out_tokens > 0:
                    _dom_ab = model_portfolios.classify(t, []) if _domain_post is None else _domain_post
                    adaptive_budget.record_output(t, _dom_ab, _out_tokens)
            except Exception as e:
                _log.debug("hook adaptive_budget_record failed: %s", e)
            # PROMPT DISTILLATION: distill winning prompts into minimal templates
            try:
                if integrated:
                    _ig_files_pd = (_plan or {}).get("files", [])
                    _cost_pd = run_cost.get("usd", 0) if isinstance(run_cost, dict) else 0
                    prompt_distillation.distill(t, out, _ig_files_pd, project=name, cost_usd=_cost_pd)
            except Exception as e:
                _log.debug("hook prompt_distillation_distill failed: %s", e)
            # OUTPUT RECYCLING: recycle partial work from failures
            try:
                if not integrated:
                    output_recycling.recycle(t["id"], wt if os.path.isdir(wt) else repo,
                                             out, error="integration failed")
            except Exception as e:
                _log.debug("hook output_recycling_recycle failed: %s", e)
            # CADE TOURNAMENTS: update standings + failure fingerprints
            try:
                cade_tournaments.record_tournament_outcome(visible_model, won=integrated)
                if not integrated:
                    _err_fp = (out or "")[-300:] if out else "unknown failure"
                    cade_tournaments.record_failure(coder, visible_model, _err_fp, t)
                if integrated:
                    _ig_files_wb = (_plan or {}).get("files", [])
                    _wb_cost = run_cost.get("usd", 0) if isinstance(run_cost, dict) else 0
                    _wb_tin = run_cost.get("input_tokens", 0) if isinstance(run_cost, dict) else 0
                    _wb_tout = run_cost.get("output_tokens", 0) if isinstance(run_cost, dict) else 0
                    cade_tournaments.writeback_outcome(
                        t, {"merged": integrated, "diff_summary": (out or "")[-500:]},
                        project=name, merged_files=_ig_files_wb,
                        model=visible_model, coder=coder,
                        domain=_domain_post if _domain_post is not None else "general",
                        wall_s=time.time() - t0, cost_usd=_wb_cost,
                        tokens_in=_wb_tin, tokens_out=_wb_tout)
            except Exception as e:
                _log.debug("hook cade_tournaments failed: %s", e)
            # PORTFOLIO REBALANCER: record outcome for $/merged-line cost curves
            try:
                _pr_domain = _domain_post if _domain_post is not None else "general"
                _pr_cost = run_cost.get("usd", 0) if isinstance(run_cost, dict) else 0
                _pr_lines = len(t.get("_touched_files") or []) * 50  # rough estimate
                portfolio_rebalancer.record_outcome(
                    visible_model, _pr_domain, integrated, _pr_cost,
                    _pr_lines, wall_s=time.time() - t0)
            except Exception as e:
                _log.debug("hook portfolio_rebalancer failed: %s", e)
            # CAPACITY PACER: record token spend for budget pacing
            try:
                _cp_tokens = 0
                if isinstance(run_cost, dict):
                    _cp_tokens = run_cost.get("input_tokens", 0) + run_cost.get("output_tokens", 0)
                if _cp_tokens > 0:
                    _cp_cost = run_cost.get("usd", 0) if isinstance(run_cost, dict) else 0
                    capacity_pacer.record_spend(acct or "unknown", _cp_tokens, _cp_cost)
            except Exception as e:
                _log.debug("hook capacity_pacer failed: %s", e)
            # PROOF PROPAGATION: after merge, propagate to other projects
            try:
                if integrated:
                    _pp_files = (_plan or {}).get("files", [])
                    _pp_diff = ""
                    try:
                        _pp_diff = subprocess.check_output(
                            ["git", "diff", f"{base}...HEAD", "--stat"],
                            cwd=wt, text=True, errors="replace")[:2000]
                    except Exception as e:
                        _log.debug("hook diff_stat failed: %s", e)
                    _pp_results = proof_propagation.propagate(t, name, _pp_files, _pp_diff)
                    if _pp_results:
                        set_state(t["id"], note=f"propagated to {len(_pp_results)} projects")
            except Exception as e:
                _log.debug("hook proof_propagation failed: %s", e)
            # BANKRUPTCY DECOMPOSE: on failure, auto-decompose if bankrupt
            try:
                if not integrated:
                    import prompt_bankruptcy as _pb_check
                    if _pb_check.is_bankrupt(t):
                        _bd_subs = bankruptcy_decompose.decompose(t, name, wt if os.path.isdir(wt) else repo)
                        if _bd_subs:
                            set_state(t["id"], note=f"bankrupt → decomposed into {len(_bd_subs)} sub-tasks")
            except Exception as e:
                _log.debug("hook bankruptcy_decompose failed: %s", e)
            # OUTCOME ROUTER: record success/failure for future model routing decisions
            try:
                import outcome_router
                outcome_router.record_outcome(slug, visible_model, integrated)
            except Exception as e:
                _log.debug("hook outcome_router.record failed: %s", e)
            # TASK MEMORY: learn from this task's outcome for individual + hivemind intelligence
            try:
                import task_memory
                _tm_cost = run_cost.get("usd", 0) if isinstance(run_cost, dict) else 0
                _tm_wall = time.time() - t0
                _tm_files = t.get("_touched_files", [])
                task_memory.learn_from_outcome(
                    t, out, visible_model, _tm_cost, _tm_wall, integrated,
                    coder, name, _tm_files)
            except Exception as e:
                _log.debug("hook task_memory.learn failed: %s", e)
            # CONFLICT PREDICTOR: record whether our prediction was correct
            try:
                import conflict_predictor
                conflict_predictor.record_outcome(t["id"], not integrated, False)
            except Exception as e:
                _log.debug("hook conflict_predictor.record failed: %s", e)
            # RETRY BUDGET: record attempt outcome for future budget decisions
            try:
                import retry_budget
                retry_budget.record_attempt(slug, attempt, visible_model, integrated, "")
            except Exception as e:
                _log.debug("hook retry_budget.record failed: %s", e)
            # PROMPT EVOLUTION: record prompt structure → outcome for self-improvement
            try:
                import prompt_evolution
                _pe_cost = run_cost.get("usd", 0) if isinstance(run_cost, dict) else 0
                prompt_evolution.record_prompt_outcome(t, draft_prompt, visible_model, integrated, _pe_cost, attempt)
            except Exception as e:
                _log.debug("hook prompt_evolution.record failed: %s", e)
            # ERROR TAXONOMY: record remediation outcome
            try:
                import error_taxonomy
                error_taxonomy.record_remediation(
                    t.get("_last_error_class", "unknown"),
                    "retry" if integrated else "failed",
                    integrated)
            except Exception as e:
                _log.debug("hook error_taxonomy.record failed: %s", e)
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
    total_tokens = int(row["input_tokens"] or 0) + int(row["output_tokens"] or 0)
    diff_bytes = int(t.get("_diff_bytes") or 0)
    review_failures = int(t.get("_review_failures") or (0 if tests_ok else 1))
    outcome = {
        "task_id": t["id"], "project": project, "slug": slug, "kind": kind,
        "model": model, "account": (acct or {}).get("name"), "attempts": attempt,
        "rate_limited": any(s in out.lower() for s in RATE),
        "tests_passed": tests_ok, "integrated": integrated,
        "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"],
        "usd": row["usd"], "wall_ms": int((time.time() - t0) * 1000),
        "diff_bytes": diff_bytes, "total_tokens": total_tokens,
        "tokens_per_diff_byte": round(total_tokens / max(1, diff_bytes), 6),
        "review_failures": review_failures,
        "review_failures_per_merge": round(review_failures / max(1, 1 if integrated else 0), 6),
        "sensitivity": t.get("sensitivity")}
    # Track experiment assignment if this task is part of an A/B trial
    exp_meta = t.get("experiment_id")
    if exp_meta:
        outcome["experiment_id"] = exp_meta
        outcome["experiment_variant"] = t.get("experiment_variant", "control")
    try:
        db.insert("outcomes", outcome)
    except Exception as e:
        for k in ("diff_bytes", "total_tokens", "tokens_per_diff_byte",
                  "review_failures", "review_failures_per_merge", "sensitivity"):
            outcome.pop(k, None)
        try:
            db.insert("outcomes", outcome)
        except Exception as e2:
            print(f"[record] outcomes insert skipped: {e2 or e}")
    try:
        mesh_optimizer.settle(
            t, project=project, slug=slug, kind=kind, model=model,
            coder=str(model).split(":", 1)[0] if ":" in str(model) else "",
            tests_passed=bool(tests_ok), integrated=bool(integrated),
            output=out, cost=row, wall_s=time.time() - t0,
        )
    except Exception as e:
        print(f"[record] mesh optimizer settlement skipped: {e}")
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
    ("dbrecover-60",  "db_recovery_sprint.py","interval", 60),   # when Supabase 522 clears, sprint drain/release immediately
    ("resmesh-60",    "resilience_mesh.py", "interval", 60),    # keep local/vendor/deploy prep moving during Supabase/vendor outages
    ("train-60",      "merge_train.py",     "interval", 60),    # canonical approved-card cleanup train
    ("mergestall-900","merge_stall_monitor.py","interval",900), # alert if merges stop landing despite a real backlog (2026-07-08 incident safeguard)
    ("mergecycle-300","merge_cycle.py",       "interval",300), # snapshot branch-blocked queue pressure by project/branch
    ("sweep-90",      "integration_sweeper.py","interval",90),  # passed-tests-but-not-integrated -> canonical train
    ("sentinel-300",  "sentinel.py",        "interval", 300),   # self-healing: DB-outage offline sweeps, checkout drift, runner singleton, RAM clamp, stale code
    ("medic-90",      "resource_medic.py",  "interval", 90),    # autonomous resource bots: predictive OOM guard, thrash-hunter (durable model exclusion / lane lowering), process hygiene, loop breaker
    ("modelscout-14400","model_scout.py",   "interval", 14400), # discover new vendor model releases, eval vs incumbent, auto-adopt if better (quality/speed/cost), rollback on regression
    ("ownermodel-300","owner_decision_model.py","interval",300),# draft/auto-apply gated decisions from owner precedent
    ("ev-900",        "ev_scheduler.py",    "interval", 900),   # EV-per-token queue ordering + zero-EV parking
    ("codercanary-1800","coder_canary.py",  "interval", 1800),  # force low-risk per-coder samples for learned routing
    ("ollamacal-3600","ollama_calibrator.py","interval",3600),  # calibrate local model pass rate/latency for routing
    ("histmodel-night","model_historical_canary.py","daily",(1, 20)), # real merged-task canaries per local model
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
    # No second mergetrain alias here: direct task completion is the canonical fast route
    # into the integration branch, train-60 handles legacy approved cards, release_train
    # promotes batches to prod. Running both train entrypoints created duplicate retries.
    ("draftact-300",  "draftactions",       "interval", 300),   # pre-draft exact commands for action items
    ("prebrief-300",  "prebrief",           "interval", 300),   # plain-English legal decision briefs
    ("bizradar-900",  "bizradar",           "interval", 900),   # early business-model decision radar
    ("autoexec-60",   "autoexec",           "interval", 60),    # auto-run proven-safe steps + queued ones
    ("legaltri-300",  "legaltriage",        "interval", 300),   # classify legal cards; auto-clear routine
    ("decbriefs-300", "decisionbriefs",     "interval", 300),   # war-room briefs for legal/strategic decisions
    ("improve-900",   "improve",            "interval", 900),   # continuous '20-500X better?' idea miner (every 15m, never throttled)
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
    ("quarantine-180","quarantine",         "interval", 180),   # rewrite terminal blockers into safe claimable work
    ("objective-3600","objective",          "interval", 3600),  # meta-controller: tune knobs toward north-star
    ("selfcheck-600", "selfcheck",          "interval", 600),   # periodic invariant assert + auto-heal
    ("push-180",      "pushdecisions",      "interval", 180),   # push new decisions/actions to email + Smarter
    ("selfheal-120",  "selfheal",           "interval", 120),   # auto-file fixes for prod incidents
    ("credresolver-300", "credresolver",     "interval", 300),   # auto-resolve credential_requests from env
    ("newapp-300",    "newapp",             "interval", 300),   # process one-command new-app requests
    ("autopilot-180", "autopilot",          "interval", 180),   # queue/improvement operating bot
    ("abedge-600",    "abedge",             "interval", 600),   # edge A/B promote/rollback on live traffic
    ("roadmap-weekly","roadmap",            "weekly",   (1, 6, 0)),# revenue-ranked weekly focus proposals
    ("worktreegc-300","worktreegc",         "interval", 300),   # remove stale agent worktrees (unblocks merges)
    ("releasetrain-600","releasetrain",     "interval", 600),   # accumulate on staging, QA, release to prod
    ("deployverify-120","deployverify",     "interval", 120),   # confirm Vercel deploy / auto-rollback
    ("releasekpi-1800","release_kpi.py",     "interval", 1800),  # released->deploy-green KPI + self-tune gate
    ("integratekpi-1800","integrate_kpi.py",  "interval", 1800),  # per-app integrate build-pass / merge-rate KPI
    ("fleetsync-90",  "fleet_control.py",     "interval", 90),    # fleet gateway: central config + control + auto-pull (survives a busy main loop)
    ("stripe-daily",  "stripe",             "daily",    (6, 0)),  # pull real MRR from Stripe -> app_revenue
    ("ownerreport-wk","ownerreport",        "weekly",   (1, 7, 0)),# Monday owner report -> email
    ("revattr-daily", "revattr",            "daily",    (5, 45)),# attribute merges to revenue movement
    ("specwriter-wk", "specwriter",         "weekly",   (0, 5, 0)),# apps self-write SPEC.md
    ("prewarm-120",   "prewarm",            "interval", 120),   # warm next worktrees/context (0 spend)
    ("preflight-90",  "preflight",          "interval", 90),    # cheap multi-provider triage before agentic spend
    ("governor-900",  "governor",           "interval", 900),   # EV-based capacity allocation
    ("costslo-1800",  "costslo",            "interval", 1800),  # hold per-app $/merge SLOs
    ("promote-daily", "promote",            "daily",    (6, 30)),# productize proven capabilities
    ("dedup-600",     "dedup",              "interval", 600),   # collapse near-duplicate queued tasks (+ semantic pass)
    ("conflictres-300","conflictresolve",   "interval", 300),   # zero-token auto-rebase/branch recovery for BLOCKED
    ("contcompact-300","contcompact",       "interval", 300),   # collapse cont-* shard floods into few tasks
    ("backlogcompact-600","backlogcompact", "interval", 600),   # collapse stale broad queued backlog into batches
    ("canaryecon-600","canaryecon",         "interval", 600),   # promote/rollback canaries on cost+quality
    ("learnmerges-dy","learnmerges",        "daily",    (5, 30)),# reinforce from merged diffs
    ("embedretry-300","embedretry",         "interval", 300),   # drain knowledge_embed retry queue (429 backoff)
    ("promptfactory-4h","promptfactory",    "interval", 14400), # objective -> intake DAG, no operator in the loop
    ("metaloop-1800", "meta_loop.py",       "interval", 1800), # continuous meta-improvement loop (every 30m)
    ("metaloop-daily","meta_loop.py",       "daily",    (4, 0)),# deeper improvement sweep overnight
    ("feedback-daily","feedback_review.py", "daily",    (5, 0)),# agent->orchestrator improvements
    ("experiments-daily", "experiment_portfolio.py","daily", (3, 30)),# autonomous A/B experiment portfolio
    ("usage-daily",   "usage_meter.py",     "daily",    (6, 0)),# external API/subscription spend
    ("thermal-300",   "thermal_queue.py",   "interval", 300),   # recompute thermal queue ranking (EV/min)
    ("modelscore-600","model_score.py",     "interval", 600),   # recompute $/merged-diff model scores
    ("agentmarket-900","agentmarket",       "interval", 900),   # cross-app role-aware model mesh
    ("commonbrain-1800","commonbrain",      "interval", 1800),  # reusable brain deployments/outcomes
    ("promptbankrupt-600","promptbankruptcy","interval",600),    # stop repeating losing prompt patterns
    ("portfolios-600","modelportfolios",    "interval", 600),   # per-domain model champions
    ("slashing-600",  "modelslashing",      "interval", 600),   # allocation penalties for weak routes
    ("materializer-300","queue_materializer.py","interval",300), # close completed decomposed parents
    ("builddaemon-600","build_daemon.py",   "interval", 600),   # warm repos: deps, worktrees, build check
    ("lanescheduler-120","lane_scheduler.py","interval", 120),   # manage Ollama lanes + orphan cleanup
    ("slocontroller-300","slo_controller.py","interval", 300),   # autonomous SLO enforcement + remediation
    ("colosseum-900",  "colosseum.py",       "interval", 900),   # model tournament + promotion/demotion
    ("prompt-bankruptcy-600", "prompt_bankruptcy.py", "interval", 600),  # scan bankrupt patterns
    ("model-portfolios-600",  "model_portfolios.py",  "interval", 600),  # domain standings
    ("model-slashing-600",    "model_slashing.py",    "interval", 600),  # slashing state + quarantine expiry
    ("intent-graph-900",      "intent_graph.py",      "interval", 900),  # intent graph stats + prune
    ("cross-templates-900",   "cross_project_templates.py", "interval", 900),  # cross-project template stats
    ("predictive-600",        "predictive_scheduler.py", "interval", 600),  # predictive task pre-queuing
    ("session-cache-1800",    "session_cache.py",      "interval", 1800), # session cache pruning
    ("graduated-autonomy-600","graduated_autonomy.py", "interval", 600),  # trust level reporting
    ("adaptive-budget-600",   "adaptive_budget.py",    "interval", 600),  # token budget stats
    ("prompt-distill-900",    "prompt_distillation.py", "interval", 900), # distillation stats
    ("output-recycle-1800",   "output_recycling.py",   "interval", 1800), # prune expired recycled data
    ("cade-tournaments-600",  "cade_tournaments.py",   "interval", 600),  # tournament standings
    ("queue-elimination-120", "queue_elimination.py",  "interval", 120),  # zero-token elimination at queue time
    ("proof-propagation-600", "proof_propagation.py",  "interval", 600),  # cross-project proof replay
    ("intent-compiler-900",   "intent_compiler.py",    "interval", 900),  # compile mature intents to scripts
    ("bankruptcy-decompose-600","bankruptcy_decompose.py","interval",600), # decompose bankrupt prompts
    ("portfolio-rebalancer-300","portfolio_rebalancer.py","interval",300), # portfolio cost curve reporting
    ("batch-fusion-120",      "batch_fusion.py",       "interval", 120),  # fuse queued tasks for same repo
    ("capacity-pacer-180",    "capacity_pacer.py",     "interval", 180),  # token budget pacing report
    ("account-partition-600", "account_partition.py",   "interval", 600),  # cross-machine account affinity
    ("gen-feedback-300",      "generator_feedback.py",  "interval", 300),  # outcome feedback for generators
    ("exhaustion-signal-60",  "exhaustion_signal.py",   "interval",  60),  # surface exhaustion to dashboard
    ("surge-planner-300",     "surge_planner.py",       "interval", 300),  # plan high-value surge on reset
    ("queue-velocity-900",    "queue_velocity.py",      "interval", 900),  # PID controller: auto-pause generators when queue growing
    ("toolchain-1800",        "toolchain_gate.py",      "interval", 1800), # verify build toolchain per project, auto-repair
    ("pause-arbiter-300",     "pause_arbiter.py",       "interval", 300),  # lift self-clearing pauses (TTL + registered checks)
    ("fleet-stuck-300",       "fleet_stuck_alarm.py",   "interval", 300),  # queued>0 & running=0 for >15min -> notify + remediate
    ("queue-bankruptcy-3600", "queue_bankruptcy.py",    "interval", 3600), # close QUEUED tasks past ORCH_TASK_BANKRUPTCY_DAYS
    ("scoreboard-600",        "scoreboard.py",          "interval", 600),  # merged/day, first-pass rate, paused-minutes, queue mix
    ("context-distill-3600",  "context_cache_distill.py","interval", 3600), # prune stale embedding-cache entries (unbounded growth fix)
    ("cost-intel-86400",      "cost_intelligence.py",   "interval", 86400), # daily: internal + external cost/value reports
    ("improve-roadmap-86400", "improvement_roadmap.py", "interval", 86400), # daily: 50x-500x claim, disclosed-assumption staged model
    ("tier-stats-300",     "tier_router_tick.py",      "interval", 300),   # tier routing stats + subscription capacity report
    ("fleet-topo-600",     "fleet_topology_tick.py",    "interval", 600),   # fleet topology optimization recommendations
    ("sub-recommend-3600", "sub_recommend_tick.py",     "interval", 3600),  # hourly subscription cost/value analysis
]
_sched_last: dict = {}

# Jobs that NEVER call a model and are safe (even desirable) to run while paused:
# protect the Mac, and keep read-only spend/health telemetry flowing.
_SAFE_WHEN_PAUSED = {"resource_governor.py", "usage_meter.py", "anomaly.py", "roi", "txn",
                     "approval_policy.py", "queue_janitor.py", "db_recovery_sprint.py",
                     "resilience_mesh.py", "resource_medic.py", "sentinel.py", "model_scout.py",
                     "integration_sweeper.py", "merge_train.py",
                     "unstick", "dagfix", "batchmech", "selftune", "cluster",
                     "governor", "costslo", "promote", "prewarm", "billingguard",
                     "dedup", "contcompact", "backlogcompact", "canaryecon", "forecast", "arbitrage", "autoscale", "bizradar",
                     "credresolver", "pushdecisions", "selfheal", "newapp", "autopilot", "abedge",
                     "stripe", "ownerreport", "worktreegc", "remediate", "quarantine", "selfcheck", "release_kpi.py",
                     "integrate_kpi.py", "fleet_control.py",
                     "thermal_queue.py", "model_score.py", "queue_materializer.py",
                     "build_daemon.py", "lane_scheduler.py", "slo_controller.py", "merge_cycle.py",
                     "colosseum.py",
                     "prompt_bankruptcy.py", "model_portfolios.py",
                     "model_slashing.py", "intent_graph.py",
                     "cross_project_templates.py", "predictive_scheduler.py",
                     "session_cache.py", "graduated_autonomy.py",
                     "adaptive_budget.py", "prompt_distillation.py",
                     "output_recycling.py", "cade_tournaments.py",
                     "queue_elimination.py", "proof_propagation.py",
                     "intent_compiler.py", "bankruptcy_decompose.py",
                     "portfolio_rebalancer.py", "batch_fusion.py",
                     "capacity_pacer.py", "account_partition.py",
                     "generator_feedback.py", "exhaustion_signal.py",
                     "surge_planner.py",
                     "pause_arbiter.py", "fleet_stuck_alarm.py", "queue_bankruptcy.py",
                     "scoreboard.py", "toolchain_gate.py", "context_cache_distill.py",
                     "cost_intelligence.py", "improvement_roadmap.py"}

# Optional autonomous-improvement jobs that are NOT yet routed through claude_cli (so their
# spend isn't counted against the $40/day cap). OFF unless ENABLE_PROACTIVE_LOOPS=true.
_PROACTIVE = {"scout", "spec", "chaos", "self_review.py", "maturity.py", "demand_mining.py",
              "capability_radar.py", "meta_loop.py", "feedback_review.py", "conventions", "learnmerges",
              "experiment_portfolio.py"}
_PROACTIVE_ON = os.environ.get("ENABLE_PROACTIVE_LOOPS", "false").lower() == "true"

# QUEUE-DEPTH OBJECTIVE: generators of speculative work (idea-miners / radars / roadmap). When the
# queue is already far deeper than the fleet can execute, STOP firing these so the backlog DRAINS
# instead of ballooning — the portfolio-level complement to session_watcher's per-continuation cap.
_GENERATORS = {"bizradar", "demand_mining.py", "capability_radar.py", "scout", "spec",
               "promote", "roadmap", "newapp", "committees"}
_qdepth = {"n": 0, "t": 0.0}

# ORCH_LEAN_MODE (opt-in, default off): periodic-only housekeeping for the heaviest self-play
# subsystems. See the comment in _fire_periodic for what this does and does not affect.
_LEAN_MODE_SKIP = {"colosseum.py", "cade_tournaments.py", "agentmarket",
                   "committees", "committeecal", "committeedocket", "committeedigest",
                   "committeerollout", "committeeboard", "committeewatch",
                   "committeeminutes", "committeekg", "committeemeta"}


def _LEAN_MODE_ON():
    return os.environ.get("ORCH_LEAN_MODE", "false").lower() in ("1", "true", "yes", "on")


def _queue_gen_ceiling():
    try:
        return max(0, int(os.environ.get("QUEUE_GEN_CEILING", "500")))
    except Exception:
        return 500


def _proactive_on():
    return os.environ.get("ENABLE_PROACTIVE_LOOPS", "false").lower() in ("1", "true", "yes", "on")


def _queue_depth():
    """Cached (60s) count of QUEUED tasks, bounded so the probe stays cheap."""
    if time.time() - _qdepth["t"] < 60:
        return _qdepth["n"]
    ceiling = _queue_gen_ceiling()
    try:
        rows = db.select("tasks", {"select": "id", "state": "eq.QUEUED",
                                   "limit": str(ceiling + 1)}) or []
        _qdepth["n"] = len(rows)
    except Exception:
        _qdepth["n"] = 0
    _qdepth["t"] = time.time()
    return _qdepth["n"]


def _fire_periodic(job: str) -> None:
    # LEAN MODE (opt-in, default off): skip the periodic housekeeping/standings jobs for the
    # heaviest self-play subsystems (colosseum, cade tournaments, agent market, the committee
    # assembly — 277 modules / ~80 periodic jobs is most of what turns compute into failed
    # releases per the 2026-07-08 postmortem). This does NOT touch the inline, load-bearing
    # calls these same modules make from run_task() every task (cade_tournaments.zero_token_patch,
    # colosseum.settle, etc.) — those run in-process regardless of the periodic scheduler and are
    # real cost savings, not noise. Only the standalone "python3 X.py" / periodic.py dispatch that
    # produces standings reports, promotions, and committee proposals is skipped. Try it for a
    # week with ORCH_LEAN_MODE=true and compare scoreboard.py's merged/day + usd_per_merge before
    # reverting to the default (off) if it doesn't help.
    if _LEAN_MODE_ON() and job in _LEAN_MODE_SKIP:
        print(f"[sched] {job} skipped — ORCH_LEAN_MODE=true", flush=True)
        return False
    # don't run uncounted proactive spenders unless explicitly enabled
    if job in _PROACTIVE and not _proactive_on():
        return False
    try:
        import drain_policy
        reason = drain_policy.skip_reason(job, queue_depth=_queue_depth())
        if reason:
            print(f"[sched] {job} skipped — {reason}; draining backlog first", flush=True)
            return False
    except Exception as e:
        print(f"[sched] {job} drain policy unavailable ({e})", flush=True)
    # throttle speculative-work generators when the queue is already deeper than we can execute
    ceiling = _queue_gen_ceiling()
    if job in _GENERATORS and _queue_depth() > ceiling:
        print(f"[sched] {job} throttled — queue depth > {ceiling} (draining backlog first)", flush=True)
        return False
    # PID controller: queue_velocity pauses generators when velocity is positive for 2+ windows
    try:
        import queue_velocity
        if queue_velocity.is_generator_paused(job):
            print(f"[sched] {job} paused by queue-velocity PID controller", flush=True)
            return False
    except Exception as e:
        _log.debug("hook queue_velocity failed: %s", e)
    # honor the kill switch for every scheduled job that could spend tokens, so a global
    # pause stops ALL spend (not just the main task loop) without restarting the runner.
    if job not in _SAFE_WHEN_PAUSED:
        try:
            if kill_switch.is_paused():
                print(f"[sched] {job} skipped (paused)", flush=True)
                return False
        except Exception as e:
            _log.debug("hook kill_switch failed: %s", e)
    # Don't stack a new instance on top of one that's still running -- see _is_still_running
    # for why this was missing and what it caused (2026-07-10, train-60/merge_train.py pileup).
    if _is_still_running(job):
        print(f"[sched] {job} still running from last cycle — skipping this launch", flush=True)
        return False
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
    _logpath = None
    for cand in (_base, os.path.join(_dir, "logs"), "/tmp/claude-orchestrator-logs"):
        try:
            os.makedirs(cand, exist_ok=True)
            _probe = os.path.join(cand, ".wtest")
            with open(_probe, "a"):
                pass
            os.remove(_probe)
            _logpath = os.path.join(cand, job.replace(".py", "").replace("_", "-"))
            break
        except Exception:
            continue
    # Reap any stale previous instance of this job before launching. Scaled to the job's own
    # configured interval (was hardcoded 3600s for every job regardless of cadence -- a 60s
    # job wouldn't be reaped for 5 hours; see _is_still_running for the incident this caused).
    _reap_stale_periodic(job, _JOB_INTERVAL.get(job, 3600))
    try:
        if _logpath:
            with open(_logpath + ".log", "a") as lf, open(_logpath + ".err", "a") as ef:
                p = subprocess.Popen(cmd, stdout=lf, stderr=ef, cwd=_dir, env=os.environ.copy())
        else:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             cwd=_dir, env=os.environ.copy())
        _PERIODIC_PIDS[job] = (p.pid, time.time())
        return True
    except Exception as e:
        print(f"[sched] {job} launch failed: {e}")
        return False

_PERIODIC_PIDS = {}  # job_name -> (pid, launch_time)

# job script -> its own configured interval (seconds), built from _SCHEDULE. Used so the
# stale-reap threshold scales with how often a job is actually supposed to run, instead of a
# single hardcoded default that's wildly wrong for fast-cadence jobs (see _is_still_running).
_JOB_INTERVAL = {job: args for (_key, job, stype, args) in _SCHEDULE if stype == "interval"}


def _is_still_running(job):
    """True if the previously-launched instance of this job is still alive.

    2026-07-10: train-60 (merge_train.py, 60s cadence) piled up 8+ concurrent instances over
    several hours -- _reap_stale_periodic only killed an instance once it had run for
    expected_interval*5, but it was ALWAYS called with a hardcoded 3600s default regardless of
    the job's real interval, so a 60s-cadence job wasn't reaped until it had run for 5 HOURS.
    Meanwhile nothing stopped a brand-new instance from being Popen'd every single tick on top
    of the still-running one -- there was no "skip if already running" check at all, only
    "kill if grotesquely stale". Each merge_train.py instance can legitimately take several
    minutes when multiple projects are repo-lock-busy (up to 120s of polling per busy project),
    so with a 60s scheduler tick they were guaranteed to overlap and accumulate. Any interval
    job whose runtime can exceed its own interval has this same latent bug. Fix: don't launch a
    new instance while the last one is still alive; let it finish (or let the properly-scaled
    reaper below kill it if it's truly stuck) instead of stacking duplicates."""
    info = _PERIODIC_PIDS.get(job)
    if not info:
        return False
    pid, _launch_t = info
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        del _PERIODIC_PIDS[job]
        return False


def _reap_stale_periodic(job, expected_interval):
    """Kill periodic children that have been running > 5x their expected interval."""
    info = _PERIODIC_PIDS.get(job)
    if not info:
        return
    pid, launch_t = info
    try:
        os.kill(pid, 0)  # check if alive
    except OSError:
        del _PERIODIC_PIDS[job]
        return
    if time.time() - launch_t > expected_interval * 5:
        try:
            os.kill(pid, 9)
            print(f"[reaper] killed stale periodic child {job} (pid {pid}, ran {int(time.time()-launch_t)}s)")
        except Exception as e:
            _log.debug("hook reap_stale failed: %s", e)
        del _PERIODIC_PIDS[job]


_ZOMBIE_REAP_T = 0.0

def _reap_zombie_tasks():
    """Reclaim RUNNING tasks whose threads are dead (updated_at > 30min ago)."""
    global _ZOMBIE_REAP_T
    if time.time() - _ZOMBIE_REAP_T < 300:
        return
    _ZOMBIE_REAP_T = time.time()
    try:
        running = db.select("tasks", {"select": "id,slug,updated_at,account", "state": "eq.RUNNING",
                                       "limit": "100"}) or []
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)).isoformat()
        reclaimed = 0
        for t in running:
            # COWORK DISPATCH: skip tasks claimed by Cowork sessions — they run in a
            # separate execution context, not as a local subprocess.
            if (t.get("account") or "").startswith("cowork-"):
                continue
            if (t.get("updated_at") or "") < cutoff:
                patch = agentic_repair.repair_patch(
                    t, "zombie-reaper: stale RUNNING >30min",
                    category="orphaned-running",
                    directive="The worker died or stopped updating this RUNNING task. Resume the same task from existing branch/worktree/artifacts, finish the implementation, run checks, and commit.")
                db.update("tasks", {"id": t["id"]}, patch)
                reclaimed += 1
        if reclaimed:
            print(f"[zombie-reaper] reclaimed {reclaimed} stale RUNNING tasks")
    except Exception as e:
        print(f"[zombie-reaper] error: {e}")


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
    _reap_zombie_tasks()
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
            patch = agentic_repair.repair_patch(
                {**t, "remediation_count": tr},
                note,
                category="runner-exception",
                directive="The runner hit a transient technical exception. Resume the same task, preserve prior work, repair the root cause or use provider failover, and finish through build/test/commit.",
                prefer_non_claude=True,
            )
            patch["transient_retries"] = d["transient_retries"]
            set_state(t["id"], **patch)
            time.sleep(min(d["backoff_s"], 20))  # brief in-thread backoff; frees the slot after
            return "requeue"
        set_state(t["id"], state="BLOCKED", note=d["note"], transient_retries=d["transient_retries"])
        return "block"
    except Exception as e:
        _log.debug("hook block_or_retry_fallback failed: %s", e)
        try:
            set_state(t["id"], state="BLOCKED", note=(note or "")[:300])
        except Exception as e:
            _log.debug("hook run_task_safe_log failed: %s", e)
        return "block"


def _touch_progress():
    # WEDGEFIX-B-PROGRESS
    try:
        _pf = os.path.join(os.environ.get("CLAUDE_ORCH_HOME", "."), "runner.progress")
        open(_pf, "a").close()
        os.utime(_pf, None)
    except Exception:
        pass


def _run_task_safe(t):
    """Wrapper so an unhandled exception in run_task can NEVER leave a task stuck in RUNNING
    (which would leak a zombie, drain the queue, and defeat priority ordering). On any failure
    the task is auto-requeued if transient, else marked BLOCKED with the error captured."""
    try:
        run_task(t)
        _touch_progress()  # WEDGEFIX-B-PROGRESS
    except Exception as e:
        try:
            import traceback
            set_state(t["id"], log_tail=traceback.format_exc()[-2000:])
        except Exception as e2:
            _log.debug("hook run_task_safe_log failed: %s", e2)
        _block_or_retry(t, f"runner exception: {e}"[:300])
        try:
            import exec_telemetry
            _crash_tel = exec_telemetry.start(t["id"])
            _crash_tel.finish(outcome="crash", note=f"runner exception: {e}"[:300])
        except Exception:
            pass


_FLEET = {"t": 0.0}  # throttle for the in-loop fleet_control gateway tick


def _ensure_agentic_deps():
    """Cheap-model agentic coding needs the `aider` CLI. If it's missing, the cheap coders silently fail
    and ALL agentic work falls back to Claude — overloading it and stalling the whole fleet the moment
    both Claude accounts hit their limits (exactly what happened). Best-effort self-install so every
    machine provisions the fallback executor on its own. Fail-soft — never blocks startup."""
    import shutil
    for p in ("/opt/homebrew/bin",
              "/usr/local/bin",
              os.path.expanduser("~/.local/bin"),
              os.path.expanduser("~/Library/Python/3.9/bin"),
              os.path.expanduser("~/Library/Python/3.11/bin"),
              os.path.expanduser("~/Library/Python/3.12/bin"),
              "/usr/bin",
              "/bin",
              "/usr/sbin",
              "/sbin"):
        if os.path.isdir(p) and p not in os.environ.get("PATH", ""):
            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
    if shutil.which("aider"):
        print("[deps] aider present — cheap-model agentic fallback available", flush=True)
        return True
    try:
        print("[deps] aider missing — installing cheap-coder executor (aider-chat)…", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", "--quiet", "aider-chat"],
                       capture_output=True, timeout=900)
        ok = bool(shutil.which("aider"))
        print(f"[deps] aider install {'ok' if ok else 'FAILED (cheap agentic unavailable until installed)'}", flush=True)
        return ok
    except Exception as e:
        print(f"[deps] aider install error ({e})", flush=True)
        return False


def main():
    if not _EARLY_SINGLETON_LOCKED and not _acquire_singleton():
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
                except Exception as e:
                    _log.debug("hook billing_firewall failed: %s", e)
        else:
            print(f"[billing-firewall] WARNING: API billing is ALLOWED ({g.get('reason')}). "
                  f"You will be charged API rates. Unset ORCH_ALLOW_API_BILLING to block.")
    except Exception as _e:
        print(f"[billing-firewall] guard failed to load: {_e}")
    _touch_progress()  # WEDGEFIX-C: reset progress mtime at startup so keepalive doesn't
                        # immediately kill a fresh runner due to stale mtime from prior run.
    print(f"runner {RUNNER_ID} online -> {os.environ.get('SUPABASE_URL','(set SUPABASE_URL)')}")
    # FLEET TOPOLOGY: register this runner's capability profile
    try:
        import fleet_topology
        fleet_topology.register_profile()
        _prof = fleet_topology.profile()
        print(f"[fleet-topology] registered: {_prof.get('ram_gb', '?')}GB RAM, "
              f"max_complexity={_prof.get('max_complexity', '?')}, "
              f"tools={','.join(_prof.get('tools', []))}")
    except Exception as e:
        _log.debug("hook fleet_topology.register failed: %s", e)
    # FAST-START: run dependency check + self-check in background threads so the main loop
    # starts claiming tasks within seconds instead of waiting 30-120s for synchronous I/O.
    # Both are fail-soft — they log but never block the runner.
    def _bg_ensure_deps():
        try:
            _ensure_agentic_deps()
        except Exception as _e:
            print(f"[deps] background check failed: {_e}")
    def _bg_selfcheck():
        try:
            import startup_selfcheck
            startup_selfcheck.run(RUNNER_ID)
        except Exception as _e:
            print(f"[self-check] failed: {_e}")
    def _bg_controls():
        try:
            import control_flags
            control_flags.ensure_use_purchased_credits_row(
                os.environ.get("ORCH_USE_PURCHASED_CREDITS", os.environ.get("ORCH_USE_PAID_AGENTIC_CREDITS", "false")).lower()
                in ("1", "true", "yes", "on"))
        except Exception as _e:
            print(f"[controls] purchased-credit flag setup skipped: {_e}")
    threading.Thread(target=_bg_ensure_deps, daemon=True, name="bg-deps").start()
    threading.Thread(target=_bg_selfcheck, daemon=True, name="bg-selfcheck").start()
    threading.Thread(target=_bg_controls, daemon=True, name="bg-controls").start()
    # QUEUE PRE-OPTIMIZATION: start background daemon that pre-computes expensive
    # hook results for QUEUED tasks so they execute faster when claimed.
    try:
        import queue_preopt
        queue_preopt.start()
    except Exception as _e:
        print(f"[queue-preopt] daemon start skipped: {_e}")
    print("[fast-start] deps + self-check + queue-preopt running in background — claiming tasks immediately")
    global _sched_bg_running
    _sched_bg_running = False
    active = []
    # Delay first scheduler tick so tasks get claimed before 60+ periodic jobs run.
    # The scheduler will fire after 120s, giving the runner time to fill lanes first.
    _sched_t = time.time() + 60  # effectively 120s delay (checked at >= 60s elapsed)
    _mem_log_t = 0.0
    _reload_t = 0.0
    _restart_log_t = 0.0
    import resource_governor
    # WARM POOL: eagerly pre-load CLAUDE.md context for active projects
    try:
        if warm_pool:
            _wp_repos = [p.get("repo_path") for p in projects().values() if p.get("repo_path")]
            warm_pool.preload(_wp_repos)
            print(f"[warm-pool] pre-loaded {len(_wp_repos)} repo context(s): {warm_pool.stats()}")
    except Exception as _wp_err:
        print(f"[warm-pool] preload skipped: {_wp_err}")
    print("[main-loop] entering main loop", flush=True)
    try:
        if _fire_periodic("resilience_mesh.py"):
            print("[sched] resilience_mesh.py", flush=True)
    except Exception as e:
        print(f"[sched] resilience_mesh.py error: {e}", flush=True)
    while True:
        active = [th for th in active if th.is_alive()]
        if time.time() - _sched_t >= 60 and not _sched_bg_running:
            _sched_t = time.time()
            def _bg_sched():
                global _sched_bg_running
                try:
                    _scheduler_tick()
                finally:
                    _sched_bg_running = False
            _sched_bg_running = True
            threading.Thread(target=_bg_sched, daemon=True, name="bg-sched").start()
        # HOT RELOAD: pick up changed modules + .env live, so improvements take effect with NO restart.
        if time.time() - _reload_t > 5:
            _reload_t = time.time()
            try:
                import hot_reload
                hot_reload.maybe_reload()
            except Exception as e:
                _log.debug("hook hot_reload failed: %s", e)
        # SELF-DEPLOY: graceful exec-into-new-code when self_deploy requested it (canary-gated)
        # and no tasks are mid-flight; keepalive.sh restarts us into the new commit.
        try:
            _rr = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".restart_requested")
            if os.path.exists(_rr):
                max_active = max(0, int(os.environ.get("ORCH_RESTART_MAX_ACTIVE", "2") or 2))
                if time.time() - _restart_log_t > 30:
                    print(f"[self-deploy] restart requested — draining lanes active={len(active)} threshold={max_active}")
                    _restart_log_t = time.time()
                if len(active) <= max_active:
                    print(f"[self-deploy] restart threshold reached ({len(active)} <= {max_active}) — exiting for keepalive")
                    os.remove(_rr)
                    sys.exit(0)
                # Freeze new claims while waiting to restart so the active count can converge.
                os.environ["ORCH_DRAINING_FOR_RESTART"] = "1"
            else:
                os.environ.pop("ORCH_DRAINING_FOR_RESTART", None)
        except ValueError:
            pass
        except SystemExit:
            raise
        except Exception as e:
            _log.debug("hook self_deploy failed: %s", e)
        try:
            db.heartbeat(RUNNER_ID, socket.gethostname(), len(active))
            # RUNNER REMOTE RESTART: check runner_control table for pending restart commands
            # targeted at this host (or 'all'). Mark handled, release lock, exit (keepalive respawns).
            try:
                _hostname = socket.gethostname()
                _rc_rows = db.select('runner_control', {
                    'select': 'id,target,action',
                    'action': 'eq.restart',
                    'handled_at': 'is.null',
                    'or': f'(target.eq.{_hostname},target.eq.all)',
                    'limit': '1',
                    'order': 'requested_at.asc',
                })
                if _rc_rows:
                    _rc = _rc_rows[0]
                    _log.info('runner_control restart request id=%s target=%s — honoring', _rc['id'], _rc['target'])
                    print(f'[runner-control] restart requested (id={_rc["id"]}, target={_rc["target"]}) — exiting for keepalive')
                    try:
                        db.update('runner_control', {'handled_at': 'now()'}, {'id': f'eq.{_rc["id"]}'})
                    except Exception:
                        pass
                    # Release singleton lock cleanly
                    if _LOCK_FD:
                        try:
                            import fcntl
                            fcntl.flock(_LOCK_FD, fcntl.LOCK_UN)
                            _LOCK_FD.close()
                        except Exception:
                            pass
                    sys.exit(0)
            except SystemExit:
                raise
            except Exception as _rc_err:
                _log.debug('runner_control check failed (fail-soft): %s', _rc_err)
            # FLEET GATEWAY: load central config (fleet_config) + honor control actions (restart / pull)
            # from ONE place, so every Mac converges without a second terminal. In-process so config is
            # live (the loop reads MAX_PARALLEL etc. from env below) and a restart action affects THIS
            # runner. Throttled + fail-soft.
            try:
                import fleet_control
                if time.time() - _FLEET["t"] >= float(os.environ.get("ORCH_FLEET_TICK_S", "60")):
                    _FLEET["t"] = time.time()
                    fleet_control.tick()
            except Exception as e:
                _log.debug("hook fleet_control failed: %s", e)
            # live throttle: the resource governor lowers this under disk/RAM pressure
            # read MAX_PARALLEL live from env each loop so concurrency is tunable via .env + hot_reload
            # WITHOUT a restart (RAM permitting; resource_governor still clamps to protect the Mac).
            eff_limit = min(int(os.environ.get("MAX_PARALLEL", MAX_PARALLEL)), resource_governor.current_limit())
            # COWORK DISPATCH: reduce local lanes when Cowork is actively processing tasks,
            # to avoid git worktree contention. Cowork throughput is 20-180X faster, so yielding
            # local lanes when it's active maximizes total fleet throughput.
            try:
                eff_limit = cowork_dispatch.adjust_local_lanes(eff_limit)
            except Exception:
                pass
            if os.environ.get("ORCH_DRAINING_FOR_RESTART") == "1":
                eff_limit = 0
            # COWORK-ONLY MODE: yield all local claims to Cowork executor sessions.
            # Set ORCH_COWORK_ONLY=1 in .env or fleet_config; runner still orchestrates.
            try:
                _co = os.environ.get("ORCH_COWORK_ONLY", "0")
                if _co != "1":
                    import db as _db2
                    _fc = _db2.select("fleet_config", {"select": "value", "key": "eq.ORCH_COWORK_ONLY"})
                    if _fc and str((_fc[0] or {}).get("value", "")).strip('"') == "1":
                        _co = "1"
                if _co == "1":
                    eff_limit = 0
            except Exception:
                pass
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
                    # CAPACITY PACER: check if we should claim based on token budget pacing
                    _cp_ok = True
                    try:
                        _cp = capacity_pacer.should_claim()
                        if not _cp.get("claim", True):
                            _cp_ok = False
                            if time.time() - _mem_log_t > 120:
                                print(f"[capacity-pacer] holding: {_cp.get('reason','')}")
                                _mem_log_t = time.time()
                    except Exception as e:
                        _log.debug("hook capacity_pacer_claim failed: %s", e)
                    if not _cp_ok:
                        t = None
                        pass  # skip claiming this cycle
                    else:
                        # PARALLEL SWARM DISPATCH: batch-claim + concurrent API dispatch
                        # when conditions are right (enough headroom, budget under cap).
                        # Falls through to serial claim if swarm is disabled or not applicable.
                        t = None
                        _swarm_dispatched = False
                        try:
                            import parallel_dispatch
                            if parallel_dispatch.should_use_swarm(eff_limit, len(active)):
                                _pd_stats = parallel_dispatch.dispatch_swarm_batch(
                                    RUNNER_ID, active, _run_task_safe)
                                if _pd_stats.get("dispatched", 0):
                                    print(f"[swarm-batch] dispatched={_pd_stats['dispatched']} "
                                          f"api={_pd_stats['api_tasks']} cli={_pd_stats['cli_tasks']} "
                                          f"cost=${_pd_stats['cost_usd']:.4f}", flush=True)
                                    _swarm_dispatched = True
                        except Exception as e:
                            _log.debug("hook parallel_dispatch failed: %s", e)
                        if not _swarm_dispatched:
                            t = db.claim_task(RUNNER_ID)
                        _touch_progress()  # WEDGEFIX-B-PROGRESS
                    if t:
                        print(f"[claim] {t.get('slug','')} (project={t.get('project_id','?')[:8]}) active={len(active)+1}/{eff_limit}", flush=True)
                        # REUSE-FIRST: adapt an already-solved implementation instead of rebuilding
                        try:
                            import reuse_first
                            t = reuse_first.pre_claim_hook(t)
                        except Exception as e:
                            _log.debug("hook reuse_first failed: %s", e)
                        try:
                            import patch_transplant
                            t = patch_transplant.pre_claim_hook(t)
                        except Exception as e:
                            _log.debug("hook patch_transplant failed: %s", e)
                        try:
                            import patch_templates
                            t = patch_templates.pre_claim_hook(t)
                        except Exception as e:
                            _log.debug("hook patch_templates failed: %s", e)
                        # PATCH-FIRST RECOVERY: for recovery tasks, try stored patch replay/reflog
                        # before spending tokens on a full agent run (10X-100X cheaper).
                        try:
                            import patch_recovery
                            slug = t.get("slug", "")
                            if slug.startswith("recover-missing-branch-"):
                                _proj = projects(t.get("project_id")).get(t.get("project_id"), {})
                                _repo = _proj.get("repo_path", os.getcwd())
                                _base = _proj.get("default_base") or "main"
                                _rec = patch_recovery.recover(_repo, slug.replace("recover-missing-branch-", ""), _base, project=_proj.get("name"))
                                if _rec.get("ok"):
                                    set_state(t["id"], state="DONE",
                                              note=f"patch-recovery: {_rec['method']} (zero-spend)")
                                    print(f"[patch-recovery] {slug}: recovered via {_rec['method']}")
                                    continue
                        except Exception as e:
                            _log.debug("hook patch_recovery failed: %s", e)
                        th = threading.Thread(target=_run_task_safe, args=(t,), daemon=True)
                        th.start(); active.append(th); continue
                    else:
                        # WORK STEALING: if local queue empty, try stealing from other projects
                        try:
                            import work_stealer
                            _primary_pids = list(projects().keys())
                            if work_stealer.should_steal(RUNNER_ID, _primary_pids):
                                _stolen = work_stealer.steal_task(RUNNER_ID, _primary_pids)
                                if _stolen:
                                    print(f"[work-steal] stolen {_stolen.get('slug','')} from project {_stolen.get('project_id','?')[:8]}", flush=True)
                                    th = threading.Thread(target=_run_task_safe, args=(_stolen,), daemon=True)
                                    th.start(); active.append(th); continue
                        except Exception as e:
                            _log.debug("hook work_stealer failed: %s", e)
                        # PREDICTIVE QUEUE: generate speculative tasks when idle
                        try:
                            import predictive_queue
                            for _pid, _pname in list(projects().items())[:3]:
                                _prepo = _project_repo(_pid)
                                if _prepo:
                                    predictive_queue.generate_speculative_tasks(_pid, _pname, _prepo)
                        except Exception as e:
                            _log.debug("hook predictive_queue failed: %s", e)
                        # PATTERN TRANSFER: scan for cross-project patterns when idle
                        try:
                            import pattern_transfer
                            pattern_transfer.auto_transfer_scan()
                        except Exception as e:
                            _log.debug("hook pattern_transfer failed: %s", e)
                        # PATTERN ADVERSARY: audit patterns when idle
                        try:
                            import pattern_adversary
                            pattern_adversary.audit_all_patterns()
                        except Exception as e:
                            _log.debug("hook pattern_adversary failed: %s", e)
        except Exception as e:
            print("poll error:", e)
        _touch_progress()  # WEDGEFIX-C: unconditional — prevents wedge detection during
                           # capacity-pacer holds, mem-gate holds, or any non-claiming cycle.
        time.sleep(POLL)


if __name__ == "__main__":
    main()
