"""Tests for source_config_test_validator — validates project configuration consistency."""
import os
import sys
import json
import tempfile
import shutil
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock db before importing source_config_test_validator
_db_mock = types.ModuleType("db")
_db_mock.select = MagicMock(return_value=[])
_db_mock.localize_repo_path = lambda p: p
sys.modules["db"] = _db_mock

# Mock log module
_log_mock = types.ModuleType("log")
_log_mock.get = lambda x: MagicMock()
sys.modules["log"] = _log_mock

import source_config_test_validator as scv


class TestValidateProjectBasics(unittest.TestCase):
    """Basic validation of project configuration."""

    def test_none_project(self):
        """None project should return project field issue."""
        issues = scv.validate_project(None)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["field"], "project")

    def test_empty_project(self):
        """Empty project dict should have validation issues."""
        issues = scv.validate_project({})
        # Should flag missing repo_path and test_cmd
        self.assertGreater(len(issues), 0)

    def test_project_with_id(self):
        """Project with basic id can be validated."""
        proj = {"id": "test-1"}
        issues = scv.validate_project(proj)
        # Should have issues (missing repo, etc)
        self.assertGreater(len(issues), 0)


class TestRepositoryValidation(unittest.TestCase):
    """Repository path validation."""

    def test_missing_repo_path(self):
        """Missing repo_path is flagged."""
        proj = {"id": "test-1", "repo_path": "/nonexistent/path/xyz", "test_cmd": "echo ok"}
        issues = scv.validate_project(proj)
        repo_issues = [i for i in issues if i["field"] == "repo_path"]
        self.assertEqual(len(repo_issues), 1)
        self.assertIn("not resolvable", repo_issues[0]["issue"])

    def test_empty_repo_path(self):
        """Empty repo_path is flagged."""
        proj = {"id": "test-2", "repo_path": "", "test_cmd": "echo ok"}
        issues = scv.validate_project(proj)
        repo_issues = [i for i in issues if i["field"] == "repo_path"]
        self.assertGreater(len(repo_issues), 0)

    def test_repo_exists_but_not_git(self):
        """Directory that exists but isn't a git repo is flagged."""
        with tempfile.TemporaryDirectory() as td:
            proj = {"id": "test-3", "repo_path": td, "test_cmd": "echo ok"}
            issues = scv.validate_project(proj)
            git_issues = [i for i in issues if "not a git repo" in i["issue"]]
            self.assertEqual(len(git_issues), 1)

    def test_repo_valid_git(self):
        """Valid git repository passes repo validation."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            proj = {"id": "test-4", "repo_path": td, "test_cmd": "echo ok", "build_cmd": "echo ok"}
            issues = scv.validate_project(proj)
            repo_issues = [i for i in issues if i["field"] == "repo_path"]
            self.assertEqual(len(repo_issues), 0)


class TestTestCommandValidation(unittest.TestCase):
    """Test command validation."""

    def test_missing_test_cmd(self):
        """Missing test_cmd is flagged."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            proj = {"id": "test-5", "repo_path": td, "test_cmd": ""}
            issues = scv.validate_project(proj)
            cmd_issues = [i for i in issues if i["field"] == "test_cmd"]
            self.assertEqual(len(cmd_issues), 1)
            self.assertIn("empty", cmd_issues[0]["issue"])

    def test_nonexistent_test_executable(self):
        """Test executable that doesn't exist is flagged."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            proj = {"id": "test-6", "repo_path": td, "test_cmd": "/nonexistent/pytest"}
            issues = scv.validate_project(proj)
            cmd_issues = [i for i in issues if i["field"] == "test_cmd"]
            self.assertEqual(len(cmd_issues), 1)
            self.assertIn("not found", cmd_issues[0]["issue"])

    def test_valid_test_cmd(self):
        """Valid test command passes validation."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            proj = {"id": "test-7", "repo_path": td, "test_cmd": "echo test"}
            issues = scv.validate_project(proj)
            cmd_issues = [i for i in issues if i["field"] == "test_cmd"]
            self.assertEqual(len(cmd_issues), 0)


class TestBuildCommandValidation(unittest.TestCase):
    """Build command validation."""

    def test_missing_build_cmd(self):
        """Missing build_cmd is OK (optional)."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            proj = {"id": "test-8", "repo_path": td, "test_cmd": "echo test", "build_cmd": ""}
            issues = scv.validate_project(proj)
            # build_cmd is optional, should have no issues
            build_issues = [i for i in issues if i["field"] == "build_cmd"]
            self.assertEqual(len(build_issues), 0)

    def test_nonexistent_build_executable(self):
        """Build executable that doesn't exist is flagged."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            proj = {"id": "test-9", "repo_path": td, "test_cmd": "echo test", "build_cmd": "/nonexistent/build"}
            issues = scv.validate_project(proj)
            build_issues = [i for i in issues if i["field"] == "build_cmd"]
            self.assertEqual(len(build_issues), 1)

    def test_valid_build_cmd(self):
        """Valid build command passes validation."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            proj = {"id": "test-10", "repo_path": td, "test_cmd": "echo test", "build_cmd": "echo build"}
            issues = scv.validate_project(proj)
            build_issues = [i for i in issues if i["field"] == "build_cmd"]
            self.assertEqual(len(build_issues), 0)


class TestNpmValidation(unittest.TestCase):
    """NPM-specific command validation."""

    def test_npm_with_missing_prefix_dir(self):
        """npm --prefix with missing directory is flagged."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            proj = {
                "id": "test-11",
                "repo_path": td,
                "test_cmd": "npm --prefix nonexistent test",
                "build_cmd": ""
            }
            issues = scv.validate_project(proj)
            npm_issues = [i for i in issues if "package.json" in i["issue"]]
            self.assertEqual(len(npm_issues), 1)

    def test_npm_with_missing_package_json(self):
        """npm --prefix without package.json is flagged."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            os.makedirs(os.path.join(td, "web"))
            proj = {
                "id": "test-12",
                "repo_path": td,
                "test_cmd": "npm --prefix web test",
                "build_cmd": ""
            }
            issues = scv.validate_project(proj)
            npm_issues = [i for i in issues if "package.json" in i["issue"]]
            self.assertEqual(len(npm_issues), 1)

    def test_npm_with_valid_package_json(self):
        """npm --prefix with valid package.json passes."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            os.makedirs(os.path.join(td, "web"))
            with open(os.path.join(td, "web", "package.json"), "w") as f:
                json.dump({"name": "test"}, f)
            proj = {
                "id": "test-13",
                "repo_path": td,
                "test_cmd": "npm --prefix web test",
                "build_cmd": ""
            }
            issues = scv.validate_project(proj)
            npm_issues = [i for i in issues if "package.json" in i["issue"]]
            self.assertEqual(len(npm_issues), 0)


