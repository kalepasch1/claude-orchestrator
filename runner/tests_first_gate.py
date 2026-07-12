#!/usr/bin/env python3
"""
tests_first_gate.py - when a task's `proof` references a test file that does not
yet exist, split it into two tasks:
  1. A depends-first "author the failing test" task
  2. The implementation task that depends on the test task

This ensures the test is written before (and by a different unit of work than) the
implementation that must pass it.

Does NOT split when:
  - proof references an existing test file
  - proof is a build command (no test file path detected)
  - proof is empty
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Matches file paths that look like test files in proof strings
_TEST_FILE_RE = re.compile(
    r"""(?:^|[\s`"'])"""                    # boundary
    r"""((?:[\w./\\-]+/)?"""                # optional dir prefix
    r"""test_[\w.-]+\.py)"""                # test_*.py filename
    r"""(?:[\s`"']|$)""",                   # boundary
    re.I
)


def _extract_test_file(proof):
    """Extract a test file path from a proof string, or None."""
    if not proof:
        return None
    m = _TEST_FILE_RE.search(proof)
    return m.group(1) if m else None


def _test_file_exists(test_path, repo_path=None):
    """Check if a test file exists relative to repo_path or as absolute."""
    if not test_path:
        return False
    if os.path.isabs(test_path) and os.path.isfile(test_path):
        return True
    if repo_path:
        full = os.path.join(repo_path, test_path)
        if os.path.isfile(full):
            return True
        # Also check under runner/ prefix
        full2 = os.path.join(repo_path, "runner", test_path)
        if os.path.isfile(full2):
            return True
    return False


def split_if_needed(task, repo_path=None):
    """Given a task dict, return a list of tasks.

    If the task's proof references a test file that does NOT exist, return two tasks:
      [test_task, impl_task_with_dep]
    Otherwise return [task] unchanged.
    """
    proof = task.get("proof") or ""
    test_file = _extract_test_file(proof)

    if not test_file:
        # No test file in proof (it's a build command or empty) — no split
        return [task]

    if _test_file_exists(test_file, repo_path):
        # Test file already exists — no split needed
        return [task]

    # Split: create a "write test" task that the impl depends on
    slug = task.get("slug") or "unknown"
    test_slug = f"{slug}-write-tests"

    test_task = dict(task)
    test_task["slug"] = test_slug
    test_task["prompt"] = (
        f"Write the failing test file `{test_file}` for task '{slug}'.\n\n"
        f"Original proof: {proof}\n\n"
        f"Write comprehensive failing tests that define the acceptance criteria. "
        f"Do NOT implement the feature — only the tests."
    )
    test_task["kind"] = "test"
    # test task inherits the original task's deps
    test_task["deps"] = list(task.get("deps") or [])

    impl_task = dict(task)
    # impl task depends on the test task + its original deps
    orig_deps = list(task.get("deps") or [])
    if test_slug not in orig_deps:
        orig_deps.append(test_slug)
    impl_task["deps"] = orig_deps

    return [test_task, impl_task]


def apply_gate(tasks, repo_path=None):
    """Apply the tests-first gate to a list of tasks. Returns the (possibly expanded) list."""
    result = []
    for t in tasks:
        result.extend(split_if_needed(t, repo_path))
    return result
