#!/usr/bin/env python3
"""The redo-cap-exhausted note must be actionable, not just true.

`runner/config_consumer.py` sat conflicted through six remediations behind the note
"train: still conflicts after 2 redos - needs manual rebase." That note is accurate and
useless: it does not say what to run, and the sibling path in approval_merge did not
even name the file. These tests pin the three things the note now always carries —
redo count vs cap, the exact conflicting files, and a copy-pasteable rebase command.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import conflict_exhaustion as ce  # noqa: E402


class NoteContentTest(unittest.TestCase):
    def _note(self, **overrides):
        kwargs = dict(prefix="train", redos=2, cap=2, branch="agent/foo", base="master",
                      repo="/repo", files="runner/config_consumer.py")
        kwargs.update(overrides)
        return ce.note(**kwargs)

    def test_it_reports_the_redo_count_and_the_cap(self):
        self.assertIn("after 2 of 2 redos", self._note())

    def test_it_names_the_conflicting_file(self):
        self.assertIn("runner/config_consumer.py", self._note())

    def test_it_gives_a_pasteable_command(self):
        self.assertIn("git -C /repo rebase master agent/foo", self._note())

    def test_it_keeps_the_callers_prefix_so_log_greps_still_match(self):
        self.assertTrue(self._note().startswith("train: "))
        self.assertTrue(self._note(prefix="merge-handler").startswith("merge-handler: "))

    def test_it_still_says_needs_manual_rebase(self):
        """The phrase existing dashboards and operator habits key on."""
        self.assertIn("needs manual rebase", self._note())

    def test_it_says_raising_the_cap_is_not_the_fix(self):
        self.assertIn("raising the redo cap will not either", self._note())

    def test_multiple_files_are_all_listed(self):
        note = self._note(files="a.py\nb.py\nc.py")
        for name in ("a.py", "b.py", "c.py"):
            self.assertIn(name, note)

    def test_a_long_file_list_is_summarised_not_dumped(self):
        note = self._note(files=[f"f{i}.py" for i in range(20)])
        self.assertIn("and 14 more", note)
        self.assertLessEqual(len(note), ce.NOTE_MAX_CHARS)

    def test_missing_files_are_called_out_rather_than_silently_omitted(self):
        self.assertIn("unavailable", self._note(files=None))

    def test_the_note_fits_the_column(self):
        note = self._note(files=["x" * 200, "y" * 200], branch="b" * 100)
        self.assertLessEqual(len(note), ce.NOTE_MAX_CHARS)

    def test_duplicates_are_collapsed(self):
        note = self._note(files="a.py\na.py\nb.py")
        self.assertEqual(note.count("a.py"), 1)

    def test_a_comma_separated_string_is_accepted(self):
        self.assertIn("b.py", self._note(files="a.py, b.py"))


class FailSoftTest(unittest.TestCase):
    def test_note_never_raises_on_garbage(self):
        for kwargs in (
            dict(prefix=None, redos=None, cap=None, branch=None, base=None, repo=None, files=None),
            dict(prefix="", redos="two", cap="x", branch=1, base=2, repo=3, files=4),
            dict(prefix="t", redos=-1, cap=0, branch="b", base="m", repo="", files=[]),
        ):
            self.assertIsInstance(ce.note(**kwargs), str)

    def test_manual_rebase_hint_degrades_without_a_repo(self):
        self.assertIn("rebase", ce.manual_rebase_hint("", "", ""))

    def test_unmerged_files_returns_empty_for_a_missing_directory(self):
        self.assertEqual(ce.unmerged_files("/definitely/not/here"), [])

    def test_unmerged_files_returns_empty_outside_a_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ce.unmerged_files(tmp), [])


class UnmergedFilesAgainstRealGitTest(unittest.TestCase):
    """The capture must happen before `rebase --abort`; this proves it can."""

    def _git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              timeout=60)

    def test_it_names_the_file_that_actually_conflicts(self):
        with tempfile.TemporaryDirectory() as repo:
            self._git(repo, "init")
            self._git(repo, "symbolic-ref", "HEAD", "refs/heads/master")
            self._git(repo, "config", "user.email", "t@example.com")
            self._git(repo, "config", "user.name", "T")
            path = os.path.join(repo, "conflicted.py")
            with open(path, "w") as handle:
                handle.write("base\n")
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-m", "base")

            self._git(repo, "checkout", "-b", "side")
            with open(path, "w") as handle:
                handle.write("side\n")
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-m", "side")

            self._git(repo, "checkout", "master")
            with open(path, "w") as handle:
                handle.write("master\n")
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-m", "master")

            merged = self._git(repo, "merge", "side")
            self.assertNotEqual(merged.returncode, 0, "fixture failed to conflict")

            self.assertEqual(ce.unmerged_files(repo), ["conflicted.py"])
            self._git(repo, "merge", "--abort")
            # After the abort there is nothing left to name — which is exactly why the
            # capture has to happen first.
            self.assertEqual(ce.unmerged_files(repo), [])


class CallSiteWiringTest(unittest.TestCase):
    """Both givers-up must go through the shared note."""

    def _source(self, name):
        with open(os.path.join(RUNNER, name), "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def test_merge_train_uses_the_shared_note(self):
        source = self._source("merge_train.py")
        self.assertIn("conflict_exhaustion.note(", source)
        self.assertNotIn('f"train: still conflicts after {cap} redos', source)

    def test_approval_merge_uses_the_shared_note(self):
        source = self._source("approval_merge.py")
        self.assertIn("conflict_exhaustion.note(", source)
        self.assertNotIn("CONFLICT after {cap} redo attempts", source)

    def test_approval_merge_captures_files_before_aborting(self):
        source = self._source("approval_merge.py")
        capture = source.index("LAST_CONFLICT_FILES[branch] = conflict_exhaustion.unmerged_files")
        abort = source.index('"git", "rebase", "--abort"')
        self.assertLess(capture, abort,
                        "files must be captured before --abort clears the index")


if __name__ == "__main__":
    unittest.main()
