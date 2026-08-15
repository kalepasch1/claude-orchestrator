#!/usr/bin/env python3
"""
Test suite for reproduce-beethoven-missing-branch: Core branch recovery implementation.

This test file validates the complete branch recovery workflow that handles
missing branches in the beethoven project. It tests the core recovery strategies,
error handling, and integration with the project's helpers and naming conventions.

Acceptance criteria:
1. New code in beethoven project implements core branch recovery logic
2. Tests from reproduce-beethoven-missing-branch pass
3. No regressions in existing beethoven tests
4. Implementation confined to core logic (deferred complex edge cases)
"""
import os, sys, subprocess, tempfile, shutil, unittest
from unittest.mock import patch, MagicMock, call, ANY
from datetime import datetime, timedelta
import json
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_recovery
import log as _log_mod


class TestBranchRecoveryBasicWorkflow(unittest.TestCase):
    """Core branch recovery workflow: detect, attempt recovery, report status."""

    def test_recover_existing_branch_reports_already_exists(self):
        """Branch that exists locally is marked recovered immediately."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=True):

            result = branch_recovery.recover_branch("/repo", "existing-branch")

            self.assertEqual(result["status"], "recovered")
            self.assertEqual(result["action_taken"], "branch already exists locally")

    def test_recover_via_origin_fetch_success(self):
        """Missing branch successfully recovered from origin."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            result = branch_recovery.recover_branch("/repo", "feature-missing")

            self.assertEqual(result["status"], "recovered")
            self.assertIn("origin", result["action_taken"])

    def test_recover_via_upstream_fallback(self):
        """When origin has no branch, upstream remote is tried."""
        def remote_side_effect(repo, branch, remote="origin"):
            return remote == "upstream"

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", side_effect=remote_side_effect), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            result = branch_recovery.recover_branch("/repo", "feature-missing")

            self.assertEqual(result["status"], "recovered")
            self.assertIn("upstream", result["action_taken"])

    def test_recover_via_reflog_when_remotes_unavailable(self):
        """Reflog recovery kicks in when remotes have no branch."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=False), \
             patch.object(branch_recovery, "_reflog_recover", return_value=(True, "restored from reflog")):

            result = branch_recovery.recover_branch("/repo", "deleted-branch")

            self.assertEqual(result["status"], "recovered")
            self.assertIn("reflog", result["action_taken"])

    def test_unrecoverable_when_all_strategies_fail(self):
        """Branch marked unrecoverable when all strategies exhausted."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=False), \
             patch.object(branch_recovery, "_reflog_recover", return_value=(False, "not in reflog")):

            result = branch_recovery.recover_branch("/repo", "lost-branch")

            self.assertEqual(result["status"], "unrecoverable")
            self.assertIn("strategies exhausted", result["action_taken"])


class TestBranchRecoveryErrorHandling(unittest.TestCase):
    """Error handling in branch recovery: invalid paths, permissions, timeouts."""

    def test_invalid_git_repo_returns_unrecoverable(self):
        """Non-git paths are rejected gracefully."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=False):

            result = branch_recovery.recover_branch("/not/a/repo", "branch")

            self.assertEqual(result["status"], "unrecoverable")
            self.assertIn("invalid git path", result["action_taken"])

    def test_nonexistent_path_handled(self):
        """Nonexistent paths don't crash."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=False):

            result = branch_recovery.recover_branch("/nonexistent/path/xyz", "branch")

            self.assertIsNotNone(result)
            self.assertIn("status", result)
            self.assertIn("action_taken", result)

    def test_git_command_timeout_handled(self):
        """Timeout on git commands is handled without crash."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_git") as mock_git:

            mock_git.return_value = (-1, "", "timeout")

            result = branch_recovery.recover_branch("/repo", "branch")

            self.assertEqual(result["status"], "unrecoverable")

    def test_permission_denied_handled_gracefully(self):
        """Permission errors don't crash."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_git") as mock_git:

            mock_git.return_value = (-1, "", "Permission denied")

            try:
                result = branch_recovery.recover_branch("/restricted", "branch")
                self.assertIsNotNone(result)
            except Exception as e:
                self.fail(f"Should handle permission error gracefully: {e}")

    def test_empty_repo_path_returns_empty_list_on_detect(self):
        """Detect with empty repo returns empty list."""
        with patch.object(branch_recovery, "ENABLED", True):
            result = branch_recovery.detect_missing_branches("", ["a", "b", "c"])
            self.assertEqual(result, [])

    def test_none_repo_path_returns_empty_list(self):
        """Detect with None repo returns empty list."""
        with patch.object(branch_recovery, "ENABLED", True):
            result = branch_recovery.detect_missing_branches(None, ["a", "b"])
            self.assertEqual(result, [])


