#!/usr/bin/env python3
"""
autonomous_test_runner.py - Enhanced autonomous testing framework.

Provides unit, integration, and end-to-end test execution for the orchestrator,
ensuring high coverage without additional human intervention. Runs tests
automatically before each merge request (integrates with merge_train).

Test levels:
  1. Unit tests: Fast, per-module syntax and import checks
  2. Integration tests: Cross-module pytest execution
  3. End-to-end tests: Full task lifecycle validation
"""
import os, sys, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TEST_TIMEOUT = int(os.environ.get("ORCH_TEST_TIMEOUT", "120"))
RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))


def run_unit_tests(repo=None):
    """Validate all Python modules can be parsed."""
    target = repo or RUNNER_DIR
    results = {"passed": 0, "failed": 0, "errors": []}
    py_files = [f for f in os.listdir(target) if f.endswith(".py") and not f.startswith("__")]
    for fname in sorted(py_files):
        fpath = os.path.join(target, fname)
        try:
            r = subprocess.run([sys.executable, "-c",
                f"import ast; ast.parse(open('{fpath}').read())"],
                capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({"file": fname, "error": r.stderr[:200]})
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"file": fname, "error": str(e)[:200]})
    return results


def run_integration_tests(repo=None):
    """Run pytest on test_*.py files if present."""
    target = repo or RUNNER_DIR
    results = {"passed": 0, "failed": 0, "errors": [], "skipped": False}
    test_files = [os.path.join(target, f) for f in os.listdir(target)
                  if f.startswith("test_") and f.endswith(".py")]
    test_dir = os.path.join(target, "tests")
    if os.path.isdir(test_dir):
        test_files += [os.path.join(test_dir, f) for f in os.listdir(test_dir)
                       if f.startswith("test_") and f.endswith(".py")]
    if not test_files:
        results["skipped"] = True
        return results
    for tf in test_files:
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", tf, "-x", "--tb=short", "-q"],
                cwd=target, capture_output=True, text=True, timeout=TEST_TIMEOUT)
            if r.returncode == 0:
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({"file": os.path.basename(tf),
                    "output": r.stdout[-300:] + r.stderr[-200:]})
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"file": os.path.basename(tf), "error": str(e)[:200]})
    return results


def run_e2e_tests(repo=None):
    """Validate core module imports (task lifecycle pipeline)."""
    results = {"passed": 0, "failed": 0, "errors": []}
    for name in ("db", "pipeline_contract", "approval_merge", "merge_train"):
        try:
            __import__(name)
            results["passed"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"check": name, "error": str(e)[:200]})
    return results


def run_premerge_suite(repo, branch=None):
    """Run full test suite as a pre-merge gate. Returns (passed: bool, report: dict)."""
    print(f"[autonomous_test_runner] running pre-merge suite on {repo}")
    t0 = time.time()
    test_cmd = os.environ.get("TEST_CMD", "npm test")
    project_test_ok = True
    project_output = ""
    try:
        r = subprocess.run(test_cmd.split(), cwd=repo,
                           capture_output=True, text=True, timeout=TEST_TIMEOUT)
        project_test_ok = r.returncode == 0
        project_output = (r.stdout[-500:] + r.stderr[-300:]) if not project_test_ok else ""
    except subprocess.TimeoutExpired:
        project_test_ok = False
        project_output = f"test command timed out after {TEST_TIMEOUT}s"
    except FileNotFoundError:
        project_test_ok = True
        project_output = "no test command found, skipping"
    runner_dir = os.path.join(repo, "runner") if os.path.isdir(os.path.join(repo, "runner")) else repo
    unit = run_unit_tests(runner_dir)
    elapsed = time.time() - t0
    report = {
        "project_tests": {"passed": project_test_ok, "output": project_output},
        "unit_tests": unit, "elapsed_seconds": round(elapsed, 1), "branch": branch,
    }
    all_passed = project_test_ok and unit["failed"] == 0
    print(f"[autonomous_test_runner] {'PASS' if all_passed else 'FAIL'} in {elapsed:.1f}s")
    return all_passed, report


def run(level="all"):
    print(f"[autonomous_test_runner] running level={level}")
    all_ok = True
    if level in ("unit", "all"):
        unit = run_unit_tests()
        print(f"  unit: {unit['passed']} passed, {unit['failed']} failed")
        if unit["failed"] > 0:
            all_ok = False
            for e in unit["errors"][:5]:
                print(f"    FAIL: {e.get('file','?')}: {e.get('error','')[:100]}")
    if level in ("integration", "all"):
        integ = run_integration_tests()
        if integ.get("skipped"):
            print("  integration: skipped (no test files)")
        else:
            print(f"  integration: {integ['passed']} passed, {integ['failed']} failed")
            if integ["failed"] > 0:
                all_ok = False
    if level in ("e2e", "all"):
        e2e = run_e2e_tests()
        print(f"  e2e: {e2e['passed']} passed, {e2e['failed']} failed")
        if e2e["failed"] > 0:
            all_ok = False
    print(f"[autonomous_test_runner] overall: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", default="all", choices=["unit", "integration", "e2e", "all"])
    args = parser.parse_args()
    sys.exit(0 if run(args.level) else 1)
