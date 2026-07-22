#!/usr/bin/env python3
"""
test_framework.py — Unified automated testing framework for the orchestrator.

Integrates unit tests (per-module), integration tests (cross-module interactions),
and end-to-end tests (full task lifecycle) into a single harness. Tracks test results
in the DB for regression detection and merge-gate decisions.

Owner module: eval_harness.py, tdd_gate.py
Slice-2 of: improve-enhanced-automated-testing-framework
"""
import os, sys, subprocess, time, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _safe_import(mod):
    try:
        return __import__(mod)
    except Exception:
        return None

db = _safe_import("db")
log_mod = _safe_import("log")
_log = log_mod.get("test_framework") if log_mod else None

# Test categories
UNIT = "unit"
INTEGRATION = "integration"
E2E = "e2e"

TEST_TIMEOUT = int(os.environ.get("ORCH_TEST_TIMEOUT", "300"))


class TestResult:
    """Immutable test result."""
    __slots__ = ("name", "category", "passed", "duration_s", "error", "output")

    def __init__(self, name, category, passed, duration_s=0.0, error=None, output=""):
        self.name = name
        self.category = category
        self.passed = passed
        self.duration_s = duration_s
        self.error = error
        self.output = output[:2000]  # truncate output

    def to_dict(self):
        return {
            "name": self.name, "category": self.category,
            "passed": self.passed, "duration_s": round(self.duration_s, 3),
            "error": self.error, "output": self.output,
        }


def run_command_test(name, cmd, cwd=None, category=UNIT, timeout=None):
    """Run a shell command as a test. Returns TestResult."""
    timeout = timeout or TEST_TIMEOUT
    start = time.time()
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout
        )
        elapsed = time.time() - start
        passed = proc.returncode == 0
        output = (proc.stdout + proc.stderr)[-2000:]
        return TestResult(name, category, passed, elapsed,
                          error=None if passed else f"exit code {proc.returncode}",
                          output=output)
    except subprocess.TimeoutExpired:
        return TestResult(name, category, False, time.time() - start,
                          error=f"timeout after {timeout}s")
    except Exception as e:
        return TestResult(name, category, False, time.time() - start, error=str(e))


def run_python_test(name, test_path, cwd=None, category=UNIT):
    """Run a Python test file. Returns TestResult."""
    cmd = f"python3 -m pytest {test_path} -x -q --tb=short 2>&1 || python3 {test_path}"
    return run_command_test(name, cmd, cwd=cwd, category=category)


def discover_tests(runner_dir=None):
    """Discover test files in the runner directory.

    Returns dict: {category: [{"name": str, "path": str}]}
    """
    runner_dir = runner_dir or os.path.dirname(os.path.abspath(__file__))
    tests = {UNIT: [], INTEGRATION: [], E2E: []}

    for f in sorted(os.listdir(runner_dir)):
        if f.startswith("test_") and f.endswith(".py"):
            path = os.path.join(runner_dir, f)
            # Categorize by naming convention
            if "integration" in f or "e2e" in f:
                cat = INTEGRATION if "integration" in f else E2E
            else:
                cat = UNIT
            tests[cat].append({"name": f.replace(".py", ""), "path": path})

    tests_dir = os.path.join(runner_dir, "tests")
    if os.path.isdir(tests_dir):
        for f in sorted(os.listdir(tests_dir)):
            if f.startswith("test_") and f.endswith(".py"):
                path = os.path.join(tests_dir, f)
                cat = INTEGRATION if "integration" in f else UNIT
                tests[cat].append({"name": f.replace(".py", ""), "path": path})

    return tests


def run_suite(categories=None, runner_dir=None, record=True):
    """Run all discovered tests in specified categories.

    Args:
        categories: list of categories to run (default: all)
        runner_dir: path to runner directory
        record: if True, record results to DB

    Returns:
        {"passed": int, "failed": int, "total": int, "results": [TestResult.to_dict()],
         "duration_s": float, "categories_run": list}
    """
    runner_dir = runner_dir or os.path.dirname(os.path.abspath(__file__))
    categories = categories or [UNIT, INTEGRATION, E2E]
    all_tests = discover_tests(runner_dir)

    results = []
    total_start = time.time()
    for cat in categories:
        for test_info in all_tests.get(cat, []):
            r = run_python_test(test_info["name"], test_info["path"],
                                cwd=runner_dir, category=cat)
            results.append(r)
            if _log:
                status = "PASS" if r.passed else "FAIL"
                _log.info("[%s] %s %s (%.1fs)", cat, status, r.name, r.duration_s)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total_duration = time.time() - total_start

    # Record to DB if available
    if record and db:
        try:
            db.insert("test_runs", {
                "passed": passed, "failed": failed, "total": len(results),
                "duration_s": round(total_duration, 2),
                "categories": json.dumps(categories),
                "created_at": datetime.datetime.utcnow().isoformat(),
            })
        except Exception:
            pass

    return {
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "results": [r.to_dict() for r in results],
        "duration_s": round(total_duration, 2),
        "categories_run": categories,
    }


def gate_merge(project_id, task_slug, runner_dir=None):
    """Run unit tests and gate merge based on results.

    Returns (allow_merge: bool, summary: str)
    """
    result = run_suite(categories=[UNIT], runner_dir=runner_dir, record=True)
    if result["failed"] == 0:
        return True, f"All {result['passed']} unit tests passed in {result['duration_s']}s"
    else:
        failed_names = [r["name"] for r in result["results"] if not r["passed"]]
        return False, f"{result['failed']}/{result['total']} tests failed: {', '.join(failed_names[:5])}"


def stats():
    """Return framework stats."""
    tests = discover_tests()
    return {
        "unit_tests": len(tests.get(UNIT, [])),
        "integration_tests": len(tests.get(INTEGRATION, [])),
        "e2e_tests": len(tests.get(E2E, [])),
    }
