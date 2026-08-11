#!/usr/bin/env python3
"""
self_deploy.py - merged code takes effect WITHOUT a human restart. hot_reload.py already
live-swaps leaf modules, but the entrypoint (runner.py) and low-level modules are excluded;
this closes that gap with a cooperative, test-gated restart:

  check_new_code(repo)  -> {"running_commit","head_commit","stale"}: the commit the runner
                           BOOTED on (env ORCH_BOOT_COMMIT, else <repo>/.runner_boot_commit)
                           vs current git HEAD.
  canary_gate(repo)     -> compile the runner, collect the complete test suite, then run a
                           bounded critical + change-matched test set. True only when every
                           stage exits 0. This keeps the restart gate passable as the full
                           suite grows while still failing closed on syntax, collection and
                           relevant behavioral regressions.
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
import glob, os, sys, datetime, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_DIR = os.path.dirname(os.path.abspath(__file__))
RESTART_FLAG = os.path.join(_DIR, ".restart_requested")
BOOT_FILE = ".runner_boot_commit"
BLOCK_TITLE = "Self-deploy blocked: bounded release canary failed"
# The old gate ran all 8,599+ tests under one fixed timeout. It first failed during
# collection, then (after collection was repaired) simply timed out after 900 seconds.
# A restart safety check must be bounded independently of total suite size.
CANARY_TIMEOUT = int(os.environ.get("ORCH_CANARY_TIMEOUT", "300"))
CANARY_COLLECTION_TIMEOUT = int(os.environ.get("ORCH_CANARY_COLLECTION_TIMEOUT", "180"))
CANARY_MAX_CHANGED_TESTS = int(os.environ.get("ORCH_CANARY_MAX_CHANGED_TESTS", "60"))

# These protect the exact path that turns merged code into running code, plus the release
# truth/terminal-state fixes that prevent "merged" from being mistaken for "visible".
CRITICAL_CANARY_TESTS = (
    "runner/tests/test_self_deploy.py",
    "runner/tests/test_self_deploy_canary.py",
    "runner/tests/test_self_deploy_boot_marker.py",
    "runner/tests/test_all_modules_importable.py",
    "runner/tests/test_runner_core.py",
    "runner/tests/test_integration_sweeper.py",
    "runner/tests/test_merge_truth.py",
    "runner/tests/test_phantom_recovery.py",
    "runner/tests/test_production_push_guard.py",
    "runner/tests/test_release_manifest_binding.py",
    "runner/tests/test_release_push_fast_forward.py",
)


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


def _changed_files(repo, base_commit, head_commit="HEAD"):
    """Return paths changed across the boot-to-head boundary, or None on git failure."""
    if not base_commit:
        return None
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMRT", base_commit, head_commit],
            cwd=repo, capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return [line.strip() for line in (r.stdout or "").splitlines() if line.strip()]


def _selected_tests(repo, changed_files):
    """Critical smoke tests plus tests directly changed by, or named for, changed modules."""
    selected = {p for p in CRITICAL_CANARY_TESTS if os.path.isfile(os.path.join(repo, p))}
    for rel in changed_files or ():
        if not rel.startswith("runner/") or not rel.endswith(".py"):
            continue
        base = os.path.basename(rel)
        if base.startswith("test_") and os.path.isfile(os.path.join(repo, rel)):
            selected.add(rel)
        if base.startswith("test_"):
            continue
        stem = os.path.splitext(base)[0]
        patterns = (f"runner/tests/test_{stem}*.py", f"runner/test_{stem}*.py")
        for pattern in patterns:
            for path in glob.glob(os.path.join(repo, pattern)):
                selected.add(os.path.relpath(path, repo))
    # A huge batch must not turn the bounded gate back into the full-suite gate. The critical
    # set is always retained; directly relevant additions are deterministic and capped.
    critical = [p for p in CRITICAL_CANARY_TESTS if p in selected]
    relevant = sorted(selected.difference(critical))[:max(0, CANARY_MAX_CHANGED_TESTS)]
    return critical + relevant


def _run_gate_stage(label, cmd, repo, timeout):
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"self_deploy: {label} timed out after {timeout}s")
        return False
    except Exception as e:
        print(f"self_deploy: {label} failed to run ({e})")
        return False
    if r.returncode != 0:
        tail = ((r.stdout or "") + (r.stderr or ""))[-2000:].strip()
        print(f"self_deploy: {label} red (rc={r.returncode})" +
              (f"\n{tail}" if tail else ""))
        return False
    return True


def canary_gate(repo, base_commit=None, head_commit="HEAD"):
    """Bounded, fail-closed restart gate independent of total test-suite duration.

    The full suite is still collected, so syntax/import/collection failures anywhere stop
    deployment. Runtime assertions are exercised for the self-deploy/release critical path
    and for tests matched to every changed runner module. Unlike the former failure-count
    baseline, a red selected test can never be accepted merely because it was already red.
    """
    base = (base_commit or running_commit(repo) or "").strip()
    changed = _changed_files(repo, base, head_commit)
    if changed is None:
        print("self_deploy: cannot establish boot-to-head diff — failing closed")
        return False

    if not _run_gate_stage(
            "compile gate", ["python3", "-m", "compileall", "-q", "runner"],
            repo, min(CANARY_TIMEOUT, 120)):
        return False

    collect = ["python3", "-m", "pytest", "runner/tests", "--collect-only", "-q"]
    if not _run_gate_stage("collection gate", collect, repo, CANARY_COLLECTION_TIMEOUT):
        return False

    tests = _selected_tests(repo, changed)
    if not tests:
        print("self_deploy: no critical canary tests found — failing closed")
        return False
    cmd = ["python3", "-m", "pytest", *tests, "-q", "-x"]
    if _pytest_timeout_available():
        cmd.append("--timeout=120")
    return _run_gate_stage("bounded behavior gate", cmd, repo, CANARY_TIMEOUT)


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
            "why": "New commits are on master but the bounded compile/collection/behavior "
                   "release canary is red; "
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
        if not canary_gate(repo, st["running_commit"], st["head_commit"]):
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
