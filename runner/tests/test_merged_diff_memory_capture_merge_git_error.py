#!/usr/bin/env python3
"""Boolean contract for merged_diff_memory.capture_merge on a GIT ERROR.

Spec (slice-2): on a git error (bad ref, not a repo), a file I/O error, or a
database error, log with `logging.warning(...)` and return `False`.

`capture_merge` already honoured the file-I/O half of that contract via
`_write_memory`, but not the git half. `_safe_run` swallows the exit code and
returns "" for a bad ref, a missing repo, or a timeout, so the function used to
append a record with empty author/date/message and return True — persisting a
merge that does not exist and telling the caller memory was current.

That is the same defect the sibling capture_bool spec exists to prevent:
"a guard that reports success because the function completed rather than
because the work happened". A poisoned recovery memory is worse than an empty
one, because the poison is invisible.
"""
import json
import logging
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import merged_diff_memory as mdm  # noqa: E402


class _IsolatedMemory(unittest.TestCase):
    """Point the module's memory file at a temp dir so tests never touch real state."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig_dir = mdm.MEMORY_DIR
        self._orig_file = mdm.MERGED_DIFF_FILE
        mdm.MEMORY_DIR = tmp
        mdm.MERGED_DIFF_FILE = tmp / "merged_diff_memory.json"

    def tearDown(self):
        mdm.MEMORY_DIR = self._orig_dir
        mdm.MERGED_DIFF_FILE = self._orig_file
        self._tmp.cleanup()

    def _stored(self):
        if not mdm.MERGED_DIFF_FILE.exists():
            return []
        return json.loads(mdm.MERGED_DIFF_FILE.read_text()).get("merges", [])


class TestGitErrorReturnsFalse(_IsolatedMemory):
    """A bad ref / not-a-repo makes every git call return "" (see _safe_run)."""

    def test_returns_false_on_git_error(self):
        with mock.patch.object(mdm, "_safe_run", return_value=""):
            self.assertIs(mdm.capture_merge("deadbeef", "feature", "/not/a/repo"), False)

    def test_does_not_persist_a_phantom_merge(self):
        with mock.patch.object(mdm, "_safe_run", return_value=""):
            mdm.capture_merge("deadbeef", "feature", "/not/a/repo")
        self.assertEqual(self._stored(), [], "a merge git could not resolve must not be recorded")

    def test_logs_a_warning_naming_the_ref(self):
        with mock.patch.object(mdm, "_safe_run", return_value=""):
            with self.assertLogs(mdm.logger, level=logging.WARNING) as cm:
                mdm.capture_merge("deadbeef", "feature", "/not/a/repo")
        self.assertIn("deadbeef", "\n".join(cm.output))

    def test_never_raises(self):
        with mock.patch.object(mdm, "_safe_run", side_effect=Exception("boom")):
            try:
                mdm.capture_merge("deadbeef", "feature", "/not/a/repo")
            except Exception:
                # _safe_run itself is fail-soft in production; if a caller
                # somehow gets an exception out of capture_merge the contract
                # is broken regardless of which layer raised.
                self.fail("capture_merge must never raise")

    def test_returns_a_real_bool(self):
        with mock.patch.object(mdm, "_safe_run", return_value=""):
            self.assertIsInstance(mdm.capture_merge("deadbeef", "b", "/x"), bool)


class TestHealthyPathStillWorks(_IsolatedMemory):
    """The gate must not reject legitimate commits."""

    def test_records_and_returns_true_for_a_real_commit(self):
        with mock.patch.object(mdm, "_safe_run") as run:
            run.side_effect = ["alice", "2026-08-11T10:00:00Z", "fix: thing", "a.py\nb.py"]
            self.assertIs(mdm.capture_merge("abc123", "feature", "/repo"), True)
        stored = self._stored()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["commit"], "abc123")
        self.assertEqual(stored[0]["files_affected"], ["a.py", "b.py"])

    def test_an_empty_commit_message_is_not_a_git_error(self):
        # git allows an empty subject; author and date are what it always sets.
        with mock.patch.object(mdm, "_safe_run") as run:
            run.side_effect = ["alice", "2026-08-11T10:00:00Z", "", ""]
            self.assertIs(mdm.capture_merge("abc123", "feature", "/repo"), True)
        self.assertEqual(len(self._stored()), 1)

    def test_an_empty_file_list_is_not_a_git_error(self):
        with mock.patch.object(mdm, "_safe_run") as run:
            run.side_effect = ["alice", "2026-08-11T10:00:00Z", "msg", ""]
            self.assertIs(mdm.capture_merge("abc123", "feature", "/repo"), True)
        self.assertEqual(self._stored()[0]["files_affected"], [])

    def test_an_already_recorded_commit_still_returns_true(self):
        with mock.patch.object(mdm, "_safe_run") as run:
            run.side_effect = ["alice", "2026-08-11T10:00:00Z", "msg", "a.py"]
            mdm.capture_merge("abc123", "feature", "/repo")
        # Second call must short-circuit before any git call.
        with mock.patch.object(mdm, "_safe_run", return_value="") as run:
            self.assertIs(mdm.capture_merge("abc123", "feature", "/repo"), True)
            run.assert_not_called()
        self.assertEqual(len(self._stored()), 1)


class TestWriteFailureStillReturnsFalse(_IsolatedMemory):
    """The file-I/O half of the contract, kept green alongside the new git half."""

    def test_returns_false_when_the_write_fails(self):
        with mock.patch.object(mdm, "_safe_run") as run:
            run.side_effect = ["alice", "2026-08-11T10:00:00Z", "msg", "a.py"]
            with mock.patch.object(mdm, "_write_memory", return_value=False):
                self.assertIs(mdm.capture_merge("abc123", "feature", "/repo"), False)


if __name__ == "__main__":
    unittest.main()
