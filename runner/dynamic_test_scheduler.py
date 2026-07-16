#!/usr/bin/env python3
"""
dynamic_test_scheduler.py – CI/CD dynamic test scheduling based on code changes.

Analyzes git diffs to determine which test files are relevant for a given change,
prioritizes tests by recency of failure and proximity to changed code, and
generates optimized test execution plans.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.
"""
import os, sys, re, json, datetime, threading, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_TESTS_PER_RUN = int(os.environ.get("ORCH_MAX_TESTS_PER_RUN", "20"))

_lock = threading.Lock()
_STATE = {
    "last_schedule": None,
    "schedules_generated": 0,
}


def _changed_files(repo_path, base="master"):
    """Get list of changed files relative to base branch."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base, "HEAD"],
            capture_output=True, text=True, cwd=repo_path, timeout=10,
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except (subprocess.TimeoutExpired, OSError):
        return []


def _map_source_to_tests(changed_files):
    """
    Map changed source files to their corresponding test files.

    Strategy:
    - runner/foo.py -> runner/test_foo.py
    - Any config change -> run all config tests
    - Package.json/tsconfig changes -> run build tests
    """
    test_files = set()
    for f in changed_files:
        base = os.path.basename(f)
        dirname = os.path.dirname(f)

        if base.startswith("test_"):
            test_files.add(f)
            continue

        if f.startswith("runner/") and f.endswith(".py"):
            mod_name = base[:-3]
            candidate = os.path.join("runner", f"test_{mod_name}.py")
            if os.path.exists(os.path.join(RUNNER_DIR, "..", candidate)):
                test_files.add(candidate)

        if "config" in base.lower():
            for tf in os.listdir(RUNNER_DIR):
                if tf.startswith("test_config") and tf.endswith(".py"):
                    test_files.add(os.path.join("runner", tf))

        if base in ("package.json", "tsconfig.json"):
            for tf in os.listdir(RUNNER_DIR):
                if tf.startswith("test_build") and tf.endswith(".py"):
                    test_files.add(os.path.join("runner", tf))

    return sorted(test_files)


def _prioritize_tests(test_files, failure_history=None):
    """
    Prioritize test files by:
    1. Recently failed tests (highest priority)
    2. Tests for frequently changed modules
    3. Alphabetical (stable ordering)
    """
    scores = {}
    failure_history = failure_history or {}

    for tf in test_files:
        score = 0
        if tf in failure_history:
            recency = failure_history[tf].get("last_failed_days_ago", 999)
            if recency < 1:
                score += 100
            elif recency < 7:
                score += 50
            else:
                score += 10
            score += failure_history[tf].get("fail_count", 0) * 5
        scores[tf] = score

    return sorted(test_files, key=lambda f: (-scores.get(f, 0), f))


def schedule(repo_path=None, base="master", failure_history=None):
    """
    Generate a test execution plan for the current branch changes.

    Returns dict with:
      - changed_files: list of modified files
      - scheduled_tests: prioritized list of test files to run
      - skipped_tests: tests beyond MAX_TESTS_PER_RUN limit
      - estimated_time_sec: rough estimate based on test count
    """
    if repo_path is None:
        repo_path = os.path.dirname(RUNNER_DIR)

    changed = _changed_files(repo_path, base)
    mapped_tests = _map_source_to_tests(changed)
    prioritized = _prioritize_tests(mapped_tests, failure_history)

    scheduled = prioritized[:MAX_TESTS_PER_RUN]
    skipped = prioritized[MAX_TESTS_PER_RUN:]

    result = {
        "changed_files": changed,
        "changed_count": len(changed),
        "scheduled_tests": scheduled,
        "scheduled_count": len(scheduled),
        "skipped_tests": skipped,
        "skipped_count": len(skipped),
        "estimated_time_sec": len(scheduled) * 5,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    with _lock:
        _STATE["last_schedule"] = result["generated_at"]
        _STATE["schedules_generated"] += 1

    return result


def schedule_for_slug(slug, repo_path=None, base="master"):
    """
    Generate test schedule for a specific task branch.

    Checks out the branch info without switching, compares against base.
    """
    if repo_path is None:
        repo_path = os.path.dirname(RUNNER_DIR)

    branch = f"agent/{slug}"
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base, branch],
            capture_output=True, text=True, cwd=repo_path, timeout=10,
        )
        if result.returncode != 0:
            return {"error": f"cannot diff {branch} against {base}"}
        changed = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"error": str(e)}

    mapped = _map_source_to_tests(changed)
    prioritized = _prioritize_tests(mapped)

    return {
        "slug": slug,
        "branch": branch,
        "changed_files": changed,
        "scheduled_tests": prioritized[:MAX_TESTS_PER_RUN],
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def stats():
    """Return cached scheduler state."""
    with _lock:
        return dict(_STATE)


def run():
    """Entry point for orchestrator periodic jobs."""
    result = schedule()
    return result


if __name__ == "__main__":
    print(json.dumps(schedule(), indent=2))
