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
import os, sys, datetime, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_DIR = os.path.dirname(os.path.abspath(__file__))
RESTART_FLAG = os.path.join(_DIR, ".restart_requested")
BOOT_FILE = ".runner_boot_commit"
BLOCK_TITLE = "Self-deploy blocked: tests failing on master"
CANARY_TIMEOUT = 300


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


def check_new_code(repo):
    run_c, head = running_commit(repo), current_commit(repo)
    return {"running_commit": run_c, "head_commit": head,
            "stale": bool(run_c and head and run_c != head)}


def _pytest_timeout_available():
    try:
        r = subprocess.run(["python3", "-c", "import pytest_timeout"],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def canary_gate(repo):
    """True iff the fast test suite passes on the current checkout."""
    cmd = ["python3", "-m", "pytest", "runner/tests", "-q", "-x"]
    if _pytest_timeout_available():
        cmd.append("--timeout=120")
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                           timeout=CANARY_TIMEOUT)
        return r.returncode == 0
    except Exception as e:
        print(f"self_deploy: canary run failed ({e})")
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
