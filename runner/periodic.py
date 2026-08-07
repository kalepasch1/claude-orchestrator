#!/usr/bin/env python3
from __future__ import annotations
"""
periodic.py - coordinator for all scheduled periodic jobs.
Called by launchd (or manually) with a single job argument.

Jobs:
  spec    - spec drift check across all repos (schedule: weekly)
  chaos   - chaos resilience drills (schedule: weekly, staging only)
  txn     - cross-repo transaction coordinator (schedule: every 5 min)
  scout   - opportunity scout: RICE-scored proposals (schedule: weekly)
  deploy  - canary-gated nightly deploy window (schedule: nightly)
  roi     - update project concurrency_weight from ROI (schedule: daily)
  stuck_reaper - detect+recover RUNNING tasks stuck >2h (schedule: every 30 min)
  priority_scorer - score QUEUED tasks with default priority (schedule: every 10 min)
  quarantine_gc - GC non-recoverable quarantined tasks (schedule: every 6h)

Usage:
  python3 periodic.py spec
  python3 periodic.py txn
"""
import os, sys, subprocess, time, json, socket, urllib.error
# Inherited NODE_ENV=production makes npm omit devDependencies in every child job (staging QA,
# prewarm, merge/release trains) → "Could not load <module>" failures. Strip it (see runner.py).
os.environ.pop("NODE_ENV", None)
try:
    import fcntl
except Exception:
    fcntl = None
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Lazy-load optional modules for periodic jobs
try:
    import editorial_program
except ImportError:
    editorial_program = None
try:
    import adversarial_fleet
except ImportError:
    adversarial_fleet = None
try:
    import fleet_e2e_audit
except ImportError:
    fleet_e2e_audit = None

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RUNTIME = os.path.join(_ROOT, ".runtime")
_PERIODIC_LOCK_DIR = os.path.join(_RUNTIME, "periodic-locks")
if os.environ.get("ORCH_CANONICAL_RUNTIME_HOME", "true").lower() in ("1", "true", "yes", "on"):
    os.environ["CLAUDE_ORCH_HOME"] = _RUNTIME
_TOOL_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    os.path.expanduser("~/.local/bin"),
    os.path.expanduser("~/Library/Python/3.9/bin"),
    os.path.expanduser("~/Library/Python/3.11/bin"),
    os.path.expanduser("~/Library/Python/3.12/bin"),
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)


def _ensure_tool_path():
    path = os.environ.get("PATH", "")
    parts = [p for p in path.split(os.pathsep) if p]
    for p in reversed(_TOOL_PATHS):
        if os.path.isdir(p) and p not in parts:
            parts.insert(0, p)
    os.environ["PATH"] = os.pathsep.join(parts)


# A hung job used to hold its lock forever: every later invocation printed
# "skipped; previous invocation still running" and returned, silently and without bound. On
# 2026-08-02 `remediate` sat wedged for six hours that way, so no remediation ran all afternoon
# while the queue kept growing. Cap how long a holder may keep the lock, then reap it.
_JOB_MAX_RUNTIME_S = int(os.environ.get("ORCH_PERIODIC_JOB_MAX_RUNTIME_S", "3600"))

# A skip is NOT a success. Before this, a job whose predecessor never exited printed
# "previous invocation still running" and exited 0 forever, so launchd, the dashboard and every
# health check saw an unbroken run of green. Three of four jobs no-opped that way during one
# verification pass. That is the same shape as preflight_gate being 100% dead for 19 days: the
# scheduler was reporting success for work that never happened.
#
# So: count CONSECUTIVE skips per job. Past the threshold the job is WEDGED — say so loudly,
# escalate on the crash_loop_detector alerting path, file remediation work, and reap the holder
# regardless of how much of its runtime budget is left.
_WEDGE_SKIPS = int(os.environ.get("ORCH_PERIODIC_WEDGE_SKIPS", "3"))
_SKIP_STATE_PATH = os.path.join(_RUNTIME, "periodic-skips.json")

# Exit codes, so a scheduler/wrapper can tell the three outcomes apart.
_EX_OK = 0
_EX_SKIPPED = 75        # EX_TEMPFAIL: legitimately busy, try again next interval
_EX_WEDGED = 1          # the job has not run for _WEDGE_SKIPS intervals — this is a failure


class _Skipped(object):
    """Sentinel: this invocation did not run the job."""

    def __init__(self, job, reason, wedged=False, skips=0):
        self.job, self.reason, self.wedged, self.skips = job, reason, wedged, skips


def _skip_state():
    try:
        with open(_SKIP_STATE_PATH) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_skip_state(state):
    try:
        os.makedirs(_RUNTIME, exist_ok=True)
        tmp = "%s.%d.tmp" % (_SKIP_STATE_PATH, os.getpid())
        with open(tmp, "w") as fh:
            json.dump(state, fh, indent=2, default=str)
        os.replace(tmp, _SKIP_STATE_PATH)
    except Exception as exc:
        print(f"periodic: could not persist skip state ({exc})")


def _clear_skips(job):
    """This invocation actually acquired the lock, so the job is demonstrably not wedged."""
    state = _skip_state()
    entry = state.get(job) or {}
    if entry.get("consecutive_skips"):
        print(f"periodic {job}: recovered after {entry['consecutive_skips']} consecutive skip(s)")
    state[job] = {"consecutive_skips": 0, "last_run_at": int(time.time())}
    _save_skip_state(state)


def _record_skip(job, pid, age):
    """Count one skip and report whether the job has now crossed into WEDGED."""
    state = _skip_state()
    entry = state.get(job) or {}
    count = int(entry.get("consecutive_skips") or 0) + 1
    entry.update({"consecutive_skips": count, "last_skip_at": int(time.time()),
                  "holder_pid": pid, "holder_age_s": age,
                  "first_skip_at": entry.get("first_skip_at") or int(time.time())})
    state[job] = entry
    _save_skip_state(state)
    return count, entry


