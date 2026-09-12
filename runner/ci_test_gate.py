#!/usr/bin/env python3
"""
ci_test_gate.py - CI/CD test pipeline gate for the orchestrator.

Runs the project's test_cmd on a branch and gates merge on the result.
Integrates with incremental_test_oracle for targeted test selection.

The gate:
  - the test command must exit 0
  - it must finish inside ORCH_CI_MAX_DURATION_S (default 300s), which is enforced as
    the subprocess timeout: overrunning it is a TIMEOUT, reported as a failure

Env vars:
    ORCH_CI_TEST_GATE            "true" (default) to enable
    ORCH_CI_MAX_DURATION_S       max test duration in seconds (default: 300)
    ORCH_CI_DRY_RUN              "true" (DEFAULT) — records the verdict and allows the
                                 merge anyway. Set "false" to make this gate binding.
    ORCH_CI_AUTO_BLOCK           "true" to auto-block merge on failure

TWO KNOBS REMOVED HERE, 2026-08-24, because they did nothing:

  ORCH_CI_PASS_THRESHOLD was documented above as "test pass rate must be >= ..." and
  declared as a module constant. It was never read. A pass RATE was never computed at
  all — the gate is binary on the command's exit code — so an operator who set it to
  0.9 to tolerate a flaky suite got 1.0 behaviour and no indication why. A knob that
  lies about what it controls is worse than an absent one.

  `if result["duration_s"] > MAX_DURATION` was unreachable. MAX_DURATION is passed to
  subprocess.run as `timeout`, so a run that exceeds it raises TimeoutExpired and comes
  back passed=False, and the `not passed` branch returns before the duration check is
  ever evaluated. The "tests too slow" verdict could not be produced. The bound is real
  and still enforced — as a timeout, which is where it always actually lived.

If a genuine pass-rate tolerance is wanted, it needs a parser for the runner's summary
output and a decision about which formats to support; that is a feature, not a
restoration, and it should not be implied by a constant nobody reads.
"""
import os, sys, subprocess, time, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("ci_test_gate")
import db

ENABLED = os.environ.get("ORCH_CI_TEST_GATE", "true").lower() in ("1", "true", "yes", "on")
MAX_DURATION = float(os.environ.get("ORCH_CI_MAX_DURATION_S", "300") or 300)
DRY_RUN = os.environ.get("ORCH_CI_DRY_RUN", "true").lower() in ("1", "true", "yes", "on")
AUTO_BLOCK = os.environ.get("ORCH_CI_AUTO_BLOCK", "true").lower() in ("1", "true", "yes", "on")


def run_tests(repo_path, test_cmd, branch=None, timeout=None):
    """Run test_cmd in repo_path. Returns dict with pass/fail, timing, output."""
    timeout = timeout or MAX_DURATION
    env = {**os.environ}

    start = time.monotonic()
    try:
        r = subprocess.run(
            test_cmd, shell=True, cwd=repo_path,
            capture_output=True, text=True, timeout=timeout, env=env
        )
        duration = time.monotonic() - start
        return {
            "passed": r.returncode == 0,
            "exit_code": r.returncode,
            "duration_s": round(duration, 2),
            "stdout": r.stdout[-2000:] if r.stdout else "",
            "stderr": r.stderr[-2000:] if r.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "exit_code": -1,
            "duration_s": round(time.monotonic() - start, 2),
            "stdout": "",
            "stderr": f"Test timed out after {timeout}s",
        }
    except Exception as e:
        return {
            "passed": False,
            "exit_code": -1,
            "duration_s": round(time.monotonic() - start, 2),
            "stdout": "",
            "stderr": str(e),
        }


def gate_merge(project_id, task_slug, repo_path, test_cmd, branch=None):
    """Run tests and gate merge. Returns {allow: bool, ...}."""
    if not ENABLED:
        return {"allow": True, "reason": "ci_test_gate disabled"}

    result = run_tests(repo_path, test_cmd, branch)
    record = {
        "project_id": project_id,
        "task_slug": task_slug,
        "passed": result["passed"],
        "exit_code": result["exit_code"],
        "duration_s": result["duration_s"],
        "log_tail": (result.get("stdout", "") + "\n" + result.get("stderr", ""))[-3000:],
    }

    try:
        db.insert("ci_test_runs", record)
    except Exception:
        pass

    if DRY_RUN:
        _log.info(f"DRY_RUN: test {'passed' if result['passed'] else 'FAILED'} for {task_slug}")
        return {"allow": True, "reason": "dry-run mode", "test_result": result}

    if not result["passed"]:
        if AUTO_BLOCK:
            try:
                db.update("tasks", {"state": "BLOCKED", "note": f"CI gate: tests failed (exit {result['exit_code']})"}, {"slug": task_slug, "project_id": project_id})
            except Exception:
                pass
        return {"allow": False, "reason": f"tests failed (exit {result['exit_code']})", "test_result": result}

    return {"allow": True, "reason": "tests passed", "test_result": result}


def premerge_check(project_id, task_slug, repo_path, test_cmd):
    """Convenience: called from merge_train before allowing merge."""
    return gate_merge(project_id, task_slug, repo_path, test_cmd)
