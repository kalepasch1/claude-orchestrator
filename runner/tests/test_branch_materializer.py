#!/usr/bin/env python3
"""Tests for branch_materializer.py — deterministic branch creation guarantee."""
import os, sys, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_materializer


class TestDeriveBranchName(unittest.TestCase):
    """Test deterministic branch name derivation."""

    def test_simple_slug(self):
        name = branch_materializer.derive_branch_name("my-task-slug")
        self.assertEqual(name, "agent/my-task-slug")

    def test_uppercase_normalized(self):
        name = branch_materializer.derive_branch_name("My-Task-SLUG")
        self.assertEqual(name, "agent/my-task-slug")

    def test_special_chars_replaced(self):
        name = branch_materializer.derive_branch_name("feat/add_thing@v2")
        self.assertNotIn("@", name)
        self.assertNotIn("/", name.replace("agent/", ""))

    def test_long_slug_truncated(self):
        long_slug = "a" * 200
        name = branch_materializer.derive_branch_name(long_slug)
        self.assertLessEqual(len(name), 90)  # prefix + 80

    def test_none_slug(self):
        name = branch_materializer.derive_branch_name(None)
        self.assertEqual(name, "agent/unknown")

    def test_empty_slug(self):
        name = branch_materializer.derive_branch_name("")
        self.assertEqual(name, "agent/unknown")

    def test_deterministic(self):
        """Same slug always produces the same branch name."""
        a = branch_materializer.derive_branch_name("fix-login-bug")
        b = branch_materializer.derive_branch_name("fix-login-bug")
        self.assertEqual(a, b)

    def test_custom_prefix(self):
        with patch.object(branch_materializer, "BRANCH_PREFIX", "feature/"):
            name = branch_materializer.derive_branch_name("new-thing")
            self.assertTrue(name.startswith("feature/"))


class TestMaterializeBranch(unittest.TestCase):
    """Test branch materialization logic."""

    def test_disabled_returns_ok(self):
        with patch.object(branch_materializer, "ENABLED", False):
            result = branch_materializer.materialize_branch(
                {"slug": "test"}, "/tmp/repo", "master"
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["action"], "disabled")

    @patch("branch_materializer._run_git")
    def test_branch_exists_locally(self, mock_git):
        mock_git.return_value = (0, "abc123", "")
        result = branch_materializer.materialize_branch(
            {"slug": "existing"}, "/tmp/repo", "master"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "existed")


    @patch("branch_materializer._run_git")
    def test_create_and_push_success(self, mock_git):
        # First call: rev-parse fails (not local), second: ls-remote empty,
        # third: branch create ok, fourth: push ok
        mock_git.side_effect = [
            (1, "", "not found"),   # rev-parse
            (0, "", ""),            # ls-remote (empty = not remote)
            (0, "", ""),            # branch create
            (0, "", ""),            # push
        ]
        result = branch_materializer.materialize_branch(
            {"slug": "new-task"}, "/tmp/repo", "master"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "created")

    @patch("branch_materializer._run_git")
    def test_push_failure_tags(self, mock_git):
        mock_git.side_effect = [
            (1, "", ""),            # rev-parse
            (0, "", ""),            # ls-remote
            (0, "", ""),            # branch create
            (1, "", "push error"),  # push fails
        ]
        result = branch_materializer.materialize_branch(
            {"slug": "fail-push"}, "/tmp/repo", "master"
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "push-failed")


class TestMaterializeTaskBranches(unittest.TestCase):
    """Test batch materialization."""

    @patch("branch_materializer.materialize_branch")
    def test_batch_tags_failures(self, mock_mat):
        mock_mat.side_effect = [
            {"ok": True, "branch": "agent/a", "action": "created", "error": None},
            {"ok": False, "branch": "agent/b", "action": "push-failed", "error": "err"},
        ]
        results = branch_materializer.materialize_task_branches(
            [{"slug": "a"}, {"slug": "b"}], "/tmp/repo"
        )
        self.assertEqual(len(results), 2)
        self.assertNotIn("tag", results[0])
        self.assertEqual(results[1]["tag"], "branch-init-failed")


class TestStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        s = branch_materializer.stats()
        self.assertIn("branches_created", s)
        self.assertIn("failures", s)


if __name__ == "__main__":
    unittest.main()