def _alert_wedged(job, entry, pid, age):
    """A wedged job is unbounded invisible loss — escalate it like a crash loop.

    Same destinations crash_loop_detector uses (notify + an approvals card) plus a remediation
    task, so "this job has not run in N intervals" surfaces in exactly the place operators
    already look for "this job crashes every time".
    """
    headline = (f"periodic {job}: WEDGED — skipped {entry['consecutive_skips']} consecutive "
                f"invocation(s); holder pid {pid} has held the lock {age}s")
    print(headline, file=sys.stderr, flush=True)
    print(headline, flush=True)
    try:
        import notify
        notify.send(headline[:400])
    except Exception:
        pass
    try:
        db.insert("approvals", {
            "project": "ORCHESTRATOR", "kind": "self", "status": "pending",
            "title": headline[:200],
            "why": (f"periodic.py acquired no lock for '{job}' on "
                    f"{entry['consecutive_skips']} consecutive runs. Every one of those "
                    f"invocations exited 0, so the scheduler reported success for work that "
                    f"never happened.")[:1000],
            "value": "A scheduler that reports success on a skip hides a permanently wedged job "
                     "forever; this is how preflight stayed 100% dead for 19 days.",
            "risk": f"holder pid {pid}, age {age}s, lock {os.path.join(_PERIODIC_LOCK_DIR, job)}.lock",
        })
    except Exception:
        pass
    try:
        import guard_tasks
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_id = ""
        for row in (db.select("projects", {"select": "id,repo_path"}) or []):
            if os.path.abspath(row.get("repo_path") or "") == os.path.abspath(root):
                project_id = row.get("id")
                break
        filer = guard_tasks.Filer("periodic-wedge", max_per_run=3)
        filer.file(project_id, guard_tasks.stable_slug("wedged", job),
                   (f"The periodic job '{job}' is WEDGED: it has been skipped for "
                    f"{entry['consecutive_skips']} consecutive invocations because a previous "
                    f"run never released its singleton lock (holder pid {pid}, held {age}s).\n\n"
                    f"Every skipped invocation exited 0, so nothing downstream noticed.\n\n"
                    f"Find why `JOBS['{job}']()` does not terminate — an unbounded subprocess, a "
                    f"blocking network read with no timeout, or a deadlock. Give it a hard "
                    f"timeout. Reproduce with:\n"
                    f"    cd runner && python3 -c \"import periodic; periodic.JOBS['{job}']()\"\n\n"
                    f"lock file: {os.path.join(_PERIODIC_LOCK_DIR, job)}.lock"),
                   severity=guard_tasks.CRITICAL, project_name="ORCHESTRATOR",
                   title=headline[:200], escalate_why=headline)
    except Exception as exc:
        print(f"periodic {job}: could not file wedge remediation task ({exc})")


def _read_lock_holder(lock_path):
    """Return (pid, started_at) recorded by the current holder, or (None, None)."""
    try:
        with open(lock_path) as fh:
            parts = fh.read().split()
        return int(parts[0]), int(parts[1])
    except Exception:
        return None, None


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _reap_stale_holder(job, lock_path):
    """Kill a lock holder that has outlived _JOB_MAX_RUNTIME_S. Returns True if we cleared it."""
    import signal
    pid, started = _read_lock_holder(lock_path)
    if not pid or not started:
        # Unreadable lock with nobody obviously behind it — let the caller retry once.
        return True
    age = int(time.time()) - started
    if not _pid_alive(pid):
        print(f"periodic {job}: holder pid {pid} is gone; reclaiming lock")
        return True
    if age < _JOB_MAX_RUNTIME_S:
        skips, entry = _record_skip(job, pid, age)
        if skips < _WEDGE_SKIPS:
            print(f"periodic {job}: skipped; previous invocation still running "
                  f"(pid {pid}, {age}s of {_JOB_MAX_RUNTIME_S}s budget) "
                  f"— consecutive skip {skips}/{_WEDGE_SKIPS}")
            return False
        # Threshold crossed. The runtime budget is irrelevant now: whatever the holder is
        # doing, this job has not run for _WEDGE_SKIPS intervals, and that is the failure.
        _alert_wedged(job, entry, pid, age)
        print(f"periodic {job}: reaping the holder so the job can run again")
        return _terminate(job, pid)
    print(f"periodic {job}: HUNG — pid {pid} has held the lock {age}s "
          f"(limit {_JOB_MAX_RUNTIME_S}s); terminating it")
    return _terminate(job, pid)


def _terminate(job, pid):
    """SIGTERM then SIGKILL a lock holder. True once it is gone."""
    import signal
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except OSError:
            break
        for _ in range(50):
            if not _pid_alive(pid):
                return True
            time.sleep(0.1)
    return not _pid_alive(pid)


_TRANSIENT_NET_ERRORS = (
    urllib.error.URLError,
    socket.timeout,
    ConnectionError,       # covers ConnectionReset/Aborted/Refused
    TimeoutError,
)


def _is_transient_net_error(exc):
    """True for errors that mean 'the network was unhappy', not 'the code is wrong'."""
    if isinstance(exc, urllib.error.HTTPError):
        # An HTTP status came back, so we reached the server. 5xx/429 are worth
        # retrying; 4xx is a real client bug and must stay loud.
        return exc.code >= 500 or exc.code == 429
    return isinstance(exc, _TRANSIENT_NET_ERRORS)


