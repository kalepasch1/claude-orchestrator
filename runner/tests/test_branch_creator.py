"""Tests for branch_creator module.

Covers the original 3 create_branch scenarios (success, already exists,
no credentials) plus the push-credential probe that replaced the hard
GITHUB_PAT gate.

Note: these tests previously passed repo_path="/tmp/fakerepo", a directory
that does not exist, so every call short-circuited on the "repo path not
found" guard and all three assertions failed. They now use a real temporary
directory so the code under test is actually exercised.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_creator as bc


class _RepoDirCase(unittest.TestCase):
    """Base case providing a real (empty) directory as repo_path."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="branch-creator-test-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)


class TestCreateBranchScenarios(_RepoDirCase):
    """Acceptance: 3 scenarios — success, already exists, no credentials."""

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
                                  repo_path=self.repo)
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
                                  repo_path=self.repo)
        self.assertTrue(result["success"])
        self.assertIn("already exists", result["reason"])

    @patch("branch_creator.push_credentials", return_value="")
    @patch("branch_creator.bl")
    def test_handle_permission_errors(self, mock_bl, _mock_creds):
        """Scenario (c): handle missing push credentials gracefully."""
        mock_bl.validate_branch_name.return_value = (True, "")
        result = bc.create_branch("proj-1", "agent/no-auth",
                                  repo_path=self.repo)
        self.assertFalse(result["success"])
        self.assertIn("no push credentials", result["reason"])
        # Verify no secret leaked into the error message.
        self.assertNotIn("ghp_", result["reason"])


class TestPushCredentials(_RepoDirCase):
    """A missing GITHUB_PAT is not by itself a missing credential.

    Regression guard for "repo not found / PAT lacks access": the fleet Macs
    push through git's osxkeychain credential helper with GITHUB_PAT unset, so
    gating recovery on the env var alone blocked every branch creation there.
    """

    @patch.dict(os.environ, {"GITHUB_PAT": "test-token"})
    def test_env_token_is_detected(self):
        """An explicit env token short-circuits before any git probe."""
        self.assertEqual(bc.push_credentials(self.repo), "env")

    @patch.dict(os.environ, {"GITHUB_PAT": "", "GITHUB_TOKEN": ""})
    @patch("branch_creator._git")
    def test_credential_helper_counts_as_credentials(self, mock_git):
        """osxkeychain helper + https origin → pushable, no PAT required."""
        mock_git.side_effect = [
            ("https://github.com/o/r.git", True),   # remote get-url
            ("osxkeychain", True),                  # credential.helper
        ]
        with patch.dict(sys.modules, {"gh_auth": MagicMock(gh_token=lambda: "")}):
            self.assertEqual(bc.push_credentials(self.repo),
                             "credential-helper")

    @patch.dict(os.environ, {"GITHUB_PAT": "", "GITHUB_TOKEN": ""})
    @patch("branch_creator._git")
    def test_ssh_remote_counts_as_credentials(self, mock_git):
        """An SSH origin authenticates with agent keys — no token needed."""
        mock_git.side_effect = [("git@github.com:o/r.git", True)]
        with patch.dict(sys.modules, {"gh_auth": MagicMock(gh_token=lambda: "")}):
            self.assertEqual(bc.push_credentials(self.repo), "ssh-remote")

    @patch.dict(os.environ, {"GITHUB_PAT": "", "GITHUB_TOKEN": ""})
    @patch("branch_creator._git")
    def test_no_credentials_anywhere(self, mock_git):
        """https origin, no helper, no token → genuinely unauthenticated."""
        mock_git.side_effect = [
            ("https://github.com/o/r.git", True),   # remote get-url
            ("", True),                             # no credential.helper
        ]
        with patch.dict(sys.modules, {"gh_auth": MagicMock(gh_token=lambda: "")}):
            self.assertEqual(bc.push_credentials(self.repo), "")

    @patch.dict(os.environ, {"GITHUB_PAT": "", "GITHUB_TOKEN": ""})
    @patch("branch_creator._git", return_value=("", False))
    def test_probe_is_fail_soft_when_gh_auth_raises(self, _mock_git):
        """A broken gh_auth must degrade to "no credential", not raise."""
        boom = MagicMock()
        boom.gh_token.side_effect = RuntimeError("gh binary missing")
        with patch.dict(sys.modules, {"gh_auth": boom}):
            self.assertEqual(bc.push_credentials(self.repo), "")

    @patch.dict(os.environ, {"GITHUB_PAT": "", "GITHUB_TOKEN": ""})
    def test_missing_repo_path_is_fail_soft(self):
        """No repo path → empty string, never an exception."""
        with patch.dict(sys.modules, {"gh_auth": MagicMock(gh_token=lambda: "")}):
            self.assertEqual(bc.push_credentials(None), "")
            self.assertEqual(bc.push_credentials("/nonexistent/path/xyz"), "")


if __name__ == "__main__":
    unittest.main()
