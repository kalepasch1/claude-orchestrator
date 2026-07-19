#!/usr/bin/env python3
"""
continuous_test_runner.py — CI/CD-integrated continuous testing automation.

Orchestrates automatic test execution after code changes, integrating with
the incremental_test_oracle for minimal test sets and providing structured
results for the promotion pipeline.

Env vars:
    ORCH_CONTINUOUS_TESTING     "true" to enable (default "true")
    ORCH_CT_TIMEOUT             per-suite timeout in seconds (default 300)
    ORCH_CT_PARALLEL            max parallel test suites (default 2)
    ORCH_CT_FAIL_FAST           stop on first failure (default "false")
"""
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("continuous_test")

ENABLED = os.environ.get("ORCH_CONTINUOUS_TESTING", "true").lower() in ("1", "true", "yes")
TIMEOUT = int(os.environ.get("ORCH_CT_TIMEOUT", "300"))
MAX_PARALLEL = int(os.environ.get("ORCH_CT_PARALLEL", "2"))
FAIL_FAST = os.environ.get("ORCH_CT_FAIL_FAST", "false").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Test result model
# ---------------------------------------------------------------------------
class TestResult:
    """Structured result from a single test run."""

    __slots__ = ("suite", "passed", "failed", "skipped", "duration_s",
                 "exit_code", "output", "error")

    def __init__(self, suite="", passed=0, failed=0, skipped=0,
                 duration_s=0.0, exit_code=0, output="", error=""):
        self.suite = suite
        self.passed = passed
        self.failed = failed
        self.skipped = skipped
        self.duration_s = duration_s
        self.exit_code = exit_code
        self.output = output
        self.error = error

    @property
    def ok(self):
        return self.exit_code == 0 and self.failed == 0

    def to_dict(self):
        return {
            "suite": self.suite,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_s": round(self.duration_s, 2),
            "exit_code": self.exit_code,
            "ok": self.ok,
            "output_tail": self.output[-2000:] if self.output else "",
            "error": self.error[:1000] if self.error else "",
        }


# ---------------------------------------------------------------------------
# Detect changed files
# ---------------------------------------------------------------------------
def detect_changed_files(repo_path, base_branch="master"):
    """Return list of files changed relative to *base_branch*."""
    if not repo_path or not os.path.isdir(repo_path):
        return []
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", base_branch, "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return []
        return [f.strip() for f in r.stdout.splitlines() if f.strip()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Run a test command
# ---------------------------------------------------------------------------
def run_test_command(cmd, cwd=None, timeout=None, env_override=None):
    """Execute a test command and return a TestResult.

    Args:
        cmd: shell command string or list
        cwd: working directory
        timeout: seconds before SIGTERM
        env_override: dict of env vars to add/override

    Returns:
        TestResult with structured output
    """
    timeout = timeout or TIMEOUT
    env = dict(os.environ)
    if env_override:
        env.update(env_override)

    start = time.time()
    try:
        if isinstance(cmd, str):
            r = subprocess.run(
                cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                timeout=timeout, env=env,
            )
        else:
            r = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True,
                timeout=timeout, env=env,
            )
        duration = time.time() - start
        output = r.stdout + r.stderr

        # Parse pass/fail counts from common test runner output
        passed, failed, skipped = _parse_test_counts(output)

        return TestResult(
            suite=cmd if isinstance(cmd, str) else " ".join(cmd),
            passed=passed, failed=failed, skipped=skipped,
            duration_s=duration, exit_code=r.returncode,
            output=output, error=r.stderr if r.returncode != 0 else "",
        )
    except subprocess.TimeoutExpired:
        return TestResult(
            suite=cmd if isinstance(cmd, str) else " ".join(cmd),
            duration_s=time.time() - start,
            exit_code=-1, error=f"Timed out after {timeout}s",
        )
    except Exception as e:
        return TestResult(
            suite=cmd if isinstance(cmd, str) else " ".join(cmd),
            exit_code=-2, error=str(e),
        )


def _parse_test_counts(output):
    """Extract pass/fail/skip counts from test runner output.

    Supports pytest, jest, and generic patterns. Returns (passed, failed, skipped).
    """
    import re

    passed = failed = skipped = 0

    # pytest: "5 passed, 2 failed, 1 skipped"
    m = re.search(r"(\d+)\s+passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", output)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+)\s+skipped", output)
    if m:
        skipped = int(m.group(1))

    # jest: "Tests: 2 failed, 5 passed, 7 total"
    if not passed and not failed:
        m = re.search(r"Tests:\s*(\d+)\s+failed,\s*(\d+)\s+passed", output)
        if m:
            failed = int(m.group(1))
            passed = int(m.group(2))
        else:
            m = re.search(r"Tests:\s*(\d+)\s+passed", output)
            if m:
                passed = int(m.group(1))

    return passed, failed, skipped


# ---------------------------------------------------------------------------
# Run suite with incremental oracle
# ---------------------------------------------------------------------------
def run_incremental(test_cmd, repo_path, project_id, base_branch="master",
                    timeout=None):
    """Run tests incrementally: detect changes, query oracle, run minimal set.

    Returns a dict with 'changed_files', 'affected_tests', 'result'.
    Falls back to running the full test command if oracle unavailable.
    """
    changed = detect_changed_files(repo_path, base_branch)
    affected = []

    # Try oracle for minimal test set
    try:
        import incremental_test_oracle
        affected = incremental_test_oracle.affected_tests(changed, project_id)
    except Exception:
        pass  # fail-soft: run full suite

    if affected:
        # Run only affected tests (pytest-specific)
        test_args = " ".join(affected)
        cmd = f"cd {repo_path} && python -m pytest {test_args} -x --tb=short"
        result = run_test_command(cmd, cwd=repo_path, timeout=timeout)
    else:
        # Full suite fallback
        result = run_test_command(test_cmd, cwd=repo_path, timeout=timeout)

    return {
        "changed_files": changed,
        "affected_tests": affected,
        "incremental": bool(affected),
        "result": result.to_dict(),
    }


# ---------------------------------------------------------------------------
# Aggregate results
# ---------------------------------------------------------------------------
def aggregate_results(results):
    """Aggregate multiple TestResult dicts into a summary.

    Args:
        results: list of TestResult.to_dict() dicts

    Returns:
        dict with overall pass/fail, total counts, and per-suite breakdown
    """
    total_passed = sum(r.get("passed", 0) for r in results)
    total_failed = sum(r.get("failed", 0) for r in results)
    total_skipped = sum(r.get("skipped", 0) for r in results)
    total_duration = sum(r.get("duration_s", 0) for r in results)
    all_ok = all(r.get("ok", False) for r in results)

    return {
        "ok": all_ok,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_skipped": total_skipped,
        "total_duration_s": round(total_duration, 2),
        "suite_count": len(results),
        "suites": results,
    }


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
_stats_lock = threading.Lock()
_stats = {"runs": 0, "incremental_runs": 0, "full_runs": 0, "failures": 0}


def stats():
    with _stats_lock:
        return dict(_stats)


def reset_stats():
    with _stats_lock:
        for k in _stats:
            _stats[k] = 0
