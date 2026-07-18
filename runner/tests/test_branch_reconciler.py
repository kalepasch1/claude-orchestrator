"""Tests for branch_reconciler module."""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from runner.branch_reconciler import (
    list_local_branches, list_remote_branches,
    get_branch_age_days, reconcile, _run_git,
    STALE_DAYS, REMOTE_NAME, PROTECTED_BRANCHES,
)


class TestListLocalBranches(unittest.TestCase):
    @patch("runner.branch_reconciler._run_git")
    def test_parses_branches(self, mock_git):
        mock_git.return_value = "main\nfeature-a\nfix-bug"
        result = list_local_branches()
        self.assertEqual(result, ["main", "feature-a", "fix-bug"])

    @patch("runner.branch_reconciler._run_git")
    def test_empty_output(self, mock_git):
        mock_git.return_value = ""
        self.assertEqual(list_local_branches(), [])


class TestListRemoteBranches(unittest.TestCase):
    @patch("runner.branch_reconciler._run_git")
    def test_strips_remote_prefix(self, mock_git):
        mock_git.return_value = "origin/main\norigin/feature-b\norigin/HEAD -> origin/main"
        result = list_remote_branches()
        self.assertIn("main", result)
        self.assertIn("feature-b", result)
        self.assertNotIn("HEAD", str(result))

    @patch("runner.branch_reconciler._run_git")
    def test_empty(self, mock_git):
        mock_git.return_value = ""
        self.assertEqual(list_remote_branches(), [])


class TestGetBranchAgeDays(unittest.TestCase):
    @patch("runner.branch_reconciler._run_git")
    def test_recent_branch(self, mock_git):
        now = int(datetime.now(timezone.utc).timestamp())
        mock_git.return_value = str(now)
        self.assertEqual(get_branch_age_days("main"), 0)

    @patch("runner.branch_reconciler._run_git")
    def test_old_branch(self, mock_git):
        old = int((datetime.now(timezone.utc) - timedelta(days=60)).timestamp())
        mock_git.return_value = str(old)
        self.assertEqual(get_branch_age_days("stale-branch"), 60)

    @patch("runner.branch_reconciler._run_git")
    def test_invalid_output(self, mock_git):
        mock_git.return_value = "not-a-number"
        self.assertEqual(get_branch_age_days("bad"), -1)


class TestReconcile(unittest.TestCase):
    @patch("runner.branch_reconciler.get_branch_age_days")
    @patch("runner.branch_reconciler._run_git")
    @patch("runner.branch_reconciler.list_remote_branches")
    @patch("runner.branch_reconciler.list_local_branches")
    def test_orphaned_local(self, mock_local, mock_remote, mock_git, mock_age):
        mock_local.return_value = ["main", "feature-x"]
        mock_remote.return_value = ["main"]
        mock_age.return_value = 5
        mock_git.return_value = "abc123"
        result = reconcile()
        self.assertIn("feature-x", result["orphaned_local"])

    @patch("runner.branch_reconciler.get_branch_age_days")
    @patch("runner.branch_reconciler._run_git")
    @patch("runner.branch_reconciler.list_remote_branches")
    @patch("runner.branch_reconciler.list_local_branches")
    def test_orphaned_remote(self, mock_local, mock_remote, mock_git, mock_age):
        mock_local.return_value = ["main"]
        mock_remote.return_value = ["main", "remote-only"]
        mock_age.return_value = 5
        mock_git.return_value = "abc123"
        result = reconcile()
        self.assertIn("remote-only", result["orphaned_remote"])

    @patch("runner.branch_reconciler.get_branch_age_days")
    @patch("runner.branch_reconciler._run_git")
    @patch("runner.branch_reconciler.list_remote_branches")
    @patch("runner.branch_reconciler.list_local_branches")
    def test_conflicting_branches(self, mock_local, mock_remote, mock_git, mock_age):
        mock_local.return_value = ["feature-a"]
        mock_remote.return_value = ["feature-a"]
        mock_age.return_value = 5
        mock_git.side_effect = lambda args, cwd=None: (
            "aaa" if "feature-a" == args[-1] else "bbb"
        )
        result = reconcile()
        self.assertEqual(len(result["conflicting"]), 1)

    @patch("runner.branch_reconciler.get_branch_age_days")
    @patch("runner.branch_reconciler._run_git")
    @patch("runner.branch_reconciler.list_remote_branches")
    @patch("runner.branch_reconciler.list_local_branches")
    def test_stale_detected(self, mock_local, mock_remote, mock_git, mock_age):
        mock_local.return_value = ["old-branch"]
        mock_remote.return_value = []
        mock_age.return_value = 60
        mock_git.return_value = ""
        result = reconcile()
        stale_names = [s["branch"] for s in result["stale"]]
        self.assertIn("old-branch", stale_names)

    @patch("runner.branch_reconciler.get_branch_age_days")
    @patch("runner.branch_reconciler._run_git")
    @patch("runner.branch_reconciler.list_remote_branches")
    @patch("runner.branch_reconciler.list_local_branches")
    def test_report_structure(self, mock_local, mock_remote, mock_git, mock_age):
        mock_local.return_value = ["main"]
        mock_remote.return_value = ["main"]
        mock_age.return_value = 1
        mock_git.return_value = "same"
        result = reconcile()
        for key in ("orphaned_local", "orphaned_remote", "stale",
                     "conflicting", "protected", "total_local", "total_remote"):
            self.assertIn(key, result)


class TestConfig(unittest.TestCase):
    def test_no_hardcoded_secrets(self):
        """Verify no secrets/credentials in module source."""
        import inspect
        source = inspect.getsource(
            sys.modules["runner.branch_reconciler"]
        )
        for pattern in ["password", "token", "secret", "api_key", "credential"]:
            # Should only appear in comments/docstrings about env vars, not as values
            self.assertNotIn(f'= "{pattern}', source.lower())
            self.assertNotIn(f"= '{pattern}", source.lower())


if __name__ == "__main__":
    unittest.main()
