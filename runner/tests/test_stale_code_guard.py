"""Regression test: stale_code_guard must not fail open when the boot marker is missing.

2026-07-16: no .runner_boot_commit file existed, so `boot` was "" and the guard's
`if boot and head and boot != head` was always False. The guard silently did nothing.
The runner sat 14h on code from 04:00 and never learned about fixes merged to master,
so patches to the drift/stash bugs were inert until a human noticed. A safety guard
that silently no-ops is worse than no guard: it produces false confidence.

Stdlib + unittest.mock only (runner convention).
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sentinel


class _R:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.returncode = 0
        self.stderr = ""


class TestStaleCodeGuard(unittest.TestCase):
    def test_missing_boot_marker_is_reported_not_ignored(self):
        logs = []
        with mock.patch.object(sentinel, "git", return_value=_R("abc123")), \
             mock.patch.object(sentinel, "log", side_effect=lambda a, d="": logs.append(a)), \
             mock.patch.object(sentinel, "emit") as emit, \
             mock.patch("builtins.open", side_effect=OSError("no such file")):
            sentinel.stale_code_guard()
        self.assertIn("stale-code-unknown", logs,
                      "a missing boot marker must be surfaced, not silently ignored")
        emit.assert_called_once()

    def test_compares_against_base_branch_not_drifted_head(self):
        """While drifted onto an agent branch, HEAD is meaningless for staleness."""
        seen = []

        def fake_git(*args, **kw):
            seen.append(args)
            return _R("deadbeef")

        m = mock.mock_open(read_data="deadbeef")
        with mock.patch.object(sentinel, "git", side_effect=fake_git), \
             mock.patch.object(sentinel, "log"), mock.patch.object(sentinel, "emit"), \
             mock.patch("builtins.open", m):
            sentinel.stale_code_guard()

        revparse = [a for a in seen if a and a[0] == "rev-parse"]
        self.assertTrue(revparse, "expected a rev-parse")
        self.assertEqual(revparse[0][1], sentinel.BASE_BRANCH,
                         "staleness must be measured against the base branch, not HEAD")


if __name__ == "__main__":
    unittest.main()
