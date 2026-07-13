#!/usr/bin/env python3
"""
test_suite_runner.py — automated test discovery and execution.

Discovers all test_*.py files in the runner directory and executes them,
reporting pass/fail counts and identifying regressions.

Usage:
    python test_suite_runner.py           # run all tests
    python test_suite_runner.py --quick   # run only fast tests (no DB)
"""
import os, sys, importlib, traceback, time, argparse

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RUNNER_DIR)

# Ensure DB stubs are present so tests can import modules that reference db
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")


def discover_test_modules():
    """Find all test_*.py files in the runner directory."""
    modules = []
    for f in sorted(os.listdir(RUNNER_DIR)):
        if f.startswith("test_") and f.endswith(".py") and f != "test_suite_runner.py":
            modules.append(f[:-3])  # strip .py
    return modules


def run_module_tests(mod_name):
    """Import a test module and run all test_ functions in it."""
    results = {"passed": 0, "failed": 0, "errors": []}
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        results["errors"].append(f"IMPORT ERROR: {mod_name}: {e}")
        results["failed"] += 1
        return results

    for attr_name in sorted(dir(mod)):
        if not attr_name.startswith("test_"):
            continue
        fn = getattr(mod, attr_name)
        if not callable(fn):
            continue
        try:
            fn()
            results["passed"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"{mod_name}.{attr_name}: {e}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Run orchestrator test suite")
    parser.add_argument("--quick", action="store_true", help="Skip slow/DB tests")
    args = parser.parse_args()

    modules = discover_test_modules()
    total_pass = 0
    total_fail = 0
    all_errors = []
    t0 = time.monotonic()

    print(f"Discovered {len(modules)} test module(s)\n")

    for mod_name in modules:
        r = run_module_tests(mod_name)
        status = "OK" if r["failed"] == 0 else "FAIL"
        print(f"  [{status}] {mod_name}: {r['passed']} passed, {r['failed']} failed")
        total_pass += r["passed"]
        total_fail += r["failed"]
        all_errors.extend(r["errors"])

    elapsed = time.monotonic() - t0
    print(f"\n{'='*60}")
    print(f"Total: {total_pass} passed, {total_fail} failed in {elapsed:.1f}s")

    if all_errors:
        print(f"\nFailures:")
        for err in all_errors:
            print(f"  - {err}")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