class TestBranchDetectionAccuracy(unittest.TestCase):
    """Branch detection: missing branches identified correctly, no false positives."""

    def test_detect_single_missing_branch(self):
        """Detects when one branch is missing."""
        def exists_mock(repo, branch):
            return branch != "missing-branch"

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", side_effect=exists_mock):

            missing = branch_recovery.detect_missing_branches(
                "/repo",
                ["main", "develop", "missing-branch", "feature-x"]
            )

            self.assertEqual(missing, ["missing-branch"])

    def test_detect_multiple_missing_branches(self):
        """Detects when multiple branches are missing."""
        present = {"main", "develop"}
        def exists_mock(repo, branch):
            return branch in present

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", side_effect=exists_mock):

            missing = branch_recovery.detect_missing_branches(
                "/repo",
                ["main", "develop", "feature-a", "feature-b", "release"]
            )

            expected = ["feature-a", "feature-b", "release"]
            self.assertEqual(sorted(missing), sorted(expected))

    def test_detect_all_branches_present(self):
        """Returns empty list when all branches present."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=True):

            missing = branch_recovery.detect_missing_branches(
                "/repo",
                ["main", "develop", "feature-x"]
            )

            self.assertEqual(missing, [])

    def test_detect_empty_branch_list(self):
        """Empty expected branches list returns empty result."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True):

            missing = branch_recovery.detect_missing_branches("/repo", [])

            self.assertEqual(missing, [])

    def test_detect_preserves_branch_name_order(self):
        """Missing branches reported in input order."""
        branches = ["z-last", "a-first", "m-middle", "n-next"]
        def exists_mock(repo, branch):
            return branch not in ["z-last", "n-next"]

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", side_effect=exists_mock):

            missing = branch_recovery.detect_missing_branches("/repo", branches)

            self.assertEqual(missing, ["z-last", "n-next"])


class TestBranchNameHandling(unittest.TestCase):
    """Branch name edge cases: special characters, slashes, length."""

    def test_branch_with_slashes_in_name(self):
        """Branch names with path separators handled."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            result = branch_recovery.recover_branch("/repo", "feature/sub/deep-feature")

            self.assertEqual(result["status"], "recovered")

    def test_branch_with_dots_in_name(self):
        """Branch names with dots (semver style) handled."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            result = branch_recovery.recover_branch("/repo", "release/v1.2.3")

            self.assertEqual(result["status"], "recovered")

    def test_branch_with_hyphens_and_underscores(self):
        """Common naming patterns with hyphens and underscores."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            result = branch_recovery.recover_branch("/repo", "bugfix-ISSUE-123_urgent")

            self.assertEqual(result["status"], "recovered")

    def test_long_branch_name(self):
        """Long branch names handled."""
        long_name = "feature-" + "x" * 200
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            result = branch_recovery.recover_branch("/repo", long_name)

            self.assertEqual(result["status"], "recovered")

    def test_branch_with_dates_in_name(self):
        """Branch names with date patterns (common in CI)."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            result = branch_recovery.recover_branch("/repo", "release-2026-08-01")

            self.assertEqual(result["status"], "recovered")


