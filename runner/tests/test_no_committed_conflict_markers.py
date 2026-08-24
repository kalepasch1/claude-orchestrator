#!/usr/bin/env python3
"""No tracked file may contain unresolved merge-conflict markers.

Four files were committed to master WITH THEIR CONFLICT MARKERS STILL IN THEM. Each is a
SyntaxError, so importing any of them takes out collection of everything downstream:
tests/test_gifting_protocol.py, tests/test_kindness_mint.py and tests/test_school_mode.py
have all been erroring at COLLECTION — not failing, erroring, which is why they show up in
smoke-failures.json as `<collection> ERROR` with no test name.

A collection error is the most expensive kind of red, because pytest reports it once and
the tests inside it never run at all — they are not counted as failures, so the suite can
look like it is merely "3 errors" while an entire domain is unexercised.

This guard is deliberately cheap and repo-wide: a conflict marker in a tracked file is
never intentional, and the check costs one `git grep`.

Proof: python3 -m pytest runner/tests/test_no_committed_conflict_markers.py -q
"""
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Anchored at line start, which is how git writes them. A `=======` underline in
#: markdown is NOT a conflict marker, so only the two unambiguous forms are matched.
MARKERS = ("^<<<<<<< ", "^>>>>>>> ")

#: Files whose conflicts are a genuine design merge, not a mechanical one, and which are
#: handed off as their own task rather than guessed at. THIS LIST MAY ONLY SHRINK.
#: See the note in the failure message below.
KNOWN_UNRESOLVED = (
    "hisanta/contracts/family.py",
    "hisanta/hisanta/contracts/family.py",
    "hisanta/hisanta/mastery/engine.py",
)


def _files_with(marker):
    try:
        out = subprocess.run(["git", "grep", "-l", marker], cwd=REPO,
                             capture_output=True, text=True, timeout=120)
    except Exception:
        return []
    if out.returncode not in (0, 1):
        return []
    return sorted(p for p in out.stdout.splitlines()
                  if p and "node_modules" not in p and not p.endswith(
                      "test_no_committed_conflict_markers.py"))


def _offenders():
    seen = set()
    for marker in MARKERS:
        seen.update(_files_with(marker))
    return sorted(seen)


class TestNoConflictMarkers(unittest.TestCase):
    def test_no_new_file_carries_conflict_markers(self):
        unexpected = [p for p in _offenders() if p not in KNOWN_UNRESOLVED]
        self.assertEqual(
            [], unexpected,
            "tracked files contain unresolved conflict markers: "
            + "; ".join(unexpected)
            + ". A committed marker is a SyntaxError in Python and takes out COLLECTION "
              "of every test that imports the module — those tests do not run and are "
              "not counted as failures.")

    def test_the_known_list_only_shrinks(self):
        """A file that has been resolved must be removed from KNOWN_UNRESOLVED, or the
        guard silently stops protecting it."""
        offenders = set(_offenders())
        stale = [p for p in KNOWN_UNRESOLVED if p not in offenders]
        self.assertEqual([], stale,
                         "these are clean now — drop them from KNOWN_UNRESOLVED: "
                         + "; ".join(stale))

    def test_the_check_is_not_vacuous(self):
        """Guard the guard: if `git grep` stops working the check must fail loudly
        rather than pass by finding nothing."""
        self.assertTrue(_files_with("^<<<<<<< ") or _files_with("^>>>>>>> ")
                        or not KNOWN_UNRESOLVED,
                        "git grep returned nothing at all; the scan is broken")


class TestPackageInitIsImportable(unittest.TestCase):
    """The one conflict this task resolved: hisanta/__init__.py."""

    def test_it_parses(self):
        import ast
        path = os.path.join(REPO, "hisanta", "__init__.py")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            ast.parse(fh.read())          # raises SyntaxError if a marker returns

    def test_it_has_no_markers(self):
        self.assertNotIn("hisanta/__init__.py", _offenders())

    def test_it_still_extends_the_path_over_the_nested_tree(self):
        """Both sides of that conflict were doing this; the resolution must keep it."""
        path = os.path.join(REPO, "hisanta", "__init__.py")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        self.assertIn("__path__.append", source)
        self.assertIn("globals()", source,
                      "the explicit __path__ bind was what satisfied the pyflakes "
                      "undefined-name guard; do not revert it to a bare append")


if __name__ == "__main__":
    unittest.main()
