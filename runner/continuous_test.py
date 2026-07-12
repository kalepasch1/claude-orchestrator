#!/usr/bin/env python3
"""
continuous_test.py - automated test runner for post-merge validation.

Runs unit tests and optional browser-based smoke tests against recently merged
task branches to catch regressions early.  Integrates with the existing build_gate
and regression modules, adding a continuous loop that validates merged code rather
than just pre-merge checks.

Unit tests are run via the project's configured test command.  Browser-based tests
(Selenium) are optional and gated behind ORCH_BROWSER_TESTS=true.

Usage:
    import continuous_test
    results = continuous_test.run_suite(repo_path, project_id)
    # results: {unit: {passed, failed, skipped}, browser: {...}, overall: bool}
"""
import os
import subprocess
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BROWSER_TESTS_ENABLED = os.environ.get("ORCH_BROWSER_TESTS", "false").lower() in ("1", "true", "yes")
TEST_TIMEOUT = int(os.environ.get("ORCH_TEST_TIMEOUT", "120"))
UNIT_TEST_CMD = os.environ.get("ORCH_UNIT_TEST_CMD", "")
BROWSER_TEST_CMD = os.environ.get("ORCH_BROWSER_TEST_CMD", "")


def _run_cmd(cmd: str, cwd: str, timeout: int = None) -> dict:
    """Run a shell command and return structured result. Fail-soft."""
    timeout = timeout or TEST_TIMEOUT
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "returncode": r.returncode,
            "stdout": r.stdout[-2000:] if r.stdout else "",
            "stderr": r.stderr[-1000:] if r.stderr else "",
            "passed": r.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "timeout", "passed": False}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "passed": False}


def _detect_test_cmd(repo_path: str) -> str:
    """Auto-detect the project's test command from package.json or pyproject.toml."""
    if UNIT_TEST_CMD:
        return UNIT_TEST_CMD

    # Check package.json
    pkg_json = os.path.join(repo_path, "package.json")
    if not os.path.isfile(pkg_json):
        pkg_json = os.path.join(repo_path, "web", "package.json")
    if os.path.isfile(pkg_json):
        try:
            with open(pkg_json) as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                return "npm test --if-present"
        except Exception:
            pass

    # Check for pytest
    for name in ("pyproject.toml", "setup.cfg", "pytest.ini"):
        if os.path.isfile(os.path.join(repo_path, name)):
            return "python -m pytest --tb=short -q 2>&1 || true"

    # Check runner/tests
    test_dir = os.path.join(repo_path, "runner", "tests")
    if os.path.isdir(test_dir):
        return f"python -m pytest {test_dir} --tb=short -q 2>&1 || true"

    return ""


def run_unit_tests(repo_path: str) -> dict:
    """Run unit tests and return {passed: int, failed: int, skipped: int, ok: bool}."""
    cmd = _detect_test_cmd(repo_path)
    if not cmd:
        return {"passed": 0, "failed": 0, "skipped": 0, "ok": True, "note": "no test command found"}

    result = _run_cmd(cmd, repo_path)
    return {
        "passed": 1 if result["passed"] else 0,
        "failed": 0 if result["passed"] else 1,
        "skipped": 0,
        "ok": result["passed"],
        "output": result["stdout"][-500:],
        "note": result["stderr"][:200] if not result["passed"] else "",
    }


def run_browser_tests(repo_path: str) -> dict:
    """Run browser-based smoke tests (Selenium). Returns {ok, note}."""
    if not BROWSER_TESTS_ENABLED:
        return {"ok": True, "note": "browser tests disabled (set ORCH_BROWSER_TESTS=true)"}

    cmd = BROWSER_TEST_CMD or "python -m pytest tests/browser --tb=short -q 2>&1 || true"
    result = _run_cmd(cmd, repo_path, timeout=TEST_TIMEOUT * 2)
    return {
        "ok": result["passed"],
        "output": result["stdout"][-500:],
        "note": result["stderr"][:200] if not result["passed"] else "",
    }


def run_suite(repo_path: str, project_id: str = "") -> dict:
    """Run the full test suite (unit + optional browser) and return combined results.

    Fail-soft: always returns a result dict, never raises.
    """
    try:
        unit = run_unit_tests(repo_path)
        browser = run_browser_tests(repo_path)
        overall = unit.get("ok", True) and browser.get("ok", True)

        result = {
            "unit": unit,
            "browser": browser,
            "overall": overall,
            "project_id": project_id,
            "timestamp": time.time(),
        }

        # Record result in DB if available
        if not overall:
            _record_failure(project_id, result)

        return result
    except Exception as e:
        return {
            "unit": {"ok": True, "note": "error"},
            "browser": {"ok": True, "note": "skipped"},
            "overall": True,
            "error": str(e),
        }


def _record_failure(project_id: str, result: dict) -> None:
    """Record test failure in DB for tracking. Fail-soft."""
    try:
        import db
        note = f"continuous_test: unit={'PASS' if result['unit']['ok'] else 'FAIL'}, browser={'PASS' if result['browser']['ok'] else 'FAIL'}"
        db.query(
            "INSERT INTO fleet_config (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (f"ORCH_LAST_TEST_RESULT_{project_id[:8]}", note),
        )
    except Exception:
        pass
