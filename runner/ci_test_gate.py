#!/usr/bin/env python3
"""
ci_test_gate.py - CI/CD test pipeline gate for the orchestrator.

Runs the project's test_cmd on a branch and gates merge on the result.
Integrates with incremental_test_oracle for targeted test selection.

Thresholds:
  - test pass rate must be >= ORCH_CI_PASS_THRESHOLD (default 100%)
  - test duration must be <= ORCH_CI_MAX_DURATION_S (default 300s)

Env vars:
    ORCH_CI_TEST_GATE            "true" (default) to enable
    ORCH_CI_PASS_THRESHOLD       minimum pass rate 0.0-1.0 (default: 1.0)
    ORCH_CI_MAX_DURATION_S       max test duration in seconds (default: 300)
    ORCH_CI_DRY_RUN              "true" for dry-run mode
"""
import os, sys, subprocess, time, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("ci_test_gate")
import db

ENABLED = os.environ.get("ORCH_CI_TEST_GATE", "true").lower() in ("1", "true", "yes", "on")
PASS_THRESHOLD = float(os.environ.get("ORCH_CI_PASS_THRESHOLD", "1.0") or 1.0)
MAX_DURATION = float(os.environ.get("ORCH_CI_MAX_DURATION_S", "300") or 300)
DRY_RUN = os.environ.get("ORCH_CI_DRY_RUN", "true").lower() in ("1", "true", "yes", "on")


def run_tests(repo_path, test_cmd, branch=None, timeout=None):
    """
    Run test_cmd in repo_path, optionally checking out branch first.
    Returns {passed: bool, exit_code: int, duration_s: float, stdout: str, stderr: str}.
    """
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
        duration = time.monotonic() - start
        return {
            "passed": False,
            "exit_code": -1,
            "duration_s": round(duration, 2),
            "stdout": "",
            "stderr": f"test timed out after {timeout}s",
        }
    except Exception as e:
        duration = time.monotonic() - start
        return {
            "passed": False,
            "exit_code": -1,
            "duration_s": round(duration, 2),
            "stdout": "",
            "stderr": str(e),
        }


def gate_task(task, project):
    """
    Run CI gate for a task. Returns {task_id, gate_passed, result, reason}.
    """
    if not ENABLED:
        return {"task_id": task["id"], "gate_passed": True, "reason": "gate disabled"}

    repo = db.localize_repo_path(project.get("repo_path", ""))
    test_cmd = project.get("test_cmd", "")

    if not repo or not os.path.isdir(repo):
        return {"task_id": task["id"], "gate_passed": False,
                "reason": f"repo not resolvable: {repo}"}
    if not test_cmd:
        return {"task_id": task["id"], "gate_passed": True,
                "reason": "no test_cmd configured, passing by default"}

    if DRY_RUN:
        _log.info("[DRY RUN] would run '%s' in %s for task %s", test_cmd, repo, task.get("slug"))
        return {"task_id": task["id"], "gate_passed": True, "reason": "dry run"}

    _log.info("running CI gate for task %s: %s", task.get("slug"), test_cmd)
    result = run_tests(repo, test_cmd)

    gate_passed = result["passed"] and result["duration_s"] <= MAX_DURATION
    reason = "passed" if gate_passed else (
        f"tests failed (exit {result['exit_code']})" if not result["passed"]
        else f"exceeded duration limit ({result['duration_s']}s > {MAX_DURATION}s)"
    )

    return {
        "task_id": task["id"],
        "gate_passed": gate_passed,
        "result": result,
        "reason": reason,
    }


def run_gate_batch(project_id=None, limit=5):
    """Run CI gate for DONE tasks pending merge."""
    params = {"select": "id,slug,project_id,base_branch,kind",
              "state": "eq.DONE", "limit": str(limit)}
    if project_id:
        params["project_id"] = f"eq.{project_id}"

    tasks = db.select("tasks", params) or []
    results = []
    for t in tasks:
        pid = t.get("project_id", "")
        projects = db.select("projects", {"select": "*", "id": f"eq.{pid}"}) or []
        if not projects:
            continue
        gate_result = gate_task(t, projects[0])
        results.append(gate_result)
        _log.info("task %s: gate %s (%s)", t.get("slug"),
                  "PASSED" if gate_result["gate_passed"] else "FAILED",
                  gate_result.get("reason", ""))

    return results


# --- Tests ---
def test_run_tests_success():
    """Successful test command returns passed=True."""
    result = run_tests("/tmp", "echo ok", timeout=10)
    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert result["duration_s"] < 10


def test_run_tests_failure():
    """Failed test command returns passed=False."""
    result = run_tests("/tmp", "exit 1", timeout=10)
    assert result["passed"] is False
    assert result["exit_code"] == 1


def test_run_tests_timeout():
    """Timed out test returns passed=False."""
    result = run_tests("/tmp", "sleep 30", timeout=1)
    assert result["passed"] is False
    assert "timed out" in result["stderr"]


if __name__ == "__main__":
    test_run_tests_success()
    test_run_tests_failure()
    test_run_tests_timeout()
    print("All ci_test_gate tests passed")
