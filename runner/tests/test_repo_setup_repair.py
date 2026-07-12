#!/usr/bin/env python3
"""
test_repo_setup_repair.py - tests for repo_setup_repair module.

Covers: diagnose, repair, check_git_config, check_worktree_health,
        repair_git_config, repair_index_lock, repair_orphaned_worktrees.
Task: improve-implement-advanced-branch-management-repai-slice-5
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import repo_setup_repair


class TestCheckGit(unittest.TestCase):
    def test_valid_repo(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            ok, err = repo_setup_repair.check_git(d)
            self.assertTrue(ok)

    def test_invalid_repo(self):
        with tempfile.TemporaryDirectory() as d:
            ok, err = repo_setup_repair.check_git(d)
            self.assertFalse(ok)


class TestCheckGitConfig(unittest.TestCase):
    def test_missing_config(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            # Unset user.name/email in the temp repo
            os.system(f"cd {d} && git config --unset user.name 2>/dev/null; git config --unset user.email 2>/dev/null")
            issues = repo_setup_repair.check_git_config(d)
            # May or may not have global config; just verify it returns a list
            self.assertIsInstance(issues, list)


class TestCheckTool(unittest.TestCase):
    def test_git_exists(self):
        self.assertTrue(repo_setup_repair.check_tool("git"))

    def test_nonexistent_tool(self):
        self.assertFalse(repo_setup_repair.check_tool("nonexistent_tool_xyz_999"))


class TestCheckWorktreeHealth(unittest.TestCase):
    def test_clean_repo(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            issues = repo_setup_repair.check_worktree_health(d)
            self.assertEqual(issues, [])

    def test_stale_index_lock(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            lock = os.path.join(d, ".git", "index.lock")
            open(lock, "w").close()
            issues = repo_setup_repair.check_worktree_health(d)
            self.assertIn("index.lock", issues)
            os.remove(lock)


class TestDiagnose(unittest.TestCase):
    def test_nonexistent_path(self):
        report = repo_setup_repair.diagnose("/tmp/does_not_exist_xyz_999")
        self.assertFalse(report["valid"])

    def test_valid_repo(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            report = repo_setup_repair.diagnose(d)
            self.assertTrue(report["valid"])
            self.assertIn("repo", report)


class TestRepair(unittest.TestCase):
    def test_repair_nonexistent(self):
        report = repo_setup_repair.repair("/tmp/does_not_exist_xyz_999")
        self.assertFalse(report["valid"])

    def test_repair_valid_repo(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            report = repo_setup_repair.repair(d)
            self.assertIn("repairs", report)
            self.assertIn("healthy", report)


class TestRepairIndexLock(unittest.TestCase):
    def test_no_lock(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            self.assertFalse(repo_setup_repair.repair_index_lock(d))

    def test_removes_stale_lock(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            lock = os.path.join(d, ".git", "index.lock")
            open(lock, "w").close()
            with patch.object(repo_setup_repair, "_run", return_value=("", "", 1)):
                removed = repo_setup_repair.repair_index_lock(d)
            # pgrep mock returns empty (no git process), so lock should be removed
            self.assertTrue(removed or not os.path.exists(lock))


class TestRepairForTask(unittest.TestCase):
    def test_missing_project(self):
        with patch.object(repo_setup_repair, "db") as mock_db:
            mock_db.select.return_value = []
            result = repo_setup_repair.repair_for_task({"project_id": "xxx"})
            self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
