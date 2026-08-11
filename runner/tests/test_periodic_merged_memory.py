#!/usr/bin/env python3
"""The merged-diff memory rollup must actually be scheduled, and its bool honoured.

`merged_diff_memory.capture_to_memory()` returns True ONLY when a memory file was
written — "no merged commits found" is False, deliberately, because a caller that
reads True as "memory is current" would be misled. Nothing in production called
it, so the daily rollup never ran and the careful bool went unread.

These tests pin the job registration and the contract at the call site.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import periodic


class TestJobRegistration(unittest.TestCase):
    def test_mergedmemory_is_a_registered_job(self):
        self.assertIn("mergedmemory", periodic.JOBS)
        self.assertIs(periodic.JOBS["mergedmemory"], periodic.run_mergedmemory)

    def test_job_is_documented_in_the_module_header(self):
        # periodic.py puts `from __future__ import annotations` above its header
        # string, so the string is an expression, not __doc__. Read the source.
        with open(periodic.__file__, encoding="utf-8") as f:
            header = f.read(2000)
        self.assertIn("mergedmemory", header)


class TestRunMergedMemory(unittest.TestCase):
    def _run(self, capture_return):
        fake = MagicMock()
        fake.capture_to_memory.return_value = capture_return
        with patch.dict(sys.modules, {"merged_diff_memory": fake}):
            result = periodic.run_mergedmemory()
        return result, fake

    def test_returns_true_when_a_memory_file_was_written(self):
        result, fake = self._run(True)
        self.assertIs(result, True)
        fake.capture_to_memory.assert_called_once()

    def test_returns_false_when_nothing_was_written(self):
        result, _fake = self._run(False)
        self.assertIs(result, False)

    def test_passes_the_repository_root_not_the_runner_dir(self):
        _result, fake = self._run(True)
        repo = fake.capture_to_memory.call_args.kwargs["repo"]
        self.assertTrue(os.path.isdir(repo), repo)
        # the repo root contains runner/, it is not runner/ itself
        self.assertTrue(os.path.isdir(os.path.join(repo, "runner")))
        self.assertNotEqual(os.path.basename(repo), "runner")

    def test_the_boolean_is_not_discarded(self):
        """A truthy-looking non-bool must not be laundered into success."""
        result, _fake = self._run(0)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
