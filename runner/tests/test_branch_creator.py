"""Tests for branch_creator module — 3 scenarios per acceptance criteria."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_creator as bc


class TestCreateBranchScenarios(unittest.TestCase):
    """Acceptance: 3 scenarios — success, already exists, permission error."""

    @patch.dict(os.environ, {"GITHUB_PAT": "test-token"})
    @patch("branch_creator.bl")
    @patch("branch_creator._git")
    def test_create_branch_successfully(self, mock_git, mock_bl):
        """Scenario (a): create a new branch successfully."""
        mock_bl.validate_branch_name.return_value = (True, "")
        mock_bl.branch_exists.return_value = False
        mock_git.side_effect = [
            ("", True),   # fetch
            ("", True),   # branch create
            ("", True),   # push
        ]
        result = bc.create_branch("proj-1", "agent/test-slug",
                                  repo_path="/tmp/fakerepo")
        self.assertTrue(result["success"])
        self.assertIn("created", result["reason"])

    @patch.dict(os.environ, {"GITHUB_PAT": "test-token"})
    @patch("branch_creator.bl")
    @patch("branch_creator._git")
    def test_handle_branch_already_exists(self, mock_git, mock_bl):
        """Scenario (b): handle branch already exists gracefully."""
        mock_bl.validate_branch_name.return_value = (True, "")
        mock_bl.branch_exists.return_value = True
        mock_git.return_value = ("", True)  # fetch
        result = bc.create_branch("proj-1", "agent/existing-slug",
                                  repo_path="/tmp/fakerepo")
        self.assertTrue(result["success"])
        self.assertIn("already exists", result["reason"])

    @patch.dict(os.environ, {"GITHUB_PAT": ""})
    @patch("branch_creator.bl")
    def test_handle_permission_errors(self, mock_bl):
        """Scenario (c): handle permission errors gracefully."""
        mock_bl.validate_branch_name.return_value = (True, "")
        result = bc.create_branch("proj-1", "agent/no-auth",
                                  repo_path="/tmp/fakerepo")
        self.assertFalse(result["success"])
        self.assertIn("GITHUB_PAT", result["reason"])
        # Verify no secret leaked in the error message
        self.assertNotIn("token", result["reason"].lower())


if __name__ == "__main__":
    unittest.main()
