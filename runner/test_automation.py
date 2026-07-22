#!/usr/bin/env python3
"""
test_automation.py — automated test discovery, execution, and reporting.

Coordinates test discovery, selective execution based on changed files,
and structured reporting. Integrates with CI via subprocess pytest calls.

Env vars:
    ORCH_TEST_AUTOMATION_ENABLED  "true" to enable (default "true")
    ORCH_TEST_AUTO_TIMEOUT        per-suite timeout in seconds (default 300)
    ORCH_TEST_AUTO_VERBOSE        verbose pytest output (default "false")
"""
import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("test_automation")

ENABLED = os.environ.get("ORCH_TEST_AUTOMATION_ENABLED", "true").lower() in (
    "1", "true", "yes", "on",
)
TIMEOUT = int(os.environ.get("ORCH_TEST_AUTO_TIMEOUT", "300"))
VERBOSE = os.environ.get("ORCH_TEST_AUTO_VERBOSE", "false").lower() in (
    "1", "true", "yes", "on",
)

_invocations = 0
_errors = 0
_suites_run = 0


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_tests(test_dir="runner/tests"):
    """Glob for test_*.py files under *test_dir*. Returns sorted list of paths."""
    global _invocations
    _invocations += 1
    if not ENABLED:
        _log.info("test_automation disabled — skipping discovery")
        return []
    try:
        pattern = os.path.join(test_dir, "test_*.py")
        found = sorted(glob.glob(pattern))
        _log.info("discovered %d test files in %s", len(found), test_dir)
        return found
    except Exception as exc:
        global _errors
        _errors += 1
        _log.warning("discover_tests failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_test_suite(test_dir="runner/tests", pattern=None):
    """Run pytest on discovered tests, capture structured results.

    If *pattern* is given only files matching it are selected.
    Returns dict with keys: passed, failed, skipped, total, duration_s,
    exit_code, output, error, files.
    """
    global _invocations, _suites_run, _errors
    _invocations += 1
    if not ENABLED:
        _log.info("test_automation disabled — skipping suite run")
        return _empty_result()
    try:
        files = discover_tests(test_dir)
        if pattern:
            files = [f for f in files if pattern in os.path.basename(f)]
        if not files:
            _log.info("no test files matched")
            return _empty_result(files=[])
        return _run_pytest(files)
    except Exception as exc:
        _errors += 1
        _log.warning("run_test_suite failed: %s", exc)
        return _empty_result(error=str(exc))


def run_on_merge_request(changed_files):
    """Determine affected tests from *changed_files* and run only those.

    Mapping heuristic: for a changed file ``runner/foo.py`` look for
    ``runner/tests/test_foo.py``.  Always includes any changed test files.
    Returns same dict shape as run_test_suite.
    """
    global _invocations, _errors
    _invocations += 1
    if not ENABLED:
        _log.info("test_automation disabled — skipping merge-request run")
        return _empty_result()
    try:
        affected = _affected_tests(changed_files)
        if not affected:
            _log.info("no affected tests for changed files")
            return _empty_result(files=[])
        existing = [f for f in affected if os.path.isfile(f)]
        if not existing:
            _log.info("affected test files not found on disk")
            return _empty_result(files=[])
        return _run_pytest(existing)
    except Exception as exc:
        _errors += 1
        _log.warning("run_on_merge_request failed: %s", exc)
        return _empty_result(error=str(exc))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def generate_report(results):
    """Produce a human-readable summary report from a results dict.

    Returns a multi-line string with passed/failed/skipped counts and duration.
    """
    global _invocations
    _invocations += 1
    if not isinstance(results, dict):
        return "Invalid results object"
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    skipped = results.get("skipped", 0)
    total = results.get("total", 0)
    duration = results.get("duration_s", 0.0)
    status = "PASS" if failed == 0 and total > 0 else "FAIL" if failed > 0 else "NO TESTS"
    lines = [
        f"Test Report — {status}",
        f"  Total:   {total}",
        f"  Passed:  {passed}",
        f"  Failed:  {failed}",
        f"  Skipped: {skipped}",
        f"  Duration: {duration:.2f}s",
    ]
    if results.get("error"):
        lines.append(f"  Error: {results['error']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def stats():
    """Return module statistics."""
    return {
        "enabled": ENABLED,
        "invocations": _invocations,
        "errors": _errors,
        "suites_run": _suites_run,
        "timeout": TIMEOUT,
        "verbose": VERBOSE,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _empty_result(files=None, error=""):
    """Return a zeroed-out result dict."""
    return {
        "passed": 0, "failed": 0, "skipped": 0, "total": 0,
        "duration_s": 0.0, "exit_code": 0, "output": "", "error": error,
        "files": files or [],
    }


def _run_pytest(files):
    """Execute pytest on *files* and parse results."""
    global _suites_run, _errors
    cmd = [sys.executable, "-m", "pytest", "--tb=short", "-q"]
    if VERBOSE:
        cmd.append("-v")
    cmd.extend(files)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT,
        )
        duration = time.monotonic() - start
        _suites_run += 1
        parsed = _parse_pytest_output(proc.stdout)
        parsed["duration_s"] = round(duration, 2)
        parsed["exit_code"] = proc.returncode
        parsed["output"] = (proc.stdout or "")[-2000:]
        parsed["error"] = (proc.stderr or "")[-2000:]
        parsed["files"] = files
        return parsed
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        _errors += 1
        return {
            "passed": 0, "failed": 0, "skipped": 0, "total": 0,
            "duration_s": round(duration, 2), "exit_code": -1,
            "output": "", "error": f"pytest timed out after {TIMEOUT}s",
            "files": files,
        }
    except Exception as exc:
        _errors += 1
        return _empty_result(files=files, error=str(exc))


def _parse_pytest_output(stdout):
    """Best-effort parse of pytest summary line.

    Looks for patterns like '5 passed', '2 failed', '1 skipped' in the
    last few lines of stdout.
    """
    import re
    passed = failed = skipped = 0
    if not stdout:
        return {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
    tail = stdout[-500:]
    m = re.search(r"(\d+)\s+passed", tail)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", tail)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+)\s+skipped", tail)
    if m:
        skipped = int(m.group(1))
    return {"passed": passed, "failed": failed, "skipped": skipped,
            "total": passed + failed + skipped}


def _affected_tests(changed_files):
    """Map changed source files to their corresponding test files.

    Heuristic: runner/foo.py -> runner/tests/test_foo.py.
    Changed test files are included directly.
    """
    affected = set()
    for path in changed_files:
        basename = os.path.basename(path)
        dirname = os.path.dirname(path)
        # If the changed file is itself a test, include it
        if basename.startswith("test_") and basename.endswith(".py"):
            affected.add(path)
            continue
        # Map source -> test
        if basename.endswith(".py"):
            test_name = f"test_{basename}"
            test_dir = os.path.join(dirname, "tests")
            affected.add(os.path.join(test_dir, test_name))
    return sorted(affected)