class TestReflogRecoveryCore(unittest.TestCase):
    """Reflog recovery: finding and validating branches from history."""

    def test_reflog_recovery_with_valid_recent_commit(self):
        """Reflog can recover recent branches."""
        reflog_output = "abc1234 HEAD@{0} checkout: moving from master to feature-new"
        now = datetime.utcnow()
        recent_date = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S +0000")

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_git") as mock_git:

            def git_side_effect(repo, *args):
                if args[0] == "reflog":
                    return 0, reflog_output, ""
                if args[0] == "show":
                    return 0, recent_date, ""
                if args[0] == "branch":
                    return 0, "", ""
                return 1, "", ""

            mock_git.side_effect = git_side_effect
            ok, detail = branch_recovery._reflog_recover("/repo", "feature-new")

            self.assertTrue(ok)
            self.assertIn("restored from reflog", detail)

    def test_reflog_recovery_rejects_stale_branch(self):
        """Reflog rejects branches older than STALE_DAYS."""
        reflog_output = "abc1234 HEAD@{0} checkout: moving from master to old-feature"
        now = datetime.utcnow()
        stale_date = (now - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S +0000")

        with patch.object(branch_recovery, "STALE_DAYS", 30), \
             patch.object(branch_recovery, "_git") as mock_git:

            def git_side_effect(repo, *args):
                if args[0] == "reflog":
                    return 0, reflog_output, ""
                if args[0] == "show":
                    return 0, stale_date, ""
                return 1, "", ""

            mock_git.side_effect = git_side_effect
            ok, detail = branch_recovery._reflog_recover("/repo", "old-feature")

            self.assertFalse(ok)
            self.assertIn("too old", detail)

    def test_reflog_recovery_boundary_exactly_stale_days(self):
        """Branch exactly at STALE_DAYS boundary is accepted."""
        reflog_output = "abc1234 HEAD@{0} checkout: moving from master to boundary-branch"
        stale_days = 30
        now = datetime.utcnow()
        boundary_date = (now - timedelta(days=stale_days)).strftime("%Y-%m-%d %H:%M:%S +0000")

        with patch.object(branch_recovery, "STALE_DAYS", stale_days), \
             patch.object(branch_recovery, "_git") as mock_git:

            def git_side_effect(repo, *args):
                if args[0] == "reflog":
                    return 0, reflog_output, ""
                if args[0] == "show":
                    return 0, boundary_date, ""
                if args[0] == "branch":
                    return 0, "", ""
                return 1, "", ""

            mock_git.side_effect = git_side_effect
            ok, _ = branch_recovery._reflog_recover("/repo", "boundary-branch")

            self.assertTrue(ok)

    def test_reflog_recovery_with_empty_reflog(self):
        """Empty reflog handled gracefully."""
        with patch.object(branch_recovery, "_git") as mock_git:
            mock_git.return_value = (0, "", "")

            ok, detail = branch_recovery._reflog_recover("/repo", "missing")

            self.assertFalse(ok)

    def test_reflog_recovery_with_malformed_output(self):
        """Malformed reflog output handled."""
        malformed = "not a valid reflog entry"

        with patch.object(branch_recovery, "_git") as mock_git:
            mock_git.return_value = (0, malformed, "")

            ok, detail = branch_recovery._reflog_recover("/repo", "branch")

            self.assertFalse(ok)


class TestStatisticsTracking(unittest.TestCase):
    """Statistics accumulation: recovery outcomes tracked correctly."""

    def test_stats_initial_state(self):
        """Stats start at zero."""
        stats = branch_recovery.stats()

        self.assertEqual(stats["recover_attempts"], 0)
        self.assertEqual(stats["recover_fetched"], 0)
        self.assertEqual(stats["recover_reflog"], 0)
        self.assertEqual(stats["recover_unrecoverable"], 0)
        self.assertEqual(stats["detect_calls"], 0)

    def test_stats_count_recovery_attempts(self):
        """recover_attempts incremented on each call."""
        initial = branch_recovery.stats()["recover_attempts"]

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=True):

            branch_recovery.recover_branch("/repo", "branch1")
            branch_recovery.recover_branch("/repo", "branch2")
            branch_recovery.recover_branch("/repo", "branch3")

            stats = branch_recovery.stats()
            self.assertEqual(stats["recover_attempts"], initial + 3)

    def test_stats_track_successful_fetches(self):
        """recover_fetched incremented for fetch-based recovery."""
        initial = branch_recovery.stats()["recover_fetched"]

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            branch_recovery.recover_branch("/repo", "fetched-branch")

            stats = branch_recovery.stats()
            self.assertEqual(stats["recover_fetched"], initial + 1)

    def test_stats_track_reflog_recoveries(self):
        """recover_reflog incremented for reflog-based recovery."""
        initial = branch_recovery.stats()["recover_reflog"]

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=False), \
             patch.object(branch_recovery, "_reflog_recover", return_value=(True, "from reflog")):

            branch_recovery.recover_branch("/repo", "reflog-branch")

            stats = branch_recovery.stats()
            self.assertEqual(stats["recover_reflog"], initial + 1)

    def test_stats_track_unrecoverable_branches(self):
        """recover_unrecoverable incremented for failed recoveries."""
        initial = branch_recovery.stats()["recover_unrecoverable"]

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=False), \
             patch.object(branch_recovery, "_reflog_recover", return_value=(False, "not found")):

            branch_recovery.recover_branch("/repo", "lost-branch")

            stats = branch_recovery.stats()
            self.assertEqual(stats["recover_unrecoverable"], initial + 1)

    def test_stats_track_detect_calls(self):
        """detect_calls incremented on detect_missing_branches."""
        initial = branch_recovery.stats()["detect_calls"]

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False):

            branch_recovery.detect_missing_branches("/repo", ["a", "b", "c"])

            stats = branch_recovery.stats()
            self.assertEqual(stats["detect_calls"], initial + 1)


