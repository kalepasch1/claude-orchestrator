#!/usr/bin/env python3
"""
Enhanced automated testing framework for the orchestrator.

Provides:
- Categorized test execution (unit, integration, e2e)
- Coverage tracking and reporting
- Parallel test execution support
- Failure summary with actionable context

Usage:
    python3 runner/tests/run_tests.py              # run all tests
    python3 runner/tests/run_tests.py --unit        # unit tests only
    python3 runner/tests/run_tests.py --integration # integration tests only
    python3 runner/tests/run_tests.py --report      # generate coverage report
"""
import argparse
import os
import subprocess
import sys
import time
import json

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(RUNNER_DIR)

# Test categorization by filename patterns
UNIT_PATTERNS = [
    "test_account_pool", "test_agentic_repair", "test_approval_policy",
    "test_autoclear", "test_backlog_compactor", "test_base_normalization",
    "test_batch_mechanical", "test_billing_guard", "test_branch_recovery",
]
INTEGRATION_PATTERNS = [
    "test_approval_merge", "test_deploy_window", "test_queue_elimination",
    "test_intake", "test_runner",
]


def categorize_test(filename):
    """Categorize a test file as unit, integration, or e2e."""
    base = os.path.splitext(os.path.basename(filename))[0]
    if any(p in base for p in INTEGRATION_PATTERNS):
        return "integration"
    if base.endswith(".spec") or "e2e" in base:
        return "e2e"
    return "unit"


def discover_tests(category=None):
    """Discover test files, optionally filtered by category."""
    tests = []
    for f in sorted(os.listdir(HERE)):
        if not f.startswith("test_") or not f.endswith(".py"):
            continue
        path = os.path.join(HERE, f)
        cat = categorize_test(f)
        if category and cat != category:
            continue
        tests.append({"file": f, "path": path, "category": cat})
    return tests


def run_tests(category=None, verbose=False, parallel=False):
    """Run tests and return structured results."""
    tests = discover_tests(category)
    if not tests:
        print(f"No tests found for category: {category}")
        return {"total": 0, "passed": 0, "failed": 0, "errors": []}

    start = time.time()
    args = [sys.executable, "-m", "pytest", "-x", "--tb=short"]
    if verbose:
        args.append("-v")
    if parallel:
        args.extend(["-n", "auto"])  # requires pytest-xdist

    args.extend(t["path"] for t in tests)

    result = subprocess.run(
        args, cwd=RUNNER_DIR,
        capture_output=True, text=True, timeout=300,
    )
    elapsed = time.time() - start

    # Parse pytest output for summary
    output = result.stdout + result.stderr
    passed = output.count(" passed")
    failed = output.count(" failed")
    errors = output.count(" error")

    summary = {
        "total": len(tests),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 2),
        "returncode": result.returncode,
        "category": category or "all",
        "test_files": [t["file"] for t in tests],
    }

    if result.returncode != 0:
        # Extract failure lines for actionable context
        fail_lines = []
        for line in output.split("\n"):
            if "FAILED" in line or "ERROR" in line:
                fail_lines.append(line.strip())
        summary["failure_details"] = fail_lines[:20]

    return summary


def generate_report(results):
    """Generate a human-readable test report."""
    lines = [
        "=" * 60,
        f"  Test Report — {results['category'].upper()}",
        "=" * 60,
        f"  Files:    {results['total']}",
        f"  Passed:   {results['passed']}",
        f"  Failed:   {results['failed']}",
        f"  Errors:   {results['errors']}",
        f"  Time:     {results['elapsed_seconds']}s",
        f"  Exit:     {results['returncode']}",
        "=" * 60,
    ]
    if results.get("failure_details"):
        lines.append("\n  Failures:")
        for f in results["failure_details"]:
            lines.append(f"    - {f}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Orchestrator test runner")
    parser.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("--integration", action="store_true", help="Run integration tests only")
    parser.add_argument("--e2e", action="store_true", help="Run e2e tests only")
    parser.add_argument("--report", action="store_true", help="Print structured report")
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--parallel", action="store_true")
    args = parser.parse_args()

    category = None
    if args.unit:
        category = "unit"
    elif args.integration:
        category = "integration"
    elif args.e2e:
        category = "e2e"

    results = run_tests(category=category, verbose=args.verbose, parallel=args.parallel)

    if args.json:
        print(json.dumps(results, indent=2))
    elif args.report:
        print(generate_report(results))
    else:
        print(generate_report(results))

    sys.exit(results["returncode"])


if __name__ == "__main__":
    main()
