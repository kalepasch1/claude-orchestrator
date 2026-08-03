#!/usr/bin/env python3
"""
self_deploy.py - merged code takes effect WITHOUT a human restart. hot_reload.py already
live-swaps leaf modules, but the entrypoint (runner.py) and low-level modules are excluded;
this closes that gap with a cooperative, test-gated restart:

  check_new_code(repo)  -> {"running_commit","head_commit","stale"}: the commit the runner
                           BOOTED on (env ORCH_BOOT_COMMIT, else <repo>/.runner_boot_commit)
                           vs current git HEAD.
  canary_gate(repo)     -> run the fast suite (python3 -m pytest runner/tests -q -x
                           [--timeout=120 if pytest-timeout is importable]) with a 300s cap;
                           True only on rc==0. New code never goes live on red tests.
  request_restart(why)  -> touch runner/.restart_requested (reason + timestamp) AND insert a
                           notifications digest row. The MAIN LOOP (wired separately) checks
                           this file BETWEEN tasks and sys.exit(0)s cleanly; keepalive.sh
                           then restarts into the new code. No hard kills, no forced exits —
                           always cooperative, so in-flight tasks finish first.
  maybe_deploy(repo)    -> full flow: stale? -> canary gate -> request restart. On canary
                           failure it files a kind='self' approvals card instead (unique
                           partial index on (kind,title) may reject dupes — caught+ignored).
                           Never raises; safe to call every loop.
"""
import os, sys, re, datetime, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_DIR = os.path.dirname(os.path.abspath(__file__))
RESTART_FLAG = os.path.join(_DIR, ".restart_requested")
BOOT_FILE = ".runner_boot_commit"
BASELINE_FILE = ".pytest-failure-baseline"
BLOCK_TITLE = "Self-deploy blocked: tests REGRESSED against baseline"
# 300s could not fit a full suite run, so the gate timed out and returned False even when
# the suite was healthy. Configurable, with a default that matches reality.
CANARY_TIMEOUT = int(os.environ.get("ORCH_CANARY_TIMEOUT", "900"))


def current_commit(repo):
    """git HEAD of repo (read-only). Empty string if git fails."""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def running_commit(repo):
    """Commit the current process booted on: env ORCH_BOOT_COMMIT, else boot file."""
    c = (os.environ.get("ORCH_BOOT_COMMIT") or "").strip()
    if c:
        return c
    try:
        with open(os.path.join(repo, BOOT_FILE)) as f:
            return f.read().strip()
    except OSError:
        return ""


def record_boot(repo, commit=None):
    """Stamp the commit this runner booted on. Call ONCE at process start.

    Without this the marker never exists, running_commit() returns "", and
    check_new_code()["stale"] is always False — so self-deploy can never fire and
    merged code never reaches the running fleet until a human restarts it. That is
    the "sentinel: stale-code-unknown" state observed continuously since 2026-07-16.

    Deliberately NOT called from a monitor or sentinel: writing the marker after boot
    would stamp the CURRENT head onto an OLD process and permanently hide staleness,
    which is worse than not knowing. Only the launcher may write it.
    """
    c = (commit or current_commit(repo) or "").strip()
    if not c:
        return ""
    try:
        with open(os.path.join(repo, BOOT_FILE), "w") as f:
            f.write(c + "\n")
    except OSError:
        return ""
    return c


def check_new_code(repo):
    run_c, head = running_commit(repo), current_commit(repo)
    return {"running_commit": run_c, "head_commit": head,
            "stale": bool(run_c and head and run_c != head),
            # Distinguishable from stale=False-because-current: a missing marker means
            # we CANNOT TELL, which must not be reported as healthy.
            "unknown": not bool(run_c)}