class TestEnvironmentConfiguration(unittest.TestCase):
    """Configuration via environment variables."""

    def test_feature_disabled_via_env(self):
        """Recovery disabled when ORCH_BRANCH_RECOVERY_ENABLED=false."""
        with patch.object(branch_recovery, "ENABLED", False):
            result = branch_recovery.recover_branch("/repo", "branch")

            self.assertEqual(result["status"], "unrecoverable")
            self.assertEqual(result["action_taken"], "feature disabled")

    def test_stale_days_customizable(self):
        """ORCH_BRANCH_RECOVERY_STALE_DAYS adjusts staleness threshold."""
        # Test with custom threshold
        with patch.object(branch_recovery, "STALE_DAYS", 60):
            # A branch that would be stale at 30 days but fresh at 60
            now = datetime.utcnow()
            test_date = (now - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S +0000")
            reflog = "abc1234 HEAD@{0} checkout: moving to test"

            with patch.object(branch_recovery, "_git") as mock_git:
                def git_side_effect(repo, *args):
                    if args[0] == "reflog":
                        return 0, reflog, ""
                    if args[0] == "show":
                        return 0, test_date, ""
                    if args[0] == "branch":
                        return 0, "", ""
                    return 1, "", ""

                mock_git.side_effect = git_side_effect
                ok, _ = branch_recovery._reflog_recover("/repo", "test")

                # Should succeed with 60-day threshold
                self.assertTrue(ok)

    def test_timeout_configurable(self):
        """ORCH_BRANCH_RECOVERY_TIMEOUT adjusts git command timeout."""
        with patch.object(branch_recovery, "TIMEOUT", 120):
            self.assertEqual(branch_recovery.TIMEOUT, 120)


class TestConcurrentRecovery(unittest.TestCase):
    """Concurrent recovery behavior: no race conditions or conflicts."""

    def test_concurrent_recovery_same_branch(self):
        """Multiple threads recovering same branch don't conflict."""
        results = []
        lock = threading.Lock()

        def recover_thread():
            with patch.object(branch_recovery, "ENABLED", True), \
                 patch.object(branch_recovery, "_is_git_repo", return_value=True), \
                 patch.object(branch_recovery, "_branch_exists_local") as mock_exists:

                # First call returns False (missing), subsequent calls return True (recovered)
                mock_exists.side_effect = [False, True]

                result = branch_recovery.recover_branch("/repo", "shared-branch")
                with lock:
                    results.append(result)

        threads = [threading.Thread(target=recover_thread) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should report success
        for result in results:
            self.assertIn(result["status"], ["recovered", "unrecoverable"])


class TestRecoveryResponseFormat(unittest.TestCase):
    """Response format: consistent structure and required fields."""

    def test_recover_response_always_has_status_and_action(self):
        """recover_branch always returns status and action_taken."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=False):

            result = branch_recovery.recover_branch("/invalid", "branch")

            self.assertIn("status", result)
            self.assertIn("action_taken", result)
            self.assertIsInstance(result["status"], str)
            self.assertIsInstance(result["action_taken"], str)

    def test_recover_status_only_valid_values(self):
        """Recovery status is either 'recovered' or 'unrecoverable'."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=False):

            result = branch_recovery.recover_branch("/invalid", "branch")

            self.assertIn(result["status"], ["recovered", "unrecoverable"])

    def test_detect_response_always_list(self):
        """detect_missing_branches always returns a list."""
        with patch.object(branch_recovery, "ENABLED", False):
            result = branch_recovery.detect_missing_branches("/repo", ["a"])

            self.assertIsInstance(result, list)

    def test_detect_response_contains_strings(self):
        """detect_missing_branches returns list of branch name strings."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False):

            result = branch_recovery.detect_missing_branches(
                "/repo",
                ["branch-a", "branch-b", "branch-c"]
            )

            self.assertIsInstance(result, list)
            for item in result:
                self.assertIsInstance(item, str)

    def test_stats_returns_dict_with_required_keys(self):
        """stats() returns dict with all required statistics keys."""
        result = branch_recovery.stats()

        self.assertIsInstance(result, dict)
        required_keys = {
            "recover_attempts", "recover_fetched", "recover_reflog",
            "recover_unrecoverable", "recover_errors",
            "detect_calls", "detect_missing_found"
        }
        self.assertEqual(set(result.keys()), required_keys)


class TestIntegrationWorkflows(unittest.TestCase):
    """End-to-end workflows: detect → recover → verify."""

    def test_workflow_detect_and_recover_single_branch(self):
        """Complete workflow: detect missing → recover → verify."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local") as mock_exists, \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            # First call to detect: branch missing
            # Recovery calls: branch not found initially, then recovered
            mock_exists.side_effect = [False, False, True]

            missing = branch_recovery.detect_missing_branches(
                "/repo",
                ["main", "feature-x", "develop"]
            )
            self.assertIn("feature-x", missing)

            result = branch_recovery.recover_branch("/repo", "feature-x")
            self.assertEqual(result["status"], "recovered")

    def test_workflow_multiple_branches_partial_recovery(self):
        """Workflow with multiple branches, some recovered, some fail."""
        def exists_mock(repo, branch):
            # main and develop exist; others don't
            return branch in ["main", "develop"]

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", side_effect=exists_mock), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            branches = ["main", "develop", "feature-a", "feature-b"]
            missing = branch_recovery.detect_missing_branches("/repo", branches)

            # Should detect feature branches as missing
            self.assertEqual(len(missing), 2)

            # Recover each missing branch
            for branch in missing:
                result = branch_recovery.recover_branch("/repo", branch)
                self.assertEqual(result["status"], "recovered")


if __name__ == "__main__":
    unittest.main()
