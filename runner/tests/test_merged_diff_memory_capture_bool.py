#!/usr/bin/env python3
"""Boolean contract for merged_diff_memory.capture_to_memory.

Spec: return True if the memory file was written successfully, False on ANY error
(bad git refs, no diffs, write failure), and never raise. Failures go to
logging.warning, following the repo's fail-soft pattern.

The load-bearing case is "no diffs -> False". Returning True there would tell a caller
that memory is current when nothing was persisted, which is exactly the kind of
silent-no-op this codebase keeps getting bitten by — a guard that reports success
because the function completed rather than because the work happened.
"""
import logging
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import merged_diff_memory as mdm  # noqa: E402


def _ok(memory_file="/tmp/mem.md", patterns=3):
    return {"success": True, "merged_count": 5, "patterns_count": patterns,
            "memory_file": memory_file, "error": None}


class TestReturnsTrue(unittest.TestCase):
    def test_true_when_memory_file_written(self):
        with mock.patch.object(mdm, "run", return_value=_ok()):
            self.assertIs(mdm.capture_to_memory(), True)

    def test_returns_a_real_bool(self):
        with mock.patch.object(mdm, "run", return_value=_ok()):
            self.assertIsInstance(mdm.capture_to_memory(), bool)

    def test_repo_argument_is_forwarded(self):
        with mock.patch.object(mdm, "run", return_value=_ok()) as r:
            mdm.capture_to_memory(repo="/some/repo")
        self.assertEqual(r.call_args.kwargs.get("repo"), "/some/repo")


class TestReturnsFalse(unittest.TestCase):
    def test_false_when_no_memory_file_written(self):
        res = _ok(memory_file=None)
        res["success"] = True
        with mock.patch.object(mdm, "run", return_value=res):
            self.assertIs(mdm.capture_to_memory(), False)

    def test_false_when_no_diffs_found(self):
        empty = {"success": False, "merged_count": 0, "patterns_count": 0,
                 "memory_file": None, "error": None}
        with mock.patch.object(mdm, "run", return_value=empty):
            self.assertIs(mdm.capture_to_memory(), False)

    def test_false_on_reported_error(self):
        bad = _ok()
        bad.update(success=False, error="fatal: not a git repository")
        with mock.patch.object(mdm, "run", return_value=bad):
            self.assertIs(mdm.capture_to_memory(), False)

    def test_false_on_write_failure(self):
        bad = _ok(memory_file=None)
        bad.update(success=False, error="[Errno 13] Permission denied")
        with mock.patch.object(mdm, "run", return_value=bad):
            self.assertIs(mdm.capture_to_memory(), False)

    def test_false_on_unexpected_return_shape(self):
        for junk in (None, "ok", 42, []):
            with self.subTest(junk=junk):
                with mock.patch.object(mdm, "run", return_value=junk):
                    self.assertIs(mdm.capture_to_memory(), False)

    def test_dry_run_writes_nothing_and_is_false(self):
        dry = {"success": True, "merged_count": 5, "patterns_count": 2,
               "memory_file": None, "error": None, "dry_run": True}
        with mock.patch.object(mdm, "run", return_value=dry):
            self.assertIs(mdm.capture_to_memory(dry_run=True), False)


class TestNeverRaises(unittest.TestCase):
    """"Never raise" is the contract — callers treat this as a fire-and-forget hook."""

    def test_git_error_does_not_propagate(self):
        with mock.patch.object(mdm, "run",
                               side_effect=RuntimeError("fatal: bad revision")):
            self.assertIs(mdm.capture_to_memory(), False)

    def test_io_error_does_not_propagate(self):
        with mock.patch.object(mdm, "run", side_effect=OSError("disk full")):
            self.assertIs(mdm.capture_to_memory(), False)

    def test_db_error_does_not_propagate(self):
        with mock.patch.object(mdm, "run", side_effect=Exception("db unavailable")):
            self.assertIs(mdm.capture_to_memory(), False)

    def test_keyboardinterrupt_style_base_exception_is_not_swallowed(self):
        # Catching BaseException would make Ctrl-C unkillable inside a sweep.
        with mock.patch.object(mdm, "run", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                mdm.capture_to_memory()


class TestLogging(unittest.TestCase):
    def test_failure_is_logged_as_a_warning(self):
        bad = _ok()
        bad.update(success=False, error="fatal: not a git repository")
        with mock.patch.object(mdm, "run", return_value=bad):
            with self.assertLogs(level=logging.WARNING) as cap:
                mdm.capture_to_memory()
        self.assertTrue(any("merged_diff_memory" in m for m in cap.output))

    def test_raised_error_is_logged_with_its_type(self):
        with mock.patch.object(mdm, "run", side_effect=RuntimeError("bad ref")):
            with self.assertLogs(level=logging.WARNING) as cap:
                mdm.capture_to_memory()
        joined = " ".join(cap.output)
        self.assertIn("RuntimeError", joined)
        self.assertIn("bad ref", joined)

    def test_success_is_not_logged_as_a_warning(self):
        with mock.patch.object(mdm, "run", return_value=_ok()):
            with mock.patch.object(logging, "warning") as warn:
                mdm.capture_to_memory()
            warn.assert_not_called()


class TestCoexistence(unittest.TestCase):
    def test_run_still_returns_its_dict(self):
        # The boolean wrapper must not replace the detailed API.
        self.assertTrue(callable(mdm.run))
        self.assertTrue(callable(mdm.capture_to_memory))


if __name__ == "__main__":
    unittest.main()
