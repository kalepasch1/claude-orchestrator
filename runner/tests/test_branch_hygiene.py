"""Tests for branch_hygiene — stale worktree/branch detection.

Uses subprocess mocking to avoid needing a real git repo.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_hygiene as bh

PORCELAIN_OUTPUT = """\
worktree /repo
HEAD abc1234
branch refs/heads/master
bare

worktree /repo-wt/task-1
HEAD def5678
branch refs/heads/agent/task-1

worktree /repo-wt/task-2
HEAD 9876543
detached

worktree /repo-wt/task-3
HEAD aaa1111
branch refs/heads/agent/task-3
locked

worktree /repo-wt/task-4
HEAD bbb2222
prunable

"""

MERGED_OUTPUT = """\
  agent/task-1
  agent/task-5
"""


class TestListWorktrees(unittest.TestCase):
    @patch("branch_hygiene._run_git", return_value=PORCELAIN_OUTPUT)
    def test_parses_all_entries(self, mock_git):
        entries = bh.list_worktrees("/repo")
        # 4 worktree blocks in the porcelain output (bare, task-1, task-2, task-3, task-4)
        named = [e for e in entries if e.path]
        self.assertEqual(len(named), 5)

    @patch("branch_hygiene._run_git", return_value=PORCELAIN_OUTPUT)
    def test_bare_flag(self, mock_git):
        entries = bh.list_worktrees("/repo")
        self.assertTrue(entries[0].is_bare)
        self.assertFalse(entries[1].is_bare)

    @patch("branch_hygiene._run_git", return_value=PORCELAIN_OUTPUT)
    def test_detached_flag(self, mock_git):
        entries = bh.list_worktrees("/repo")
        task2 = [e for e in entries if "task-2" in e.path][0]
        self.assertTrue(task2.is_detached)

    @patch("branch_hygiene._run_git", return_value=PORCELAIN_OUTPUT)
    def test_locked_flag(self, mock_git):
        entries = bh.list_worktrees("/repo")
        task3 = [e for e in entries if "task-3" in e.path][0]
        self.assertTrue(task3.is_locked)

    @patch("branch_hygiene._run_git", return_value=PORCELAIN_OUTPUT)
    def test_prunable_flag(self, mock_git):
        entries = bh.list_worktrees("/repo")
        task4 = [e for e in entries if "task-4" in e.path][0]
        self.assertTrue(task4.is_prunable)

    @patch("branch_hygiene._run_git", return_value=None)
    def test_git_failure_returns_empty(self, mock_git):
        self.assertEqual(bh.list_worktrees("/repo"), [])

    @patch("branch_hygiene._run_git", return_value="")
    def test_empty_output_returns_empty(self, mock_git):
        self.assertEqual(bh.list_worktrees("/repo"), [])


class TestMergedAgentBranches(unittest.TestCase):
    @patch("branch_hygiene._run_git", return_value=MERGED_OUTPUT)
    def test_parses_merged_branches(self, mock_git):
        branches = bh.merged_agent_branches("/repo")
        self.assertIn("agent/task-1", branches)
        self.assertIn("agent/task-5", branches)

    @patch("branch_hygiene._run_git", return_value=None)
    def test_git_failure_returns_empty(self, mock_git):
        self.assertEqual(bh.merged_agent_branches("/repo"), [])


class TestStaleWorktrees(unittest.TestCase):
    @patch("branch_hygiene.merged_agent_branches", return_value=["agent/task-1"])
    @patch("branch_hygiene._run_git", return_value=PORCELAIN_OUTPUT)
    def test_detached_unlocked_is_stale(self, mock_git, mock_merged):
        stale = bh.stale_worktrees("/repo")
        paths = [e.path for e in stale]
        self.assertIn("/repo-wt/task-2", paths)  # detached, unlocked

    @patch("branch_hygiene.merged_agent_branches", return_value=["agent/task-1"])
    @patch("branch_hygiene._run_git", return_value=PORCELAIN_OUTPUT)
    def test_locked_not_stale(self, mock_git, mock_merged):
        stale = bh.stale_worktrees("/repo")
        paths = [e.path for e in stale]
        self.assertNotIn("/repo-wt/task-3", paths)  # locked

    @patch("branch_hygiene.merged_agent_branches", return_value=["agent/task-1"])
    @patch("branch_hygiene._run_git", return_value=PORCELAIN_OUTPUT)
    def test_prunable_is_stale(self, mock_git, mock_merged):
        stale = bh.stale_worktrees("/repo")
        paths = [e.path for e in stale]
        self.assertIn("/repo-wt/task-4", paths)  # prunable

    @patch("branch_hygiene.merged_agent_branches", return_value=["agent/task-1"])
    @patch("branch_hygiene._run_git", return_value=PORCELAIN_OUTPUT)
    def test_merged_branch_is_stale(self, mock_git, mock_merged):
        stale = bh.stale_worktrees("/repo")
        paths = [e.path for e in stale]
        self.assertIn("/repo-wt/task-1", paths)  # merged


class TestCleanupReport(unittest.TestCase):
    @patch("branch_hygiene.merged_agent_branches", return_value=[])
    @patch("branch_hygiene.list_worktrees", return_value=[])
    @patch("branch_hygiene.stale_worktrees", return_value=[])
    def test_empty_report(self, mock_stale, mock_wt, mock_merged):
        report = bh.cleanup_report("/repo")
        self.assertEqual(report["total_worktrees"], 0)
        self.assertEqual(report["stale_worktrees"], 0)


if __name__ == "__main__":
    unittest.main()
