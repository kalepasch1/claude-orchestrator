"""
test_impact — map changed files to affected test files.

Pure function: no git history rewriting, no subprocess calls.
Accepts the output of `git diff --name-only` (a list of paths)
and returns the list of test files that should be re-run.

Part of the test-impact-incremental-build initiative (sub-task 1).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Set


def changed_files_to_tests(
    changed: List[str],
    repo_root: Optional[str] = None,
) -> List[str]:
    """Map changed file paths to affected test file paths.

    Uses simple path heuristics:
      runner/foo.py        -> tests/test_foo.py
      server/bar.py        -> tests/test_bar.py
      triage/baz.py        -> triage/tests/test_baz.py
      tests/test_*.py      -> itself (already a test)

    Returns a sorted, deduplicated list of test file paths.
    If *repo_root* is given, only tests that actually exist on disk
    are returned; otherwise all inferred paths are returned.
    """
    tests: Set[str] = set()

    for path in changed:
        path = path.strip()
        if not path or not path.endswith(".py"):
            continue

        # Already a test file — include directly
        if _is_test_file(path):
            tests.add(path)
            continue

        # Infer candidate test paths
        candidates = _infer_test_paths(path)
        for candidate in candidates:
            if repo_root is not None:
                full = os.path.join(repo_root, candidate)
                if os.path.isfile(full):
                    tests.add(candidate)
            else:
                tests.add(candidate)

    return sorted(tests)


def _is_test_file(path: str) -> bool:
    """Return True if *path* looks like a test file."""
    basename = os.path.basename(path)
    return basename.startswith("test_") or basename.endswith("_test.py")


def _infer_test_paths(path: str) -> List[str]:
    """Return candidate test file paths for a given source file."""
    parts = Path(path).parts
    basename = parts[-1]
    stem = basename.replace(".py", "")
    candidates: List[str] = []

    if len(parts) >= 2:
        top_dir = parts[0]

        # runner/foo.py  -> tests/test_foo.py
        # server/bar.py  -> tests/test_bar.py
        if top_dir in ("runner", "server", "web", "packages", "scripts"):
            candidates.append(f"tests/test_{stem}.py")

        # triage/baz.py -> triage/tests/test_baz.py
        if top_dir == "triage":
            candidates.append(f"triage/tests/test_{stem}.py")

        # Also try a direct mirror: <dir>/tests/test_<stem>.py
        candidates.append(str(Path(top_dir) / "tests" / f"test_{stem}.py"))

    # Fallback: tests/test_<stem>.py
    fallback = f"tests/test_{stem}.py"
    if fallback not in candidates:
        candidates.append(fallback)

    return candidates
