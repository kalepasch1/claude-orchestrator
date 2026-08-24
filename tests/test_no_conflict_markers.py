#!/usr/bin/env python3
"""Guard: no tracked Python file may carry git conflict markers.

WHY THIS CHECK EXISTS. Four tracked files (hisanta/__init__.py, both copies of
contracts/family.py, hisanta/hisanta/mastery/engine.py) were committed to master with
literal `<<<<<<<` / `=======` / `>>>>>>>` in them. Each is a SyntaxError, and a
SyntaxError in an imported module fails pytest at COLLECTION — pytest then aborts with
"Interrupted: N errors during collection" and every other test in that invocation stops
reporting. So a bad merge did not cost four files; it silenced the run.

Nothing caught it because the failure is not a failing test, it is the absence of a run.
This test turns it into one visible red line.

Scoped to *.py because that is where a marker is a hard syntax failure; a stray marker in
a markdown doc is untidy, not load-bearing, and flagging it would make the guard noisy
enough to be ignored.
"""
import os
import subprocess
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Excluded on purpose:
#   _to_delete/  — a holding pen for removed trees, not importable code
#   fixtures/    — a conflicted diff can be legitimate TEST DATA for patch tooling
_EXCLUDED_PREFIXES = ("_to_delete/", "tests/fixtures/", "runner/tests/fixtures/")

_MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")


def _tracked_python_files():
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=_ROOT, capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return []
    return [p for p in out.stdout.split("\0")
            if p and not p.startswith(_EXCLUDED_PREFIXES)]


def _conflicted(path):
    """A file is conflicted when it opens a marker AND closes one — the pair is what
    makes it a real conflict rather than, say, a `=======` underline inside a docstring."""
    full = os.path.join(_ROOT, path)
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return False
    opened = any(line.startswith(_MARKERS[0]) for line in lines)
    closed = any(line.startswith(_MARKERS[2]) for line in lines)
    return opened and closed


class NoConflictMarkersTest(unittest.TestCase):
    def test_no_tracked_python_file_carries_conflict_markers(self):
        files = _tracked_python_files()
        if not files:
            self.skipTest("not a git checkout (git ls-files returned nothing)")
        offenders = [path for path in files if _conflicted(path)]
        self.assertEqual(offenders, [], (
            "unresolved git conflict markers in tracked python files — these are "
            "SyntaxErrors and will abort pytest collection for the whole run: "
            + ", ".join(offenders)))

    def test_the_detector_actually_detects(self):
        """A guard nobody has seen fire is a guard nobody can trust."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "conflicted.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("<<<<<<< HEAD\nx = 1\n=======\nx = 2\n>>>>>>> other\n")
            global _ROOT
            original, _ROOT = _ROOT, tmp
            try:
                self.assertTrue(_conflicted("conflicted.py"))
            finally:
                _ROOT = original

    def test_an_equals_underline_alone_is_not_a_conflict(self):
        """reStructuredText underlines and separator comments must not trip the guard."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clean.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('"""Title\n=======\n"""\nx = 1\n')
            global _ROOT
            original, _ROOT = _ROOT, tmp
            try:
                self.assertFalse(_conflicted("clean.py"))
            finally:
                _ROOT = original


if __name__ == "__main__":
    unittest.main()
