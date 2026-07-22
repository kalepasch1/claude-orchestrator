"""Tests for gh_auth — token mint/cache, fallback chain, merge-queue detection."""
import os, sys, json, time, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gh_auth


class TestFallbackChain(unittest.TestCase):

    def setUp(self):
        gh_auth.invalidate_cache()

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"}, clear=False)
    @patch.object(gh_auth, "_try_app_token", return_value=None)
    def test_pat_fallback(self, _):
        token = gh_auth.gh_token()
        self.assertEqual(token, "ghp_test123")

    @patch.dict(os.environ, {}, clear=True)
    @patch.object(gh_auth, "_try_app_token", return_value=None)
    @patch("subprocess.run")
    def test_gh_cli_fallback(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=0, stdout="gho_clitoken\n")
        token = gh_auth.gh_token()
        self.assertEqual(token, "gho_clitoken")

    @patch.dict(os.environ, {}, clear=True)
    @patch.object(gh_auth, "_try_app_token", return_value=None)
    @patch("subprocess.run")
    def test_all_fail_returns_empty(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        token = gh_auth.gh_token()
        self.assertEqual(token, "")

    @patch.object(gh_auth, "_try_app_token", return_value="ghs_apptoken")
    def test_app_token_takes_priority(self, _):
        token = gh_auth.gh_token()
        self.assertEqual(token, "ghs_apptoken")


class TestCache(unittest.TestCase):

    def setUp(self):
        gh_auth.invalidate_cache()

    def test_invalidate_clears(self):
        gh_auth._cached_token = ("tok", time.time() + 3600)
        gh_auth.invalidate_cache()
        self.assertIsNone(gh_auth._cached_token)

    def test_stats_reflects_state(self):
        s = gh_auth.stats()
        self.assertIn("app_configured", s)
        self.assertIn("cached_token", s)
        self.assertFalse(s["cached_token"])


class TestMergeQueueDetection(unittest.TestCase):

    @patch.object(gh_auth, "gh_token", return_value="")
    def test_no_token_returns_false(self, _):
        self.assertFalse(gh_auth.has_merge_queue("owner/repo"))

    def test_no_repo_returns_false(self):
        self.assertFalse(gh_auth.has_merge_queue(""))

    def test_no_slash_returns_false(self):
        self.assertFalse(gh_auth.has_merge_queue("noslash"))


if __name__ == "__main__":
    unittest.main()
