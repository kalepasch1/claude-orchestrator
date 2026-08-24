"""Fail if unresolved merge-conflict markers are committed.

runner/config_consumer.py was left with conflict markers once, and the cost was
not the broken module — it was that nothing noticed. A file with `<<<<<<<` in it
does not import, so every consumer fails with a SyntaxError far from the cause,
and the queue fills with tasks to re-diagnose the same thing. (This session
alone adjudicated eight separate tasks whose premise was "resolve the conflict
in <file>", all of which turned out to be already resolved.)

Scope is the tracked tree, not just the one file that triggered it: the failure
mode is not specific to config_consumer.py, and a check that only guards the
file that already broke would not have caught it the first time.
"""
import os
import re
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Anchored to line start, and `=======` needs its own rule: a bare run of equals
# signs is legitimate in markdown underlines and ASCII art, so it only counts as
# a conflict when the file also carries a real `<<<<<<<` opener.
_OPEN = re.compile(r"^<<<<<<< ", re.M)
_CLOSE = re.compile(r"^>>>>>>> ", re.M)
_MID = re.compile(r"^=======\s*$", re.M)

# Files that legitimately contain marker-looking text: this test describes them,
# and the repo's own docs explain the recovery procedure.
_ALLOWED = {
    "runner/tests/test_no_unresolved_conflict_markers.py",
}
_ALLOWED_SUFFIXES = (".md",)

# KNOWN-BROKEN, recorded 2026-08-24 by the check that found them.
#
# These four ARE genuinely conflicted on master — committed in cb4065c8
# ("chore: commit the in-flight tree") — and they are why `pytest tests/` currently
# dies during collection with `SyntaxError: invalid syntax` on a bare `=======`.
# They are listed rather than fixed here because resolving someone's in-flight
# vendored subtree is not "add a regression check", and picking a side needs the
# author: in hisanta/__init__.py, for instance, both sides append the nested dir
# to __path__ and differ only in docstring and abspath usage.
#
# They are NOT silently exempt: test_the_known_broken_set_is_still_exactly_this
# fails if the list drifts in either direction, so fixing one forces the list to
# shrink and a new conflict anywhere else fails the repo-wide check immediately.
_KNOWN_BROKEN = {
    "hisanta/__init__.py",
    "hisanta/contracts/family.py",
    "hisanta/hisanta/contracts/family.py",
    "hisanta/hisanta/mastery/engine.py",
}


def _tracked_text_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, text=True, timeout=120)
    for path in out.stdout.split("\0"):
        if not path or path in _ALLOWED or path.endswith(_ALLOWED_SUFFIXES):
            continue
        full = os.path.join(REPO, path)
        try:
            if os.path.getsize(full) > 4_000_000:
                continue
            with open(full, encoding="utf-8", errors="strict") as fh:
                yield path, fh.read()
        except (OSError, UnicodeDecodeError):
            continue          # binary or unreadable: not our concern


def _conflicted(text):
    """True when `text` carries a real, unresolved conflict hunk."""
    if not _OPEN.search(text):
        return False
    return bool(_CLOSE.search(text) or _MID.search(text))


class TestNoUnresolvedConflictMarkers(unittest.TestCase):
    def test_config_consumer_has_no_conflict_markers(self):
        # The specific file this regression is named for.
        path = os.path.join(REPO, "runner", "config_consumer.py")
        with open(path, encoding="utf-8") as fh:
            self.assertFalse(_conflicted(fh.read()),
                             "runner/config_consumer.py has unresolved conflict markers")

    def test_no_new_tracked_file_has_conflict_markers(self):
        bad = sorted(path for path, text in _tracked_text_files()
                     if _conflicted(text) and path not in _KNOWN_BROKEN)
        self.assertEqual(bad, [], f"unresolved conflict markers in: {bad}")

    def test_the_known_broken_set_is_still_exactly_this(self):
        # Keeps the exemption honest in both directions: a fixed file must be
        # removed from the list, and the list can never quietly absorb a new one.
        found = {path for path, text in _tracked_text_files() if _conflicted(text)}
        self.assertEqual(found, _KNOWN_BROKEN & found,
                         "a conflicted file is not in the known-broken list")
        stale = _KNOWN_BROKEN - found
        self.assertEqual(stale, set(),
                         f"these are fixed — drop them from _KNOWN_BROKEN: {sorted(stale)}")

    def test_the_detector_fires_on_a_reintroduced_conflict(self):
        # The check is worthless unless it can go red; prove it does.
        conflicted = (
            "def f():\n"
            "<<<<<<< HEAD\n"
            "    return 1\n"
            "=======\n"
            "    return 2\n"
            ">>>>>>> other\n"
        )
        self.assertTrue(_conflicted(conflicted))

    def test_the_detector_ignores_markdown_underlines(self):
        # A bare ======= row is normal in markdown/ASCII art; flagging it would
        # make the guard noisy and it would get disabled.
        self.assertFalse(_conflicted("Title\n=======\n\nbody text\n"))
        self.assertFalse(_conflicted("a = 1  # ======= separator\n"))

    def test_the_detector_requires_a_line_start_opener(self):
        self.assertFalse(_conflicted('note = "<<<<<<< not a real marker"\n'))

    def test_the_detector_needs_more_than_a_lone_opener(self):
        # A lone `<<<<<<<` with no midpoint or closer is not a conflict hunk.
        self.assertFalse(_conflicted("<<<<<<< stray\n"))


if __name__ == "__main__":
    unittest.main()
