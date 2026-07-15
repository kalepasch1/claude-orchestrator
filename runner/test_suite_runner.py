#!/usr/bin/env python3
"""
test_suite_runner.py — automated test discovery and execution.

Discovers all test_*.py files in the runner directory and executes them,
reporting pass/fail counts and identifying regressions.

Usage:
    python test_suite_runner.py           # run all tests
    python test_suite_runner.py --quick   # run only fast tests (no DB)
    python test_suite_runner.py --git-diff-base main # run tests affected by changes since 'main'
"""
import os, sys, importlib, traceback, time, argparse
import subprocess # Needed for git diff

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RUNNER_DIR)

# Ensure DB stubs are present so tests can import modules that reference db
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")


def _get_changed_python_files(base_commit):
    """
    Uses git diff to find changed Python files relative to RUNNER_DIR.
    Returns a list of paths relative to RUNNER_DIR.
    """
    try:
        # Get the current HEAD commit
        current_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=RUNNER_DIR,
            check=True,
            capture_output=True,
            text=True
        ).stdout.strip()

        # Get changed files between base_commit and current_head
        result = subprocess.run(
            ["git", "diff", "--name-only", base_commit, current_head],
            cwd=RUNNER_DIR,
            check=True,
            capture_output=True,
            text=True
        )
        changed_files = result.stdout.strip().split('\n')
        
        # Filter for Python files within RUNNER_DIR and make paths relative
        python_files = []
        for f in changed_files:
            if f and f.endswith(".py") and os.path.exists(os.path.join(RUNNER_DIR, f)):
                python_files.append(f)
        return python_files
    except subprocess.CalledProcessError as e:
        print(f"Error running git command: {e}", file=sys.stderr)
        print(f"Stdout: {e.stdout}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
        return []
    except FileNotFoundError:
        print("Git command not found. Is Git installed and in PATH?", file=sys.stderr)
        return []


def discover_all_test_modules():
    """Find all test_*.py files in the runner directory."""
    modules = []
    for f in sorted(os.listdir(RUNNER_DIR)):
        if f.startswith("test_") and f.endswith(".py") and f != "test_suite_runner.py":
            modules.append(f[:-3])  # strip .py
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
    results = {"passed": 0, "failed": 0, "errors": []}
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        results["errors"].append(f"IMPORT ERROR: {mod_name}: {e}\n{traceback.format_exc()}")
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
            results["errors"].append(f"{mod_name}.{attr_name}: {e}\n{traceback.format_exc()}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Run orchestrator test suite")
    parser.add_argument("--quick", action="store_true", help="Skip slow/DB tests")
    parser.add_argument("--git-diff-base", type=str,
                        help="Run only tests affected by changes since this git commit/ref.")
    args = parser.parse_args()

    # Pass args to discover_test_modules
    modules = discover_test_modules(args)
    total_pass = 0
    total_fail = 0
    all_errors = []
    t0 = time.monotonic()

    if not modules:
        print("No test modules to run.")
        return 0

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
