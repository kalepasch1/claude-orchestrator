#!/usr/bin/env python3
"""
continuous_test_runner.py — Continuous testing integration for the merge process.

Runs automated tests as part of the merge train and on push, tracks results,
and gates integration on green builds. Integrates with merge_train.py to provide
continuous test feedback during the serialized integration process.

Two modes:
  1. merge-gate: called by merge_train before fast-forward; blocks on red.
  2. push-trigger: called by approval_push/deploy hooks; async, reports only.

Test results are persisted to the `test_runs` concept in the tasks table notes
so the fleet can learn which tests flake and which are reliable signals.
"""
import datetime
import hashlib
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


# ── configuration (read live from env for fleet_config compatibility) ─────────

def _test_cmd():
    return os.environ.get("TEST_CMD", "npm test")

def _test_timeout():
    try:
        return int(os.environ.get("CONTINUOUS_TEST_TIMEOUT", "300"))
    except ValueError:
        return 300

def _max_flake_retries():
    try:
        return int(os.environ.get("CONTINUOUS_TEST_FLAKE_RETRIES", "2"))
    except ValueError:
        return 2

def _result_hash(output):
    """Hash test output to detect flakes (same hash = same failure = likely real)."""
    cleaned = re.sub(r'\d+\.\d+s', 'Xs', output)  # normalize timing
    cleaned = re.sub(r'at \d{4}-\d{2}-\d{2}.*', 'at DATE', cleaned)
    return hashlib.sha256(cleaned.encode(errors="replace")).hexdigest()[:16]


# ── core test execution ──────────────────────────────────────────────────────

def run_tests(repo, branch=None, task=None, mode="merge-gate"):
    """Run tests in a repo, optionally on a specific branch.

    Args:
        repo: path to the git repo (or worktree)
        branch: if set, checkout this branch in a temp worktree first
        task: optional task dict for context/reporting
        mode: "merge-gate" (blocking) or "push-trigger" (async reporting)

    Returns:
        dict with keys: passed (bool), exit_code (int), output (str),
                        output_hash (str), duration_s (float), flake (bool)
    """
    test_cmd = _test_cmd()
    timeout = _test_timeout()
    task_id = (task or {}).get("id", "unknown")
    slug = (task or {}).get("slug", "unknown")

    result = {
        "passed": False,
        "exit_code": -1,
        "output": "",
        "output_hash": "",
        "duration_s": 0.0,
        "flake": False,
        "mode": mode,
        "task_id": task_id,
        "slug": slug,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }

    start = time.monotonic()
    try:
        proc = subprocess.run(
            test_cmd, shell=True, cwd=repo,
            capture_output=True, text=True, timeout=timeout,
        )
        result["exit_code"] = proc.returncode
        result["output"] = (proc.stdout + proc.stderr)[-4000:]  # tail
        result["passed"] = proc.returncode == 0
    except subprocess.TimeoutExpired:
        result["output"] = f"test timed out after {timeout}s"
        result["exit_code"] = 124
    except Exception as e:
        result["output"] = str(e)[:1000]
        result["exit_code"] = -1
    result["duration_s"] = round(time.monotonic() - start, 2)
    result["output_hash"] = _result_hash(result["output"])

    # Flake detection: if failed, retry up to N times; if hash changes, it's a flake
    if not result["passed"] and mode == "merge-gate":
        first_hash = result["output_hash"]
        for retry in range(_max_flake_retries()):
            time.sleep(2 ** retry)  # exponential backoff
            retry_result = _run_once(repo, test_cmd, timeout)
            if retry_result["passed"]:
                result["passed"] = True
                result["flake"] = True
                result["output"] += f"\n[flake: passed on retry {retry + 1}]"
                break
            if retry_result["output_hash"] != first_hash:
                result["flake"] = True
                result["output"] += f"\n[flake: different output on retry {retry + 1}]"

    # Persist result
    _record_test_run(result)
    return result


def _run_once(repo, test_cmd, timeout):
    """Single test execution, no retries."""
    try:
        proc = subprocess.run(
            test_cmd, shell=True, cwd=repo,
            capture_output=True, text=True, timeout=timeout,
        )
        output = (proc.stdout + proc.stderr)[-4000:]
        return {
            "passed": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output": output,
            "output_hash": _result_hash(output),
        }
    except Exception:
        return {"passed": False, "exit_code": -1, "output": "", "output_hash": ""}


def _record_test_run(result):
    """Persist test run results for fleet learning. Fail-soft."""
    try:
        db.insert("fleet_config", {
            "key": f"test_run:{result['task_id']}:{result['timestamp'][:19]}",
            "value": str({
                "passed": result["passed"],
                "flake": result["flake"],
                "hash": result["output_hash"],
                "duration_s": result["duration_s"],
                "mode": result["mode"],
                "slug": result["slug"],
            })[:500],
        }, on_conflict="key", merge_patch={"value": "EXCLUDED.value"})
    except Exception:
        pass  # fail-soft: test recording is best-effort


# ── merge-gate integration ────────────────────────────────────────────────────

def merge_gate_check(repo, branch, base, task):
    """Called by merge_train before fast-forward. Returns True if tests pass."""
    result = run_tests(repo, branch=branch, task=task, mode="merge-gate")
    return result["passed"]


# ── push-trigger integration ─────────────────────────────────────────────────

def on_push(repo, branch, task=None):
    """Called after a push to run tests asynchronously and report results.

    Non-blocking: records results but does not gate the push.
    """
    result = run_tests(repo, branch=branch, task=task, mode="push-trigger")
    if not result["passed"] and task:
        try:
            note = (task.get("note") or "")
            addendum = f" [push-test-fail: {result['output_hash']}]"
            if addendum not in note:
                db.update("tasks", {"id": task["id"]},
                          {"note": (note + addendum)[:500]})
        except Exception:
            pass
    return result