def _invoke_job(job):
    """Run a job, converting a permanently-missing table into a disable rather than a crash loop.

    Transient network failures are also absorbed here. Previously only
    MissingRelationError was caught, so a Supabase timeout escaped as an unhandled
    URLError: the job died and wrote a full traceback on EVERY cycle. That is how
    preflight accumulated 4970 tracebacks and quarantine 1642 with zero successful
    runs — all of it the same "urlopen error timed out", none of it a code defect.
    A timeout is not a reason to disable the job (it will likely work next cycle)
    and not a reason to spam a traceback (it hides the jobs that are genuinely
    broken). Log one line and let the next invocation retry.
    """
    try:
        return JOBS[job]()
    except db.MissingRelationError as exc:
        _disable_job(job, str(exc))
        return None
    except Exception as exc:
        if _is_transient_net_error(exc):
            print(f"periodic {job}: skipped; transient network error ({type(exc).__name__}: "
                  f"{exc}). Not a code failure — retrying next cycle.")
            return None
        raise


_DISABLED_JOBS_PATH = os.path.join(_RUNTIME, "disabled_jobs.json")


def _disabled_jobs():
    try:
        with open(_DISABLED_JOBS_PATH) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _disable_job(job, reason):
    """Record a job as structurally broken so it stops running every cycle.

    A job querying a table that does not exist cannot be fixed by running it again. Before this,
    relationship_crm and virtual_executive_worker each retried thousands of times and wrote 17MB
    of identical tracebacks, which is how genuinely broken jobs stayed invisible. Disable the job,
    say so once, and raise an approval so a human actually sees it.
    """
    state = _disabled_jobs()
    if job in state:
        return
    state[job] = {"reason": reason, "disabled_at": int(time.time())}
    try:
        os.makedirs(_RUNTIME, exist_ok=True)
        tmp = "%s.%d.tmp" % (_DISABLED_JOBS_PATH, os.getpid())
        with open(tmp, "w") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, _DISABLED_JOBS_PATH)
    except Exception as exc:
        print(f"periodic {job}: could not persist disable state ({exc})")
    print(f"periodic {job}: DISABLED — {reason}")
    try:
        db.insert("approvals", {
            "project": "", "kind": "job_disabled",
            "title": f"periodic job '{job}' disabled: missing database relation",
            "status": "pending", "detail": reason,
            "risk": "the job cannot run until the table is deployed or the job is retired; "
                    "it is no longer retrying, so nothing else is being masked by its log noise",
        })
    except Exception:
        pass  # never let the escalation path fail the runner


