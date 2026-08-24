#!/usr/bin/env python3
"""Regression guard: no tracked .py file may carry unresolved git conflict markers.

WHY THIS EXISTS. Four files shipped to master with literal `<<<<<<< HEAD` /
`>>>>>>> agent/...` hunks still in them:

    hisanta/__init__.py
    hisanta/contracts/family.py
    hisanta/hisanta/contracts/family.py
    hisanta/hisanta/mastery/engine.py

A conflict marker is a SyntaxError, so the `hisanta` package could not be imported at
all and pytest aborted collection of tests/test_gifting_protocol.py,
tests/test_kindness_mint.py and tests/test_school_mode.py — 23 tests that reported as
"3 errors during collection", not as failures, and so were invisible in a pass/fail
count. Every full-suite run on this repo was interrupted by it.

runner/conflict_marker_sentinel.py already *detects* this class and files a remediation
task, but detection that only enqueues work does not stop the markers reaching master.
This test fails the suite instead, which is the check the class was missing.

Deliberately narrow: only the conflict-start marker, only at the start of a line, only
in tracked Python files. A string literal that happens to contain "<<<<<<<" mid-line
(runner/tests/* build such fixtures on purpose) is not matched.
"""
import os
import re
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: `<<<<<<< ` at column 0. The trailing space is load-bearing: it distinguishes a real
#: marker from a line of seven angle brackets in ASCII art or a regex.
_MARKER_RE = re.compile(r"^<<<<<<< ", re.MULTILINE)

#: Fixture modules that construct marker text on purpose to test the detectors.
#: They contain markers only inside string literals, never at column 0, so they are
#: matched by the regex nowhere — listed here only so a future reader does not
#: "helpfully" add a blanket exemption for them.
_KNOWN_MARKER_AUTHORS = (
    "runner/conflict_marker_sentinel.py",
    "runner/tests/test_runner_conflict_free.py",
    "runner/tests/test_isolated_merge_promotion.py",
)


def _tracked_python_files():
    """Tracked .py paths, or [] when git is unavailable (fail-soft, never raises)."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.py"], cwd=REPO,
            capture_output=True, text=True, timeout=60,
        )
    except Exception as e:  # pragma: no cover - environment without git
        sys.stderr.write(f"[test_no_conflict_markers] git ls-files failed: {e}\n")
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


class TestNoConflictMarkers(unittest.TestCase):
    def test_no_tracked_python_file_carries_a_conflict_marker(self):
        offenders = []
        for rel in _tracked_python_files():
            path = os.path.join(REPO, rel)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except Exception:
                continue
            if _MARKER_RE.search(text):
                offenders.append(rel)
        self.assertEqual(
            offenders, [],
            "unresolved git conflict markers in tracked Python files — these are "
            "SyntaxErrors and abort pytest collection for every module that imports "
            "them: " + ", ".join(offenders),
        )

    def test_the_hisanta_package_imports(self):
        """The concrete failure this task repaired, asserted directly."""
        sys.path.insert(0, REPO)
        import importlib
        family = importlib.import_module("hisanta.contracts.family")
        nested = importlib.import_module("hisanta.hisanta.contracts.family")
        # One definition, reached by two spellings: an isinstance or enum-identity
        # check must not depend on which path the caller used to get here.
        for name in family.__all__:
            self.assertIs(getattr(nested, name), getattr(family, name), name)

    def test_marker_regex_ignores_inline_occurrences(self):
        self.assertIsNone(_MARKER_RE.search('S = "a<<<<<<< inline"'))
        self.assertIsNotNone(_MARKER_RE.search("x = 1\n<<<<<<< HEAD\n"))


if __name__ == "__main__":
    unittest.main()
