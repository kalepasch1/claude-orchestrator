#!/usr/bin/env python3
"""Tests for branch_recovery.py — detect and recover missing git branches."""
import os, sys, subprocess, tempfile, shutil, unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_recovery


def _make_repo(tmpdir):
    """Create a bare-minimum git repo for testing."""
    repo = os.path.join(tmpdir, "repo")
    os.makedirs(repo, exist_ok=True)
    subprocess.run(["git", "init", repo], capture_output=True, check=True)
    subprocess.run(["git", "-C", repo, "commit", "--allow-empty",
                     "-m", "init"], capture_output=True, check=True)
    return repo


class TestRecoverBranchFetchOrigin(unittest.TestCase):
    """Strategy 1: fetch from origin remote."""

    def test_fetch_from_origin_success(self):
        """When the branch exists on origin, fetch recovers it."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", side_effect=lambda r, b, remote="origin": remote == "origin"), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):
            result = branch_recovery.recover_branch("/fake/repo", "feature-x")
            self.assertEqual(result["status"], "recovered")
            self.assertIn("origin", result["action_taken"])

    def test_fetch_from_upstream_when_origin_missing(self):
        """Falls back to upstream remote when origin doesn't have it."""
        def remote_check(repo, branch, remote="origin"):
            return remote == "upstream"
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", side_effect=remote_check), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")), \
             patch.object(branch_recovery, "_reflog_recover", return_value=(False, "n/a")):
            result = branch_recovery.recover_branch("/fake/repo", "feature-y")
            self.assertEqual(result["status"], "recovered")
            self.assertIn("upstream", result["action_taken"])


class TestRecoverBranchReflog(unittest.TestCase):
    """Strategy 2: reflog recovery."""

    def test_reflog_recovery_success(self):
        """When branch is found in reflog and recent, recovers it."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=False), \
             patch.object(branch_recovery, "_reflog_recover",
                          return_value=(True, "restored from reflog (abc12345)")):
            result = branch_recovery.recover_branch("/fake/repo", "hotfix-z")
            self.assertEqual(result["status"], "recovered")
            self.assertIn("reflog", result["action_taken"])

    def test_reflog_stale_branch_unrecoverable(self):
        """When reflog entry is too old, branch is unrecoverable."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=False), \
             patch.object(branch_recovery, "_reflog_recover",
                          return_value=(False, "reflog entry too old (2025-01-01)")):
            result = branch_recovery.recover_branch("/fake/repo", "old-branch")
            self.assertEqual(result["status"], "unrecoverable")
            self.assertIn("exhausted", result["action_taken"])


class TestRecoverBranchStale(unittest.TestCase):
    """Strategy 3: stale branches marked unrecoverable."""

    def test_stale_over_30_days_unrecoverable(self):
        """Reflog helper rejects commits older than STALE_DAYS."""
        old_date = (datetime.utcnow() - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S +0000")
        sha = "a" * 40
        reflog_line = f"{sha} HEAD@{{0}} checkout: moving from master to old-feat"
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "STALE_DAYS", 30), \
             patch.object(branch_recovery, "_git") as mock_git:
            def git_side_effect(repo, *args):
                cmd = args[0] if args else ""
                if cmd == "rev-parse" and "--is-inside-work-tree" in args:
                    return 0, "true", ""
                if cmd == "rev-parse" and "--verify" in args:
                    return 1, "", "not found"  # branch missing
                if cmd == "ls-remote":
                    return 0, "", ""  # not on remote
                if cmd == "reflog":
                    return 0, reflog_line, ""
                if cmd == "show":
                    return 0, old_date, ""
                return 0, "", ""
            mock_git.side_effect = git_side_effect
            result = branch_recovery.recover_branch("/fake/repo", "old-feat")
            self.assertEqual(result["status"], "unrecoverable")


class TestDetectMissingBranches(unittest.TestCase):
    """Test detect_missing_branches function."""

    def test_all_present(self):
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=True):
            missing = branch_recovery.detect_missing_branches("/repo", ["a", "b"])
            self.assertEqual(missing, [])

    def test_some_missing(self):
        def exists(repo, branch):
            return branch == "a"
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", side_effect=exists):
            missing = branch_recovery.detect_missing_branches("/repo", ["a", "b", "c"])
            self.assertEqual(missing, ["b", "c"])

    def test_empty_expected(self):
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True):
            missing = branch_recovery.detect_missing_branches("/repo", [])
            self.assertEqual(missing, [])

    def test_bad_path_returns_empty(self):
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=False):
            missing = branch_recovery.detect_missing_branches("/no/such/path", ["x"])
            self.assertEqual(missing, [])


class TestFeatureFlagDisabled(unittest.TestCase):
    """Behavior when ORCH_BRANCH_RECOVERY_ENABLED is off."""

    def test_recover_disabled(self):
        with patch.object(branch_recovery, "ENABLED", False):
            result = branch_recovery.recover_branch("/repo", "feat")
            self.assertEqual(result["status"], "unrecoverable")
            self.assertIn("disabled", result["action_taken"])

    def test_detect_disabled(self):
        with patch.object(branch_recovery, "ENABLED", False):
            missing = branch_recovery.detect_missing_branches("/repo", ["a", "b"])
            self.assertEqual(missing, [])


class TestStats(unittest.TestCase):
    """Test stats() output."""

    def test_stats_returns_dict(self):
        s = branch_recovery.stats()
        self.assertIsInstance(s, dict)

    def test_stats_has_expected_keys(self):
        s = branch_recovery.stats()
        for key in ("recover_attempts", "recover_fetched", "recover_reflog",
                     "recover_unrecoverable", "recover_errors",
                     "detect_calls", "detect_missing_found"):
            self.assertIn(key, s)

    def test_stats_is_snapshot(self):
        """Mutating returned dict does not affect internal counters."""
        s = branch_recovery.stats()
        s["recover_attempts"] = 999
        self.assertNotEqual(branch_recovery.stats()["recover_attempts"], 999)


class TestErrorHandling(unittest.TestCase):
    """Error handling for bad inputs."""

    def test_invalid_path(self):
        with patch.object(branch_recovery, "ENABLED", True):
            result = branch_recovery.recover_branch("/no/such/dir", "feat")
            self.assertEqual(result["status"], "unrecoverable")
            self.assertIn("invalid git path", result["action_taken"])

    def test_none_path(self):
        with patch.object(branch_recovery, "ENABLED", True):
            result = branch_recovery.recover_branch(None, "feat")
            self.assertEqual(result["status"], "unrecoverable")

    def test_branch_already_exists(self):
        """If the branch already exists locally, report recovered."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=True):
            result = branch_recovery.recover_branch("/repo", "exists")
            self.assertEqual(result["status"], "recovered")
            self.assertIn("already exists", result["action_taken"])


class TestGitHelpers(unittest.TestCase):
    """Low-level git helper coverage."""

    def test_git_timeout(self):
        with patch("branch_recovery.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("git", 60)):
            rc, out, err = branch_recovery._git("/tmp", "status")
            self.assertEqual(rc, -1)
            self.assertIn("timeout", err)


    def test_git_generic_exception(self):
        with patch("branch_recovery.subprocess.run",
                   side_effect=OSError("bad")):
            rc, out, err = branch_recovery._git("/tmp", "status")
            self.assertEqual(rc, -1)
            self.assertIn("bad", err)

    def test_is_git_repo_none_path(self):
        self.assertFalse(branch_recovery._is_git_repo(None))

    def test_is_git_repo_nonexistent(self):
        self.assertFalse(branch_recovery._is_git_repo("/no/such/path/ever"))


if __name__ == "__main__":
    unittest.main()