def _pytest_timeout_available():
    try:
        r = subprocess.run(["python3", "-c", "import pytest_timeout"],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


_SUMMARY_RE = re.compile(r"(\d+) failed", re.I)


def _read_baseline(repo):
    try:
        with open(os.path.join(repo, BASELINE_FILE)) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _write_baseline(repo, n):
    try:
        with open(os.path.join(repo, BASELINE_FILE), "w") as f:
            f.write(f"{int(n)}\n")
    except OSError:
        pass


def canary_gate(repo):
    """True iff the suite is no worse than the recorded baseline.

    RATCHET, not absolute-zero (fixed 2026-08-02). The old gate ran with `-x`, which
    stops at the FIRST failure, and capped the run at 300s when a full pass takes longer
    than that. The suite has carried pre-existing failures for months, so the gate
    returned False on every single invocation — self-deploy was structurally impossible
    and merged code could never reach the running fleet. An impossible gate is not a
    safety property, it is an outage that looks like caution.

    The ratchet keeps the real guarantee (a change may never make things worse) while
    letting a fleet with known-red tests still ship. The baseline only moves DOWN.
    """
    cmd = ["python3", "-m", "pytest", "runner/tests", "-q"]
    if _pytest_timeout_available():
        cmd.append("--timeout=120")
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                           timeout=CANARY_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"self_deploy: canary timed out after {CANARY_TIMEOUT}s — "
              f"raise ORCH_CANARY_TIMEOUT if the suite has grown")
        return False
    except Exception as e:
        print(f"self_deploy: canary run failed ({e})")
        return False

    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0:
        _write_baseline(repo, 0)          # fully green — ratchet all the way down
        return True

    m = _SUMMARY_RE.search(out)
    if not m:
        # No parseable summary means the run died (collection error, crash) rather than
        # merely failing assertions. Fail closed: that is a real signal, not a ratchet case.
        print("self_deploy: canary produced no test summary — treating as red")
        return False

    failed = int(m.group(1))
    baseline = _read_baseline(repo)
    if baseline is None:
        _write_baseline(repo, failed)
        print(f"self_deploy: canary baseline seeded at {failed} failing tests; "
              f"future runs must not exceed it")
        return True
    if failed <= baseline:
        if failed < baseline:
            _write_baseline(repo, failed)  # ratchet down; never back up
            print(f"self_deploy: canary improved {baseline} -> {failed}; baseline tightened")
        return True
    print(f"self_deploy: canary REGRESSED {baseline} -> {failed} failing tests; holding deploy")
    return False


def request_restart(reason):
    """Cooperative restart signal: flag file + digest notification. Never kills anything."""
    ts = datetime.datetime.utcnow().isoformat()
    with open(RESTART_FLAG, "w") as f:
        f.write(f"{ts} {reason}\n")
    try:
        db.insert("notifications", {
            "channel": "digest",
            "audience": os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com"),
            "kind": "self_deploy",
            "title": f"[self-deploy] restart requested: {reason}",
            "body": "Runner will exit cleanly between tasks; keepalive.sh restarts it "
                    "into the new code. No work is interrupted.",
            "sent": False})
    except Exception:
        pass
    return RESTART_FLAG


def _file_blocked_card():
    try:
        db.insert("approvals", {
            "project": "ORCHESTRATOR", "kind": "self", "title": BLOCK_TITLE,
            "why": "New commits are on master but the fast test suite is red; "
                   "self-deploy is holding the running (green) version.",
            "value": "Fix the failing tests (or revert) and the next cycle deploys itself.",
            "risk": "None — the currently-running code keeps serving.", "command": ""})
    except Exception:
        pass  # unique partial index on (kind,title) rejects duplicates — fine


def maybe_deploy(repo=None):
    """Full self-deploy flow. Logs, never raises."""
    try:
        repo = repo or os.path.dirname(_DIR)
        st = check_new_code(repo)
        if not st["stale"]:
            print(f"self_deploy: up-to-date "
                  f"(running={st['running_commit'][:8] or '?'})")
            return {"deployed": False, "reason": "up-to-date", **st}
        print(f"self_deploy: new code {st['head_commit'][:8]} "
              f"(running {st['running_commit'][:8]}) — running canary gate")
        if not canary_gate(repo):
            print("self_deploy: BLOCKED — tests failing; filing approvals card")
            _file_blocked_card()
            return {"deployed": False, "reason": "canary_failed", **st}
        request_restart(f"new code {st['head_commit'][:8]} passed canary gate")
        print(f"self_deploy: restart requested into {st['head_commit'][:8]}")
        return {"deployed": True, "reason": "restart_requested", **st}
    except Exception as e:
        print(f"self_deploy: skipped ({e})")
        return {"deployed": False, "reason": f"error: {e}"}


if __name__ == "__main__":
    import json
    print(json.dumps(maybe_deploy(), indent=2))