def _run_job_locked(job):
    """Prevent slow periodic jobs from overlapping their next scheduled invocation."""
    disabled = _disabled_jobs().get(job)
    if disabled and os.environ.get("ORCH_RUN_DISABLED_JOBS", "").lower() not in ("1", "true", "yes", "on"):
        print(f"periodic {job}: skipped; disabled — {disabled.get('reason', 'no reason recorded')}. "
              f"Re-enable by removing it from {_DISABLED_JOBS_PATH}")
        return _Skipped(job, "disabled")
    if fcntl is None or os.environ.get("ORCH_PERIODIC_JOB_LOCKS", "true").lower() not in ("1", "true", "yes", "on"):
        _clear_skips(job)
        return _invoke_job(job)
    os.makedirs(_PERIODIC_LOCK_DIR, exist_ok=True)
    lock_path = os.path.join(_PERIODIC_LOCK_DIR, f"{job}.lock")
    with open(lock_path, "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            if not _reap_stale_holder(job, lock_path):
                skips = int((_skip_state().get(job) or {}).get("consecutive_skips") or 0)
                return _Skipped(job, "previous invocation still running",
                                wedged=skips >= _WEDGE_SKIPS, skips=skips)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                print(f"periodic {job}: skipped; lock still held after reaping the stale holder")
                skips = int((_skip_state().get(job) or {}).get("consecutive_skips") or 0)
                return _Skipped(job, "lock still held after reaping",
                                wedged=skips >= _WEDGE_SKIPS, skips=skips)
        lock.seek(0)
        lock.truncate()
        lock.write(f"{os.getpid()} {int(time.time())}\n")
        lock.flush()
        # We hold the lock, so the job is about to actually run: the skip streak is broken.
        _clear_skips(job)
        return _invoke_job(job)


def run_spec():
    import spec as spec_mod
    rows = db.select("projects", {"select": "*"}) or []
    for p in rows:
        repo = p.get("repo_path", "")
        name = p.get("name", "?")
        if not os.path.isdir(repo):
            print(f"spec {name}: repo not found at {repo}")
            continue
        result = spec_mod.check(repo, name, p["id"])
        print(f"spec {name}: {result or 'no SPEC.md'}")


def run_chaos():
    import chaos
    if not os.environ.get("CHAOS_ENABLED", "").lower() == "true":
        print("chaos: CHAOS_ENABLED not set — skipping (safe; set in a staging env only)")
        return
    for drill in ["stale-runner", "fake-fail"]:
        result = chaos.run(drill)
        print(f"chaos {drill}: {result}")
    time.sleep(60)
    _assert_chaos_recovery()


def _assert_chaos_recovery():
    runners = db.select("runner_heartbeats", {"select": "*"}) or []
    chaos_runner = next((r for r in runners if r["runner_id"] == "chaos-drill"), None)
    # Assert: chaos-drill runner is present (injected) with old timestamp (dashboard should show OFFLINE)
    if chaos_runner:
        db.insert("approvals", {
            "project": "CHAOS", "kind": "self",
            "title": "Chaos drill RESULT: stale-runner assertion",
            "why": "chaos-drill runner was injected with a stale timestamp.",
            "value": "PASS — runner was visible; verify dashboard shows it OFFLINE (red dot).",
            "risk": "If green: heartbeat TTL logic is broken.",
            "status": "pending"
        })
        print("chaos assert: stale-runner injection visible — verify dashboard shows it OFFLINE")
    else:
        print("chaos assert: WARN — stale-runner not found in heartbeats")

    chaos_approvals = db.select("approvals", {
        "select": "id", "project": "eq.CHAOS",
        "status": "eq.pending", "limit": "5"
    }) or []
    if chaos_approvals:
        print(f"chaos assert: fake-fail PASS — {len(chaos_approvals)} chaos card(s) in inbox")
    else:
        print("chaos assert: fake-fail WARN — no CHAOS approval in inbox")


def run_txn():
    import transaction
    txns_list = db.select("txns", {"select": "*", "status": "eq.pending"}) or []
    if not txns_list:
        print("txn: no pending transactions")
        return
    for txn in txns_list:
        txn_id = txn["id"]
        result = transaction.resolve(txn_id)
        print(f"txn {txn_id}: {result}")
        if "ready: integrate" in result:
            _ff_merge_txn(txn_id)
        elif "aborted" in result:
            db.update("txns", {"id": txn_id}, {"status": "aborted", "resolved_at": "now()"})


def _ff_merge_txn(txn_id):
    import transaction
    members = transaction.members(txn_id)
    all_ok = True
    for m in members:
        proj_rows = db.select("projects", {"select": "*", "id": f"eq.{m['project_id']}"}) or []
        repo = (proj_rows[0] if proj_rows else {}).get("repo_path", "")
        if not repo or not os.path.isdir(repo):
            continue
        r = subprocess.run(["git", "merge", "--ff-only", f"agent/{m['slug']}"],
                           cwd=repo, capture_output=True)
        if r.returncode != 0:
            all_ok = False
            db.update("tasks", {"id": m["id"]},
                      {"state": "BLOCKED", "note": f"txn:{txn_id} ff-merge failed"})
            print(f"txn {txn_id}: ff-merge FAILED for {m['slug']}")
        else:
            print(f"txn {txn_id}: merged {m['slug']}")
    status = "merged" if all_ok else "aborted"
    db.update("txns", {"id": txn_id}, {"status": status, "resolved_at": "now()"})
    print(f"txn {txn_id}: {status}")


def run_scout():
    import opportunity_scout
    opportunity_scout.run()


def run_deploy():
    import deploy_window
    deploy_window.run()


def run_batch():
    import batch_pass
    batch_pass.run()


def run_unstick():
    """Safety-net sweep (dependency resilience): requeue TRANSIENT-BLOCKED tasks under the retry
    cap so a foundation task that died on a network blip / notional budget cap can never freeze
    its whole dependency subtree again. Terminal blocks (agent/verify/judge/legal) are left alone.
    This automates the manual requeue that was needed to un-jam `tomorrow`."""
    import retry_policy
    import agentic_repair
    limit = int(os.environ.get("UNSTICK_LIMIT", "60"))
    # `prompt`, `attempt`, `log_tail` and `remediation_count` are selected because
    # agentic_repair.repair_patch() needs them: without prompt it cannot tell a real spec from a
    # missing column, without attempt it cannot tell "failed" from "never tried", and without
    # log_tail/remediation_count neither the evidence check nor the repair ceiling can bind.
    blocked = db.select("tasks", {"select": "id,slug,prompt,note,log_tail,attempt,"
                                            "remediation_count,transient_retries,project_id",
                                  "state": "eq.BLOCKED", "limit": str(limit * 3)}) or []
    requeued = terminal = capped = 0
    for t in blocked:
        d = retry_policy.decide(t.get("note") or "", t.get("transient_retries") or 0)
        if d["action"] == "requeue":
            if requeued >= limit:
                break
            patch = agentic_repair.repair_patch(
                t, t.get("note") or "", category="transient", prefer_non_claude=True,
                directive="This task was blocked by a transient/provider/runtime issue. Resume the same task through the selected coder, repair/fail over as needed, and finish it.")
            patch["transient_retries"] = d["transient_retries"]
            db.update("tasks", {"id": t["id"]}, patch)
            requeued += 1
        elif retry_policy.classify(t.get("note") or "") == "transient":
            capped += 1  # transient but over the retry cap -> leave for a human
        else:
            terminal += 1
    print(f"unstick: requeued {requeued} transient-blocked, {capped} over-cap, {terminal} terminal (left alone)")


def run_dagfix():
    """Keep the dependency graph healthy: drop ghost/redundant dep edges, flag true orphans."""
    import dag_optimizer
    dag_optimizer.optimize()


def run_dagspecunblock():
    """Speculatively release tasks waiting only on actively-retrying deps (removes RETRY-wait stalls)."""
    import dag_optimizer
    dag_optimizer.speculative_unblock()


def run_selftune():
    """Outcome-driven autonomy tuning: nudge per-project confidence thresholds from real results."""
    import self_tune
    self_tune.run(apply=True)


def run_batchmech():
    """Fold independent same-repo mechanical tasks into single agent runs (cold-start savings)."""
    import batch_mechanical
    batch_mechanical.apply()


def run_releasetrain():
    """Accumulate agent work on staging, QA it, release to prod (main/master) as a batch."""
    if os.environ.get("AUTOPILOT_RELEASE_TRAIN_ONLY_HOTLANE", "true").lower() in ("1", "true", "yes", "on"):
        print("releasetrain: skipped; hot-lane release_blocker_agent owns release attempts")
        return {"skipped": "hotlane_only"}
    import release_train; release_train.run()


def run_deployverify():
    """Confirm each Vercel prod deploy; auto-rollback to last-good on failure (no downtime)."""
    import deploy_verify; deploy_verify.run()


def run_worktreegc():
    """Remove leftover agent worktrees so branches are free to merge (fixes phantom CONFLICTs)."""
    import worktree_gc; worktree_gc.run()


def run_vercelconfig():
    """Deploy-config coherence: catches vercel.json/package.json/.vercelignore drift a local build cannot."""
    import vercel_config_guard; vercel_config_guard.run()


def run_cleanclone():
    """Pristine git-archive + real install + real build. Catches 'works on my machine' drift."""
    import clean_clone_gate; clean_clone_gate.run()


def run_botcommits():
    """Bot-authored commits must parse. Catches the hisanta class (bot stripped a string escape)."""
    import bot_commit_verifier; bot_commit_verifier.run()


def run_crashloop():
    """Detect modules crashing on every invocation (preflight was 100% dead for 19 days, unnoticed)."""
    import crash_loop_detector; crash_loop_detector.run()


def run_stubguard():
    """Constant-return stubs shadowing real code. Silent: the build is GREEN (tomorrow: 187 symbols)."""
    import stub_guard; stub_guard.run()


def run_divergent():
    """Merges that dropped a symbol because both sides authored the same file (71cfd4ca6)."""
    import divergent_authorship_guard; divergent_authorship_guard.run()


def run_worktreeguard():
    """Pin uncommitted work in every worktree to a rescue ref so no bot can destroy it."""
    import worktree_ownership_guard; worktree_ownership_guard.run()


def run_deploysilence():
    """Projects with ZERO successful production deploys in N days — absence of deploys is invisible."""
    import deploy_silence_detector; deploy_silence_detector.run()


def run_remotegc():
    """GC stale remote agent/* branches (fills gap branch_gc.py doesn't cover)."""
    import workflow_guardrails
    repo_paths = [p.get("repo_path") for p in (db.select("projects", {"select": "repo_path"}) or [])
                  if p.get("repo_path") and os.path.isdir(p["repo_path"])]
    result = workflow_guardrails.periodic_maintenance(repo_paths)
    for repo, r in result.items():
        print(f"  remote_gc {repo}: {r.get('deleted',0)} deleted, dry_run={r.get('dry_run')}", flush=True)


def run_stripe():
    import stripe_revenue; stripe_revenue.run()


def run_ownerreport():
    import owner_report; owner_report.run()


def run_pushdecisions():
    """Fan every new decision/action out to email + Smarter (source-of-truth notifications)."""
    import approval_push
    approval_push.run()


def run_roadmap():
    import roadmap; roadmap.run()


def run_selfheal():
    import self_heal; self_heal.run()


def run_newapp():
    import new_app; new_app.run()


def run_autopilot():
    import autopilot; autopilot.run()


def run_portfolio_autopilot():
    import portfolio_autopilot; portfolio_autopilot.run()


def run_abedge():
    import ab_edge; ab_edge.run()


def run_objective():
    """Meta-controller: measure the north-star and tune one knob toward it (revert regressions)."""
    import objective_optimizer; objective_optimizer.run()


def run_credential_resolver():
    """Auto-resolve credential_requests stuck at status=manual by checking runner env for available keys."""
    import credential_auto_resolver; credential_auto_resolver.resolve_pending()


def run_stuck_reaper():
    """Detect RUNNING tasks that haven't updated in hours (crashed/hung) and reset or quarantine them."""
    import stuck_reaper; stuck_reaper.run()


def run_remediate():
    """Drive BLOCKED to zero: requeue transient/conflict, escalate+sharpen review/no-op fails, human-card the rest."""
    import auto_remediate; auto_remediate.run()


def run_quarantine():
    """Park terminal blockers and queue safe local/value reworks so the backlog keeps draining."""
    import blocker_quarantine; blocker_quarantine.run()


def run_selfcheck():
    """Assert + auto-heal core invariants; post a health line."""
    import startup_selfcheck; startup_selfcheck.run("periodic")


def run_improve():
    """Measured self-improvement: detect a real bottleneck, propose against a baseline+target."""
    import improvement_miner; improvement_miner.run()


def run_bottlenecks():
    """Measure the pipeline's own bottlenecks and rank them by arithmetic headroom."""
    import bottleneck_detector; bottleneck_detector.run()


def run_gateliveness():
    """Alarm on any gate that has gone degenerate or silent (the 18-day-outage detector)."""
    import gate_liveness; gate_liveness.run()


def run_improvesettle():
    """Close due measurement windows: validate against baseline, or revert and mark regressed."""
    import improvement_verify; improvement_verify.run()


def run_improvemeasure():
    """Learn which KINDS of improvements actually pay off; bias future mining toward them."""
    import improvement_measure; improvement_measure.run()


def run_cadeextras():
    """Auto-discover and run all cx_*.py extra modules."""
    import cade_extras; cade_extras.run()


def run_committees():
    """Convene expert committees (Legal, BizDev/Marketing, Finance, Product, Security, Growth, Risk)
    on business-model proposals + legal/strategic decisions."""
    import committees; committees.run()


def run_committeecal():
    """Committee memory: reweight committees + individual seats by how well past verdicts predicted outcomes."""
    import committees; committees.calibrate()


def run_committeedocket():
    """Continuous docket: committees proactively re-review shipped features and act when evidence has moved."""
    import committees; committees.docket()


def run_committeerollout():
    """Staged rollout controller: advance healthy canaries (canary->ramp->full) and auto-rollback regressions."""
    import committees; committees.rollout_advance(); committees.conclude_experiments()


def run_committeeboard():
    """Portfolio bandit: continuously shift build effort toward the highest realized-reward app (with
    exploration), and mine fresh experiment hypotheses so the A/B pipeline never runs dry."""
    import committees; committees.board_bandit(); committees.mine_hypotheses()


def run_committeekg():
    """Cross-committee knowledge graph: index opinions/precedents/dissents so panels can pull related priors."""
    import committees; committees.build_kg()


def run_committeemeta():
    """Meta-committee: review the committee system itself and recalibrate autonomously; log structural ideas."""
    import committees; committees.meta_review()


def run_committeewatch():
    """Event-driven watch: scan external reg/security/competitor signals and re-open the docket on material ones."""
    import committees; committees.watch_scan()


def run_committeeminutes():
    """Plain-English board minutes so the owner can skim the whole autonomous operation in 60 seconds."""
    import committees; committees.board_minutes()


def run_committeedigest():
    """Weekly owner brief of the sharpest committee dissents, reversals, and least-confident calls."""
    import committees; committees.dissent_digest()


def run_decisionbriefs():
    """Generate war-room/negotiation-grade briefs for new legal/strategic decisions."""
    import decision_engine; decision_engine.run()


def run_legaltriage():
    """Classify legal cards routine/elevated/novel; auto-clear routine (if enabled), escalate novel."""
    import legal_triage
    legal_triage.run()


def run_revattr():
    """Snapshot revenue + attribute merges to revenue movement (which work pays off)."""
    import revenue_attribution
    revenue_attribution.run()


def run_specwriter():
    """Each app self-writes SPEC.md from merged outcomes + usage (compounding plan quality)."""
    import spec_writer
    spec_writer.run()


def run_autoexec():
    """Auto-run the safe majority of proven operator steps (no click), plus execute queued ones."""
    import action_runner
    action_runner.auto_execute()
    action_runner.run()


def run_draftactions():
    """Pre-generate exact command/steps for each operator/credential to-do (review + run one line)."""
    import action_drafter
    action_drafter.run()


def run_prebrief():
    """Attach a plain-English legal decision brief to each legal card."""
    import legal_prebrief
    legal_prebrief.run()


def run_bizradar():
    """Flag queued work that would change pricing/data-use/regulatory posture as an early decision."""
    import business_radar
    business_radar.run()


def run_actionexec():
    """Execute ONLY the safe, you-clicked operator steps queued from the cockpit."""
    import action_runner
    action_runner.run()


def run_mergetrain():
    """Batch non-overlapping judge-passed branches into one green CI run and merge the train."""
    import merge_train
    merge_train.run()


def run_forecast():
    """Project end-of-day spend from burn rate; pause on real-$ runaway, alert on notional spike."""
    import spend_forecast
    spend_forecast.run()


def run_arbitrage():
    """Rebalance provider routing to the cheapest capable frontier as prices/quality move."""
    import price_arbitrage
    price_arbitrage.run()


def run_autoscale():
    """Emit scale up/down signal when weighted demand diverges from live fleet capacity."""
    import autoscale_signal
    autoscale_signal.run()


def run_learnmerges():
    """Reinforcement from shipped work: distill merged diffs into conventions + regression rules."""
    import learn_from_merges
    learn_from_merges.run()


def run_promptfactory():
    """Objective -> intake DAG, with no operator in the loop after the objective is stated.
    Gated by drain_policy like other generators, and by prompt_factory's own ORCH_FACTORY_MAX_OPEN
    cap so a slow-draining fleet doesn't get buried in generated work."""
    import prompt_factory
    result = prompt_factory.run()
    print(f"promptfactory: {result}")


def run_embedretry():
    """Drain the knowledge_embed retry queue: texts that hit a 429/circuit-open and had no local
    Ollama fallback get another shot at real semantic embedding, with backoff between ticks
    (not within a call) so a throttled provider degrades to 'embedded later', not 'never'."""
    import knowledge_embed
    result = knowledge_embed.retry_queue_flush()
    print(f"embedretry: {result}")


def run_dedup():
    """Collapse near-duplicate queued tasks so the swarm solves each thing once."""
    import task_dedup
    task_dedup.apply()
    # Second pass: embedding-similarity dedupe catches paraphrased duplicates that
    # slug/title matching misses. Capped per run; fail-soft.
    try:
        import db
        import semantic_dedupe
        import knowledge_embed

        def _batch_embed(texts):
            return [knowledge_embed.embed(t) for t in texts]

        def _mark(keeper, dup, sim):
            db.update("tasks", {"id": dup["id"]}, {
                "state": "QUARANTINED",
                "note": f"semantic-dedupe: {sim:.3f} duplicate of {keeper.get('slug','')[:60]}",
            })

        cap = int(os.environ.get("ORCH_SEMDEDUPE_BATCH", "200"))
        tasks = db.select("tasks", {
            "select": "id,slug,prompt,project_id",
            "state": "eq.QUEUED",
            "order": "created_at.asc",
            "limit": str(cap),
        }) or []
        if len(tasks) >= 2:
            n = semantic_dedupe.dedupe_queued(tasks, _batch_embed, mark_fn=_mark)
            if n:
                print(f"semantic-dedupe: quarantined {n} paraphrase duplicates")
    except Exception as e:
        print(f"semantic-dedupe skipped: {e}")


def run_conflictresolve():
    """Zero-token conflict/branch recovery: auto-rebase + serialize + branch rebuild."""
    import conflict_auto_resolve
    n = conflict_auto_resolve.run()
    if n:
        print(f"conflict_auto_resolve: recovered {n} blocked tasks")


def run_contcompact():
    """Collapse low-signal cont-* shards into a few consolidated continuation tasks."""
    import continuation_compactor
    continuation_compactor.run()


def run_backlogcompact():
    """Collapse stale broad queued work into project-level backlog batches."""
    import backlog_compactor
    backlog_compactor.run()


def run_canaryecon():
    """Promote/rollback canaries on live production cost + quality."""
    import canary_economics
    canary_economics.run()


def run_billingguard():
    """Tripwire: pause everything if any real API spend or leaked key appears (anti-$500-invoice)."""
    import billing_guard
    billing_guard.run()


def run_governor():
    """Allocate fleet capacity across apps by expected value (ROI x success / cost)."""
    import portfolio_governor
    portfolio_governor.run(apply=True)


def run_costslo():
    """Hold each app's $/merge SLO by biasing routing cheaper; escalate on hard breach."""
    import cost_slo
    cost_slo.run(apply=True)


def run_promote():
    """Propose productizing capabilities proven across multiple apps."""
    import capability_promote
    capability_promote.run(apply=True)


def run_prewarm():
    """Pre-create worktrees + warm context for the next claimable tasks (zero claim latency)."""
    import prewarm
    prewarm.run()


def run_appreview():
    """Perpetual cross-app AI/API triage review: rate cost/quality, learn cheapest good route."""
    import app_triage_review
    app_triage_review.run()


def run_preflight():
    """Cheap-model triage for queued tasks before spending agentic coder time."""
    import preflight_gate
    preflight_gate.run()


def run_agentmarket():
    """Role-aware cross-app model mesh: bids, settlement functions, and app-specific implementation batches."""
    import agent_market
    agent_market.run()


def run_promptbankruptcy():
    """Detect losing prompt patterns and force restructuring instead of expensive retries."""
    import prompt_bankruptcy
    prompt_bankruptcy.run()


def run_modelportfolios():
    """Refresh per-domain model champions by merge yield and cost."""
    import model_portfolios
    model_portfolios.run()


def run_modelslashing():
    """Summarize model/vendor penalties that lower future allocation share."""
    import model_slashing
    model_slashing.run()


def run_commonbrain():
    """Deployable common brain: CADE + agent market + proof + outcome flywheel recipes for each app."""
    import common_brain
    common_brain.run()

def run_relationshipcrm():
    """Prepare CRM facts/recommendations. Provider delivery is never called here."""
    import relationship_crm
    relationship_crm.run()


def run_priority_scorer():
    """Score QUEUED tasks with default priority=1000 based on kind, slug, deps, and age."""
    import priority_scorer
    priority_scorer.run()


def run_rtmon():
    """Realtime approval monitor polling fallback (every 5 min)."""
    import realtime_approval_monitor
    realtime_approval_monitor.run()


def run_quarantine_gc():
    """GC non-recoverable quarantined tasks (PATCH TEMPLATE, dedup) to reduce scan noise."""
    import quarantine_gc
    quarantine_gc.run()


def run_cluster():
    """Cluster pending approval cards so the human can bulk-approve siblings."""
    import approval_cluster
    approval_cluster.tag()


def run_conventions():
    """Refresh each repo's CLAUDE.md (compounding caching + on-style, cheaper builds)."""
    import synthesize_conventions
    for p in db.select("projects", {"select": "name,repo_path"}) or []:
        repo = p.get("repo_path", "")
        if repo and os.path.isdir(repo):
            try:
                synthesize_conventions.run(repo)
            except Exception as e:
                print(f"conventions {p.get('name')}: {e}")


def run_roi():
    import roi
    report = roi.report()
    if not report:
        return
    max_cpm = max((r["cost_per_merge"] or 0) for r in report if r["cost_per_merge"]) or 1
    for r in report:
        cpm = r["cost_per_merge"]
        if cpm is None:
            weight = 1
        elif cpm <= max_cpm * 0.25:
            weight = 3  # high-ROI: more concurrency
        elif cpm <= max_cpm * 0.6:
            weight = 2
        else:
            weight = 1  # low-ROI: baseline only
        rows = db.select("projects", {"select": "id", "name": f"eq.{r['project']}"}) or []
        if rows:
            db.update("projects", {"id": rows[0]["id"]}, {"concurrency_weight": weight})
        print(f"roi {r['project']}: cpm=${cpm} weight={weight}")


def run_nightsweep():
    """Batch mechanical/doc/test tasks to cheapest providers during off-peak hours."""
    import nightly_cheap_sweep
    nightly_cheap_sweep.run()


def run_editorial():
    """Execute editorial program: generate drafts, schedule briefings, and manage editorial calendar."""
    if editorial_program is None:
        raise ImportError("editorial_program module not available")
    editorial_program.run()


def run_adversarial_fleet():
    """Run adversarial fleet stress tests and resilience checks across all orchestrator agents."""
    if adversarial_fleet is None:
        raise ImportError("adversarial_fleet module not available")
    adversarial_fleet.run()


def run_fleet_e2e_audit():
    """End-to-end audit of fleet health: deployment, integration, and correctness verification."""
    if fleet_e2e_audit is None:
        raise ImportError("fleet_e2e_audit module not available")
    fleet_e2e_audit.run()


def run_deployterminal():
    """Promote verified releases' tasks to DEPLOYED_AND_VERIFIED; report red (back-pressured) projects."""
    import deployment_terminal; return deployment_terminal.run()


def run_shipped():
    """owner_goals #2 telemetry: improvements actually shipped to production per day, per app."""
    import shipped_metrics; return shipped_metrics.run()


JOBS = {
    "deployterminal": run_deployterminal,
    "shipped": run_shipped,
    "spec": run_spec,
    "chaos": run_chaos,
    "txn": run_txn,
    "scout": run_scout,
    "deploy": run_deploy,
    "roi": run_roi,
    "editorial": run_editorial,
    "adversarial_fleet": run_adversarial_fleet,
    "fleet_e2e_audit": run_fleet_e2e_audit,
    "batch": run_batch,
    "unstick": run_unstick,
    "dagfix": run_dagfix,
    "dagspecunblock": run_dagspecunblock,
    "selftune": run_selftune,
    "batchmech": run_batchmech,
    "appreview": run_appreview,
    "cluster": run_cluster,
    "conventions": run_conventions,
    "governor": run_governor,
    "costslo": run_costslo,
    "promote": run_promote,
    "prewarm": run_prewarm,
    "billingguard": run_billingguard,
    "learnmerges": run_learnmerges,
    "promptfactory": run_promptfactory,
    "embedretry": run_embedretry,
    "dedup": run_dedup,
    "conflictresolve": run_conflictresolve,
    "contcompact": run_contcompact,
    "backlogcompact": run_backlogcompact,
    "canaryecon": run_canaryecon,
    "forecast": run_forecast,
    "arbitrage": run_arbitrage,
    "autoscale": run_autoscale,
    "mergetrain": run_mergetrain,
    "draftactions": run_draftactions,
    "prebrief": run_prebrief,
    "bizradar": run_bizradar,
    "actionexec": run_actionexec,
    "legaltriage": run_legaltriage,
    "decisionbriefs": run_decisionbriefs,
    "improve": run_improve,
    "bottlenecks": run_bottlenecks,
    "gateliveness": run_gateliveness,
    "improvesettle": run_improvesettle,
    "improvemeasure": run_improvemeasure,
    "cadeextras": run_cadeextras,
    "committees": run_committees,
    "committeecal": run_committeecal,
    "committeedocket": run_committeedocket,
    "committeedigest": run_committeedigest,
    "committeerollout": run_committeerollout,
    "committeeboard": run_committeeboard,
    "committeewatch": run_committeewatch,
    "committeeminutes": run_committeeminutes,
    "committeekg": run_committeekg,
    "committeemeta": run_committeemeta,
    "cadeextras": run_cadeextras,
    "credresolver": run_credential_resolver,
    "stuck_reaper": run_stuck_reaper,
    "remediate": run_remediate,
    "quarantine": run_quarantine,
    "selfcheck": run_selfcheck,
    "objective": run_objective,
    "revattr": run_revattr,
    "specwriter": run_specwriter,
    "autoexec": run_autoexec,
    "pushdecisions": run_pushdecisions,
    "roadmap": run_roadmap,
    "selfheal": run_selfheal,
    "newapp": run_newapp,
    "autopilot": run_autopilot,
    "abedge": run_abedge,
    "stripe": run_stripe,
    "ownerreport": run_ownerreport,
    "worktreegc": run_worktreegc,
    "vercelconfig": run_vercelconfig,
    "cleanclone": run_cleanclone,
    "botcommits": run_botcommits,
    "crashloop": run_crashloop,
    "stubguard": run_stubguard,
    "divergent": run_divergent,
    "worktreeguard": run_worktreeguard,
    "deploysilence": run_deploysilence,
    "remotegc": run_remotegc,
    "releasetrain": run_releasetrain,
    "deployverify": run_deployverify,
    "preflight": run_preflight,
    "agentmarket": run_agentmarket,
    "promptbankruptcy": run_promptbankruptcy,
    "modelportfolios": run_modelportfolios,
    "modelslashing": run_modelslashing,
    "commonbrain": run_commonbrain,
    "relationshipcrm": run_relationshipcrm,
    "priority_scorer": run_priority_scorer,
    "quarantine_gc": run_quarantine_gc,
    "portfolioautopilot": run_portfolio_autopilot,
}

if __name__ == "__main__":
    _ensure_tool_path()
    job = sys.argv[1] if len(sys.argv) > 1 else "help"
    if job not in JOBS:
        print(f"usage: periodic.py {'|'.join(JOBS)}")
        sys.exit(1)
    try:
        import drain_policy
        reason = drain_policy.skip_reason(job)
        if reason:
            print(f"periodic {job}: skipped ({reason}; draining backlog first)")
            sys.exit(0)
    except Exception as e:
        print(f"periodic {job}: drain policy unavailable ({e})")
    # honor the kill switch: model-spending jobs don't run while paused.
    # these only read outcomes / move task state / edit thresholds — they never spend tokens
    _SAFE_WHEN_PAUSED = {
        "resource_governor.py", "usage_meter.py", "anomaly.py", "roi", "txn",
        "approval_policy.py", "queue_janitor.py", "unstick", "dagfix", "batchmech",
        "selftune", "cluster", "governor", "costslo", "promote", "prewarm",
        "billingguard", "dedup", "conflictresolve", "canaryecon", "forecast", "arbitrage", "autoscale",
        "contcompact", "backlogcompact",
        "bizradar", "pushdecisions", "selfheal", "newapp", "autopilot", "abedge",
        "stripe", "ownerreport", "worktreegc", "stuck_reaper", "remediate", "selfcheck",
        "quarantine", "credresolver", "agentmarket", "promptbankruptcy", "modelportfolios", "modelslashing", "commonbrain", "remotegc",
        "priority_scorer", "quarantine_gc",
        "relationshipcrm",
        "release_kpi.py", "integrate_kpi.py", "fleet_control.py",
    }
    if job not in _SAFE_WHEN_PAUSED:
        try:
            import kill_switch
            if kill_switch.is_paused():
                print(f"periodic {job}: skipped (paused)")
                sys.exit(0)
        except Exception:
            pass
    outcome = _run_job_locked(job)
    # rc 0 = the job ran. rc 75 = legitimately busy, retry next interval. rc 1 = WEDGED.
    # Returning 0 for a skip is what let three of four jobs no-op through a verification pass
    # while every caller recorded success.
    if isinstance(outcome, _Skipped):
        if outcome.wedged:
            print(f"periodic {job}: exiting {_EX_WEDGED} — WEDGED ({outcome.skips} consecutive "
                  f"skips, reason: {outcome.reason})", file=sys.stderr, flush=True)
            sys.exit(_EX_WEDGED)
        sys.exit(_EX_SKIPPED)
    sys.exit(_EX_OK)
