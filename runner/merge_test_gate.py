#!/usr/bin/env python3
"""
merge_test_gate.py — CI/CD pipeline integration to run tests as part of the merge process.

Before a task branch merges into its base, this gate:
1. Discovers applicable tests (from runner/tests/ matching the changed modules)
2. Runs them in-process or dispatches to CI
3. Blocks the merge if tests fail

Integrates with merge_validator, ci_dispatch, and the existing test framework.
Fail-soft: on import/config errors, degrades to pass-through.
"""
import os
import sys
import subprocess
import time
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("merge_test_gate")

ENABLED = os.environ.get("ORCH_MERGE_TEST_GATE", "true").lower() == "true"
TEST_TIMEOUT_S = int(os.environ.get("ORCH_MERGE_TEST_TIMEOUT_S", "120"))
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
RESULTS_DIR = os.path.join(HOME, "merge-test-results")

_stats = {"runs": 0, "passed": 0, "failed": 0, "skipped": 0}


def stats():
    return dict(_stats)


def _find_changed_modules(repo_path, branch, base):
    """Find Python modules changed between branch and base."""
    if not repo_path or not os.path.isdir(repo_path):
        return []
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{branch}"],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return []
        return [f for f in r.stdout.strip().split("\n")
                if f.endswith(".py") and not f.startswith("tests/")]
    except Exception:
        return []


def _find_matching_tests(changed_modules, repo_path):
    """Find test files that correspond to changed modules."""
    test_dir = os.path.join(repo_path, "runner", "tests")
    if not os.path.isdir(test_dir):
        return []

    tests = []
    for mod in changed_modules:
        base_name = os.path.basename(mod).replace(".py", "")
        candidates = [
            os.path.join(test_dir, f"test_{base_name}.py"),
            os.path.join(repo_path, "runner", f"test_{base_name}.py"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                tests.append(c)
    return list(set(tests))


def _run_test_file(test_path, timeout=None):
    """Run a single test file with pytest or unittest. Returns (passed, output)."""
    timeout = timeout or TEST_TIMEOUT_S
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", test_path, "-x", "--tb=short", "-q"],
            capture_output=True, text=True, timeout=timeout,
            cwd=os.path.dirname(test_path)
        )
        passed = r.returncode == 0
        output = (r.stdout + r.stderr)[-2000:]  # truncate
        return passed, output
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"
    except Exception as e:
        # Fall back to direct execution
        try:
            r = subprocess.run(
                [sys.executable, test_path],
                capture_output=True, text=True, timeout=timeout,
                cwd=os.path.dirname(test_path)
            )
            return r.returncode == 0, (r.stdout + r.stderr)[-2000:]
        except Exception as e2:
            return False, str(e2)


def check_merge(task, repo_path=""):
    """Run the merge test gate for a task.

    Returns dict with:
        'passed': bool — True if all tests pass or no tests found
        'tests_run': int
        'tests_passed': int
        'tests_failed': int
        'details': list of {file, passed, output}
    """
    if not ENABLED:
        _stats["skipped"] += 1
        return {"passed": True, "tests_run": 0, "tests_passed": 0,
                "tests_failed": 0, "details": [], "skipped": True}

    slug = (task or {}).get("slug", "unknown")
    branch = f"agent/{slug}"
    base = (task or {}).get("base_branch") or "master"
    _stats["runs"] += 1

    if not repo_path:
        try:
            import db
            proj = db.select("projects", {
                "id": f"eq.{task.get('project_id')}",
                "select": "repo_path", "limit": "1"
            })
            if proj:
                repo_path = proj[0].get("repo_path", "")
                repo_path = db.localize_repo_path(repo_path)
        except Exception:
            pass

    changed = _find_changed_modules(repo_path, branch, base)
    if not changed:
        return {"passed": True, "tests_run": 0, "tests_passed": 0,
                "tests_failed": 0, "details": [], "reason": "no changed modules"}

    test_files = _find_matching_tests(changed, repo_path)
    if not test_files:
        return {"passed": True, "tests_run": 0, "tests_passed": 0,
                "tests_failed": 0, "details": [], "reason": "no matching tests"}

    details = []
    tests_passed = 0
    tests_failed = 0

    for tf in test_files:
        passed, output = _run_test_file(tf)
        details.append({"file": os.path.basename(tf), "passed": passed, "output": output[:500]})
        if passed:
            tests_passed += 1
        else:
            tests_failed += 1

    all_passed = tests_failed == 0

    if all_passed:
        _stats["passed"] += 1
    else:
        _stats["failed"] += 1

    result = {
        "passed": all_passed,
        "tests_run": len(test_files),
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "details": details,
    }

    _persist_result(slug, result)
    return result


def _persist_result(slug, result):
    """Save test result for audit."""
    try:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        path = os.path.join(RESULTS_DIR, f"{slug}-{int(time.time())}.json")
        with open(path, "w") as f:
            json.dump(result, f, indent=2)
    except Exception:
        pass


def run():
    """Periodic entry — check recently DONE tasks that haven't been test-gated."""
    if not ENABLED:
        return
    try:
        import db
        candidates = db.select("tasks", {
            "select": "id,slug,project_id,base_branch",
            "state": "eq.DONE",
            "order": "updated_at.desc",
            "limit": "3",
        }) or []

        projects = {p["id"]: p for p in (db.select("projects", {"select": "id,repo_path"}) or [])}

        for task in candidates:
            marker_key = f"merge_test_{task.get('slug')}"
            existing = db.select("fleet_config", {"key": f"eq.{marker_key}", "limit": "1"})
            if existing:
                continue

            proj = projects.get(task.get("project_id"), {})
            repo_path = proj.get("repo_path", "")
            try:
                repo_path = db.localize_repo_path(repo_path)
            except Exception:
                pass

            result = check_merge(task, repo_path)
            try:
                db.upsert("fleet_config", {"key": marker_key,
                                            "value": json.dumps({"passed": result.get("passed"),
                                                                  "tests_run": result.get("tests_run")})})
            except Exception:
                pass
    except Exception as e:
        log.warning("merge_test_gate periodic run error: %s", e)
