#!/usr/bin/env python3
"""
test_suite_runner.py — automated test discovery and execution.

Discovers all test_*.py files in the runner directory *and* the tests/
subdirectory, executes them, and reports pass/fail counts with per-module
timing.

Usage:
    python test_suite_runner.py               # run all tests
    python test_suite_runner.py --quick       # run only fast tests (no DB)
    python test_suite_runner.py --pattern foo # only modules matching 'foo'
    python test_suite_runner.py --subdir      # include tests/ subdirectory
"""
import os, sys, importlib, traceback, time, argparse, fnmatch

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.join(RUNNER_DIR, "tests")
sys.path.insert(0, RUNNER_DIR)

# Ensure DB stubs are present so tests can import modules that reference db
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")


def discover_test_modules(include_subdir=False, pattern=None):
    """Find all test_*.py files in the runner directory and optionally tests/.

    Args:
        include_subdir: also scan runner/tests/ for test modules
        pattern: glob pattern to filter module names (e.g. 'test_branch*')

    Returns:
        list of (module_name, display_label) tuples
    """
    modules = []

    # Root-level test files
    for f in sorted(os.listdir(RUNNER_DIR)):
        if f.startswith("test_") and f.endswith(".py") and f != "test_suite_runner.py":
            mod_name = f[:-3]
            if pattern and not fnmatch.fnmatch(mod_name, pattern):
                continue
            modules.append((mod_name, mod_name))

    # tests/ subdirectory
    if include_subdir and os.path.isdir(TESTS_DIR):
        if TESTS_DIR not in sys.path:
            sys.path.insert(0, TESTS_DIR)
        for f in sorted(os.listdir(TESTS_DIR)):
            if f.startswith("test_") and f.endswith(".py"):
                mod_name = f[:-3]
                if pattern and not fnmatch.fnmatch(mod_name, pattern):
                    continue
                modules.append((mod_name, f"tests/{mod_name}"))

    return modules


def discover_test_modules(args):
    """
    Find test modules, optionally filtering by git diff.
    """
    if not args.git_diff_base:
        return discover_all_test_modules()

    changed_files = _get_changed_python_files(args.git_diff_base)
    
    modules_to_run = set()
    has_non_test_python_changes = False

    for f in changed_files:
        if f.startswith("test_") and f.endswith(".py"):
            modules_to_run.add(f[:-3])
        else:
            # A non-test Python file changed, so we might need to run more tests
            has_non_test_python_changes = True
            break # No need to check further changed files, we'll run all tests

    if has_non_test_python_changes:
        print(f"Non-test Python files changed (e.g., {changed_files[0] if changed_files else 'N/A'}). Running all tests.", file=sys.stderr)
        return discover_all_test_modules()
    elif modules_to_run:
        print(f"Running {len(modules_to_run)} affected test module(s) based on git diff.", file=sys.stderr)
        return sorted(list(modules_to_run))
    else:
        print("No relevant Python files changed or no test files directly affected. Running no tests.", file=sys.stderr)
        return [] # No tests to run if only non-Python files changed, or no changes at all.


def run_module_tests(mod_name):
    """Import a test module and run all test_ functions in it."""
    results = {"passed": 0, "failed": 0, "skipped": 0, "errors": []}
    try:
        # Force reimport in case module was already loaded from a different path
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        mod = importlib.import_module(mod_name)
    except Exception as e:
        results["errors"].append(f"IMPORT ERROR: {mod_name}: {e}\n{traceback.format_exc()}")
        results["failed"] += 1
        return results

    test_fns = []
    for attr_name in sorted(dir(mod)):
        if not attr_name.startswith("test_"):
            continue
        fn = getattr(mod, attr_name)
        if not callable(fn):
            continue
        test_fns.append((attr_name, fn))

    if not test_fns:
        results["skipped"] += 1
        return results

    for attr_name, fn in test_fns:
        try:
            fn()
            results["passed"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"{mod_name}.{attr_name}: {e}\n{traceback.format_exc()}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Run orchestrator test suite")
    parser.add_argument("--quick", action="store_true", help="Skip slow/DB tests")
    parser.add_argument("--subdir", action="store_true",
                        help="Also discover tests in tests/ subdirectory")
    parser.add_argument("--pattern", type=str, default=None,
                        help="Glob pattern to filter module names (e.g. 'test_branch*')")
    args = parser.parse_args()

    modules = discover_test_modules(
        include_subdir=args.subdir,
        pattern=args.pattern,
    )
    total_pass = 0
    total_fail = 0
    total_skip = 0
    all_errors = []
    t0 = time.monotonic()

    if not modules:
        print("No test modules to run.")
        return 0

    print(f"Discovered {len(modules)} test module(s)\n")

    for mod_name, label in modules:
        mt0 = time.monotonic()
        r = run_module_tests(mod_name)
        dur = time.monotonic() - mt0
        status = "OK" if r["failed"] == 0 else "FAIL"
        if r["skipped"] and r["passed"] == 0 and r["failed"] == 0:
            status = "SKIP"
        suffix = f" ({dur:.1f}s)" if dur >= 0.1 else ""
        print(f"  [{status}] {label}: {r['passed']} passed, {r['failed']} failed{suffix}")
        total_pass += r["passed"]
        total_fail += r["failed"]
        total_skip += r["skipped"]
        all_errors.extend(r["errors"])

    elapsed = time.monotonic() - t0
    print(f"\n{'='*60}")
    parts = [f"{total_pass} passed", f"{total_fail} failed"]
    if total_skip:
        parts.append(f"{total_skip} skipped")
    print(f"Total: {', '.join(parts)} in {elapsed:.1f}s")

    if all_errors:
        print(f"\nFailures:")
        for err in all_errors:
            print(f"  - {err}")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
