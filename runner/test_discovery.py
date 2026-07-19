#!/usr/bin/env python3
"""
test_discovery.py — automated test discovery and coverage gap detection.

Scans runner/ modules, identifies which have corresponding test files, and
reports coverage gaps. Helps the fleet know where new tests are most needed.

Env vars:
    ORCH_TEST_DISCOVERY    "true" to enable (default "true")
    ORCH_RUNNER_DIR        path to runner directory (auto-detected)
    ORCH_TESTS_DIR         path to tests directory (auto-detected)
"""
import os
import sys
import importlib
import inspect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_TEST_DISCOVERY", "true").lower() in ("1", "true", "yes")
RUNNER_DIR = os.environ.get("ORCH_RUNNER_DIR", os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.environ.get("ORCH_TESTS_DIR",
                           os.path.join(os.path.dirname(RUNNER_DIR), "tests"))

# Modules to skip (not testable or infrastructure-only)
_SKIP_MODULES = frozenset({
    "__init__", "log", "db", "conftest", "setup",
})


def discover_modules(runner_dir=None):
    """Return sorted list of .py module names in runner_dir (without extension)."""
    d = runner_dir or RUNNER_DIR
    if not os.path.isdir(d):
        return []
    modules = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".py") or f.startswith("_") or f.startswith("test_"):
            continue
        name = f[:-3]
        if name in _SKIP_MODULES:
            continue
        modules.append(name)
    return modules


def discover_tests(tests_dir=None):
    """Return sorted list of test module names (test_*.py → module name tested)."""
    d = tests_dir or TESTS_DIR
    if not os.path.isdir(d):
        return []
    tested = []
    for f in sorted(os.listdir(d)):
        if f.startswith("test_") and f.endswith(".py"):
            tested.append(f[5:-3])  # test_foo.py -> foo
    return tested


def coverage_gaps(runner_dir=None, tests_dir=None):
    """Return list of runner modules with no corresponding test file."""
    modules = set(discover_modules(runner_dir))
    tested = set(discover_tests(tests_dir))
    return sorted(modules - tested)


def coverage_report(runner_dir=None, tests_dir=None):
    """Return a coverage summary dict."""
    modules = discover_modules(runner_dir)
    tested = set(discover_tests(tests_dir))
    gaps = [m for m in modules if m not in tested]
    total = len(modules)
    covered = total - len(gaps)
    pct = (covered / total * 100) if total > 0 else 0.0
    return {
        "total_modules": total,
        "tested_modules": covered,
        "coverage_pct": round(pct, 1),
        "untested": gaps[:20],  # cap output
        "tested": sorted(tested & set(modules))[:20],
    }


def run():
    """CLI entry point — print coverage report."""
    if not ENABLED:
        print("test_discovery: disabled")
        return {}
    report = coverage_report()
    print(f"test_discovery: {report['tested_modules']}/{report['total_modules']} "
          f"modules tested ({report['coverage_pct']}%)")
    if report["untested"]:
        print(f"  gaps: {', '.join(report['untested'][:10])}")
    return report


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
