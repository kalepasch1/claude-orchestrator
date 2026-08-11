#!/usr/bin/env python3
"""Regression guard: the module logger must be BOUND.

`merged_diff_memory` called `logger.warning(...)` on three error paths
(_read_memory, _write_memory, and the capture_merge git gate) while never
binding the name. Every one of those paths therefore raised
`NameError: name 'logger' is not defined` instead of logging and returning a
fail-soft value — the branch written to keep the runner alive was the branch
that killed it.

Reproduced before the fix:
    _write_memory([...]) against an unwritable directory -> NameError, not False.
"""
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import merged_diff_memory as mdm  # noqa: E402


class TestLoggerIsBound(unittest.TestCase):
    def test_module_exposes_a_real_logger(self):
        self.assertTrue(hasattr(mdm, "logger"), "merged_diff_memory must bind a module logger")
        self.assertIsInstance(mdm.logger, logging.Logger)


class TestErrorPathsFailSoftRatherThanRaise(unittest.TestCase):
    """Each error path must LOG and return its fail-soft value."""

    def setUp(self):
        self._orig_dir = mdm.MEMORY_DIR
        self._orig_file = mdm.MERGED_DIFF_FILE

    def tearDown(self):
        mdm.MEMORY_DIR = self._orig_dir
        mdm.MERGED_DIFF_FILE = self._orig_file

    def test_write_memory_returns_false_and_logs_on_io_error(self):
        mdm.MEMORY_DIR = Path("/proc/definitely-not-writable")
        mdm.MERGED_DIFF_FILE = mdm.MEMORY_DIR / "merged_diff_memory.json"
        with self.assertLogs(mdm.logger, level=logging.WARNING):
            result = mdm._write_memory([{"commit": "abc"}])
        self.assertIs(result, False)

    def test_read_memory_returns_empty_list_and_logs_on_bad_json(self):
        with mock.patch.object(Path, "exists", return_value=True), \
             mock.patch("builtins.open", mock.mock_open(read_data="{not json")):
            with self.assertLogs(mdm.logger, level=logging.WARNING):
                self.assertEqual(mdm._read_memory(), [])


if __name__ == "__main__":
    unittest.main()