class TestValidateAll(unittest.TestCase):
    """Full validation across all projects."""

    def test_validate_all_disabled(self):
        """Validation can be disabled via env var."""
        orig_enabled = scv.ENABLED
        scv.ENABLED = False
        try:
            results = scv.validate_all()
            self.assertEqual(results, {})
        finally:
            scv.ENABLED = orig_enabled

    @patch('source_config_test_validator.db.select')
    def test_validate_all_no_projects(self, mock_select):
        """Empty project list returns no issues."""
        mock_select.return_value = []
        results = scv.validate_all()
        self.assertEqual(results, {})

    @patch('source_config_test_validator.db.select')
    def test_validate_all_with_issues(self, mock_select):
        """Projects with issues are reported."""
        mock_select.return_value = [
            {"id": "p1", "name": "Project 1", "repo_path": "/nonexistent", "test_cmd": "echo"}
        ]
        results = scv.validate_all()
        self.assertIn("p1", results)
        self.assertGreater(len(results["p1"]), 0)

    @patch('source_config_test_validator.db.select')
    def test_validate_all_multiple_projects(self, mock_select):
        """Multiple projects can be validated."""
        with tempfile.TemporaryDirectory() as td1:
            with tempfile.TemporaryDirectory() as td2:
                os.makedirs(os.path.join(td1, ".git"))
                os.makedirs(os.path.join(td2, ".git"))
                mock_select.return_value = [
                    {"id": "p1", "name": "Project 1", "repo_path": td1, "test_cmd": "echo test"},
                    {"id": "p2", "name": "Project 2", "repo_path": td2, "test_cmd": "echo test"}
                ]
                results = scv.validate_all()
                # Both should be validated (may or may not have issues)
                self.assertIsInstance(results, dict)


class TestValidateCmd(unittest.TestCase):
    """Command validation helper function."""

    def test_empty_command(self):
        """Empty command string is flagged."""
        issues = []
        scv._validate_cmd("", "/tmp", "test_cmd", issues)
        self.assertEqual(len(issues), 1)
        self.assertIn("empty", issues[0]["issue"])

    def test_command_with_spaces(self):
        """Commands with arguments are handled correctly."""
        issues = []
        scv._validate_cmd("echo hello world", "/tmp", "test_cmd", issues)
        # Should only check 'echo' executable, which exists
        self.assertEqual(len(issues), 0)

    def test_nonexistent_first_token(self):
        """Non-existent command is flagged."""
        issues = []
        scv._validate_cmd("/nonexistent/cmd arg1 arg2", "/tmp", "test_cmd", issues)
        self.assertEqual(len(issues), 1)
        self.assertIn("not found", issues[0]["issue"])

    @patch('shutil.which')
    def test_mocked_executable_check(self, mock_which):
        """Executable checking uses shutil.which."""
        mock_which.return_value = "/usr/bin/pytest"
        issues = []
        scv._validate_cmd("pytest src/", "/tmp", "test_cmd", issues)
        mock_which.assert_called()
        self.assertEqual(len(issues), 0)


class TestHappyPath(unittest.TestCase):
    """Complete valid configuration passes all checks."""

    def test_happy_path_minimal(self):
        """Minimal valid project configuration."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            proj = {
                "id": "happy-1",
                "name": "Happy Path",
                "repo_path": td,
                "test_cmd": "echo test",
                "build_cmd": ""
            }
            issues = scv.validate_project(proj)
            self.assertEqual(issues, [], f"Expected no issues, got {issues}")

    def test_happy_path_full(self):
        """Full valid project configuration."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            os.makedirs(os.path.join(td, "web"))
            with open(os.path.join(td, "web", "package.json"), "w") as f:
                json.dump({"scripts": {"test": "jest"}}, f)
            proj = {
                "id": "happy-2",
                "name": "Full Config",
                "repo_path": td,
                "test_cmd": "npm --prefix web test",
                "build_cmd": "npm --prefix web run build"
            }
            issues = scv.validate_project(proj)
            self.assertEqual(issues, [], f"Expected no issues, got {issues}")


if __name__ == "__main__":
    unittest.main()
