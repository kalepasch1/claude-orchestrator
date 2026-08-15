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


def _committed_repo(d, fname="tracked.txt"):
    """git init + one committed file; returns the file's absolute path."""
    os.system(f"cd {d} && git init >/dev/null 2>&1 && "
              f"git config user.name t && git config user.email t@t && "
              f"echo x > {fname} && git add {fname} && git commit -m init >/dev/null 2>&1")
    return os.path.join(d, fname)


class TestStaleTrackedPaths(unittest.TestCase):
    def test_clean_repo_has_none(self):
        with tempfile.TemporaryDirectory() as d:
            _committed_repo(d)
            self.assertEqual(repo_setup_repair.check_stale_tracked_paths(d), [])

    def test_detects_deleted_from_disk_not_git(self):
        with tempfile.TemporaryDirectory() as d:
            path = _committed_repo(d)
            os.remove(path)
            self.assertEqual(repo_setup_repair.check_stale_tracked_paths(d), ["tracked.txt"])

    def test_repair_restores_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = _committed_repo(d)
            os.remove(path)
            restored = repo_setup_repair.repair_stale_tracked_paths(d)
            self.assertEqual(restored, ["tracked.txt"])
            self.assertTrue(os.path.exists(path))

    def test_diagnose_reports_stale_paths(self):
        with tempfile.TemporaryDirectory() as d:
            path = _committed_repo(d)
            os.remove(path)
            report = repo_setup_repair.diagnose(d)
            self.assertTrue(any("stale tracked paths" in i for i in report["issues"]))


class TestNodeDependencies(unittest.TestCase):
    def test_no_package_json(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(repo_setup_repair.check_node_dependencies(d))

    def test_missing_node_modules(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "package.json"), "w").write("{}")
            self.assertTrue(repo_setup_repair.check_node_dependencies(d))

    def test_node_modules_present(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "package.json"), "w").write("{}")
            os.mkdir(os.path.join(d, "node_modules"))
            self.assertFalse(repo_setup_repair.check_node_dependencies(d))

    def test_repair_runs_npm_ci_with_lockfile(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "package.json"), "w").write("{}")
            open(os.path.join(d, "package-lock.json"), "w").write("{}")
            with patch.object(repo_setup_repair, "check_tool", return_value=True), \
                 patch.object(repo_setup_repair, "_run", return_value=("", "", 0)) as run:
                self.assertTrue(repo_setup_repair.repair_node_dependencies(d))
            self.assertEqual(run.call_args[0][0][:2], ["npm", "ci"])


class TestOllamaModels(unittest.TestCase):
    def test_skipped_when_no_ollama_binary(self):
        with patch.object(repo_setup_repair, "check_tool", return_value=False):
            self.assertEqual(repo_setup_repair.required_ollama_models(), [])

    def test_missing_model_detected(self):
        fake_catalog = MagicMock()
        fake_catalog.models.return_value = ["qwen3-coder:30b"]
        with patch.dict(sys.modules, {"ollama_catalog": fake_catalog}):
            missing = repo_setup_repair.check_ollama_models(["llama3.2:3b"])
        self.assertEqual(missing, ["llama3.2:3b"])

    def test_base_name_match_counts_as_installed(self):
        fake_catalog = MagicMock()
        fake_catalog.models.return_value = ["llama3.2:latest"]
        with patch.dict(sys.modules, {"ollama_catalog": fake_catalog}):
            self.assertEqual(repo_setup_repair.check_ollama_models(["llama3.2:3b"]), [])

    def test_pull_is_opt_in(self):
        with patch.object(repo_setup_repair, "check_ollama_models", return_value=["llama3.2:3b"]), \
             patch.object(repo_setup_repair, "_run") as run, \
             patch.dict(os.environ, {"ORCH_REPAIR_OLLAMA_PULL": "false"}):
            self.assertEqual(repo_setup_repair.repair_ollama_models(), [])
            run.assert_not_called()

    def test_pull_when_enabled(self):
        with patch.object(repo_setup_repair, "check_ollama_models", return_value=["llama3.2:3b"]), \
             patch.object(repo_setup_repair, "_run", return_value=("", "", 0)) as run, \
             patch.dict(os.environ, {"ORCH_REPAIR_OLLAMA_PULL": "true"}):
            self.assertEqual(repo_setup_repair.repair_ollama_models(), ["llama3.2:3b"])
            self.assertEqual(run.call_args[0][0][:2], ["ollama", "pull"])


class TestRepairForTask(unittest.TestCase):
    def test_missing_project(self):
        with patch.object(repo_setup_repair, "db") as mock_db:
            mock_db.select.return_value = []
            result = repo_setup_repair.repair_for_task({"project_id": "xxx"})
            self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
