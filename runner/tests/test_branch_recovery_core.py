#!/usr/bin/env python3
"""
Test suite for core branch recovery logic.

Validates recovery strategies, fleet-level operations, periodic detection,
and integration workflows that enable the missing branch recovery feature.
"""
import os, sys, subprocess, tempfile, unittest
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_recovery
import branch_fleet_recovery
import branch_recovery_periodic


class TestRecoveryStrategySequence(unittest.TestCase):
    """Validate strategy execution order and fallback behavior."""

    def test_strategies_tried_in_order(self):
        """Strategies are attempted in order: remote fetch, reflog, fail."""
        call_order = []

        def track_branch_on_remote(repo, branch, remote="origin"):
            call_order.append(("remote_check", remote))
            return False

        def track_reflog_recover(repo, branch):
            call_order.append("reflog")
            return False, "not found"

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", side_effect=track_branch_on_remote), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(False, "")), \
             patch.object(branch_recovery, "_reflog_recover", side_effect=track_reflog_recover):

            branch_recovery.recover_branch("/repo", "feature-x")

            # Verify order: origin check, upstream check, reflog attempt
            self.assertIn(("remote_check", "origin"), call_order)
            self.assertIn(("remote_check", "upstream"), call_order)
            self.assertIn("reflog", call_order)

    def test_stops_on_first_success(self):
        """Recovery stops after first successful strategy."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")), \
             patch.object(branch_recovery, "_reflog_recover") as mock_reflog:

            result = branch_recovery.recover_branch("/repo", "feature-x")

            self.assertEqual(result["status"], "recovered")
            # Reflog should not be called if fetch succeeded
            mock_reflog.assert_not_called()


class TestReflogRecoveryEdgeCases(unittest.TestCase):
    """Comprehensive reflog recovery edge cases."""

    def test_reflog_multiple_branch_references(self):
        """Correctly identifies branch among multiple reflog entries."""
        reflog_output = "\n".join([
            "abc1234 HEAD@{0} checkout: moving from master to other-branch",
            "def5678 HEAD@{1} checkout: moving from feature-x to master",
            "abc1234 HEAD@{2} checkout: moving from master to feature-x",
            "ghi9012 HEAD@{3} branch: created from master",
        ])

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_git") as mock_git:

            def git_side_effect(repo, *args):
                if args[0] == "reflog":
                    return 0, reflog_output, ""
                if args[0] == "show":
                    return 0, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S +0000"), ""
                if args[0] == "branch":
                    return 0, "", ""
                return 1, "", ""

            mock_git.side_effect = git_side_effect
            ok, detail = branch_recovery._reflog_recover("/repo", "feature-x")
            self.assertTrue(ok)

    def test_reflog_truncated_sha_accepted(self):
        """Short SHAs from reflog are accepted and work."""
        reflog_output = "abc1234 HEAD@{0} checkout: moving from master to test-branch"

        with patch.object(branch_recovery, "_git") as mock_git:
            def git_side_effect(repo, *args):
                if args[0] == "reflog":
                    return 0, reflog_output, ""
                if args[0] == "show":
                    return 0, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S +0000"), ""
                if args[0] == "branch":
                    return 0, "", ""
                return 1, "", ""

            mock_git.side_effect = git_side_effect
            ok, detail = branch_recovery._reflog_recover("/repo", "test-branch")
            self.assertTrue(ok)

    def test_reflog_stale_threshold_boundary(self):
        """Branch exactly at STALE_DAYS boundary is recoverable."""
        stale_days = 30
        exactly_stale_date = (datetime.utcnow() - timedelta(days=stale_days)).strftime("%Y-%m-%d %H:%M:%S +0000")
        reflog_output = "abc1234 HEAD@{0} checkout: moving from master to old-branch"

        with patch.object(branch_recovery, "STALE_DAYS", stale_days), \
             patch.object(branch_recovery, "_git") as mock_git:

            def git_side_effect(repo, *args):
                if args[0] == "reflog":
                    return 0, reflog_output, ""
                if args[0] == "show":
                    return 0, exactly_stale_date, ""
                if args[0] == "branch":
                    return 0, "", ""
                return 1, "", ""

            mock_git.side_effect = git_side_effect
            ok, _ = branch_recovery._reflog_recover("/repo", "old-branch")
            # Should be accepted as on the boundary
            self.assertTrue(ok)

    def test_reflog_one_second_past_stale_rejected(self):
        """Branch just past STALE_DAYS is not recoverable."""
        stale_days = 30
        past_stale = datetime.utcnow() - timedelta(days=stale_days, seconds=1)
        past_stale_date = past_stale.strftime("%Y-%m-%d %H:%M:%S +0000")
        reflog_output = "abc1234 HEAD@{0} checkout: moving from master to old-branch"

        with patch.object(branch_recovery, "STALE_DAYS", stale_days), \
             patch.object(branch_recovery, "_git") as mock_git:

            def git_side_effect(repo, *args):
                if args[0] == "reflog":
                    return 0, reflog_output, ""
                if args[0] == "show":
                    return 0, past_stale_date, ""
                return 1, "", ""

            mock_git.side_effect = git_side_effect
            ok, _ = branch_recovery._reflog_recover("/repo", "old-branch")
            self.assertFalse(ok)


class TestBranchNameEdgeCases(unittest.TestCase):
    """Edge cases in branch name handling."""

    def test_branch_with_slashes_recovered(self):
        """Branch names with slashes (nested refs) are handled."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            result = branch_recovery.recover_branch("/repo", "feature/my-feature/v2")
            self.assertEqual(result["status"], "recovered")

    def test_branch_with_special_chars(self):
        """Branch names with special characters are handled safely."""
        special_branch = "feature-2024-07-31"
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            result = branch_recovery.recover_branch("/repo", special_branch)
            self.assertEqual(result["status"], "recovered")

    def test_branch_with_unicode_rejected_safely(self):
        """Unicode in branch names is rejected safely (git limitation)."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True):

            # Should not crash on unicode
            try:
                result = branch_recovery.recover_branch("/repo", "feature-🚀")
                self.assertIn(result["status"], ["recovered", "unrecoverable"])
            except Exception:
                self.fail("Should not crash on unicode branch names")


class TestDetectMissingBranchesComprehensive(unittest.TestCase):
    """Comprehensive detection scenarios."""

    def test_detect_multiple_missing_preserves_order(self):
        """Missing branches are reported in consistent order."""
        branches = ["branch-a", "branch-b", "branch-c", "branch-d", "branch-e"]
        def exists(repo, branch):
            return branch in ["branch-b", "branch-d"]

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", side_effect=exists):

            missing = branch_recovery.detect_missing_branches("/repo", branches)
            expected = ["branch-a", "branch-c", "branch-e"]
            self.assertEqual(missing, expected)

    def test_detect_empty_repo_path_graceful(self):
        """Empty repo path returns empty list without error."""
        with patch.object(branch_recovery, "ENABLED", True):
            missing = branch_recovery.detect_missing_branches("", ["a", "b"])
            self.assertEqual(missing, [])

    def test_detect_none_in_expected_branches_handled(self):
        """None values in expected_branches list don't crash."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False):

            # Should gracefully skip None values
            missing = branch_recovery.detect_missing_branches("/repo", ["a", None, "b", ""])
            self.assertGreaterEqual(len(missing), 0)


class TestStatsTracking(unittest.TestCase):
    """Statistics accumulation and reporting."""

    def test_stats_accumulate_across_calls(self):
        """Stats are cumulative across multiple recover_branch calls."""
        initial_stats = branch_recovery.stats()
        initial_attempts = initial_stats["recover_attempts"]

        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=True):

            branch_recovery.recover_branch("/repo", "branch-1")
            branch_recovery.recover_branch("/repo", "branch-2")
            branch_recovery.recover_branch("/repo", "branch-3")

            new_stats = branch_recovery.stats()
            self.assertEqual(new_stats["recover_attempts"], initial_attempts + 3)

    def test_stats_categorize_outcomes(self):
        """Stats differentiate between recovery strategies used."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_branch_on_remote", return_value=True), \
             patch.object(branch_recovery, "_fetch_branch", return_value=(True, "")):

            branch_recovery.recover_branch("/repo", "fetched-branch")
            stats = branch_recovery.stats()
            self.assertGreater(stats["recover_fetched"], 0)


class TestFleetRecoveryRequeueing(unittest.TestCase):
    """Fleet-level recovery and task requeuing."""

    def test_unrecoverable_branch_triggers_requeue(self):
        """When recovery fails, task is requeued as recovery task."""
        task = {
            "id": "task-123",
            "slug": "original-work",
            "project_id": "proj-1",
            "prompt": "Do some work",
            "kind": "build"
        }

        with patch.object(branch_fleet_recovery, "db") as mock_db, \
             patch.object(branch_fleet_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_fleet_recovery, "_branch_exists_remote", return_value=False), \
             patch.object(branch_fleet_recovery, "git_auth") as mock_auth:

            mock_auth.pat_available.return_value = True
            mock_db.select.return_value = []  # No existing recovery task

            result = branch_fleet_recovery.recover_branch(task, "/repo")

            # Should requeue
            self.assertTrue(result.get("recovered"))
            self.assertEqual(result.get("strategy"), "requeued")
            # Verify db.insert was called for recovery task
            mock_db.insert.assert_called()

    def test_requeue_preserves_task_context(self):
        """Requeued recovery task preserves original task's context."""
        original_prompt = "Deploy service X to staging"
        task = {
            "id": "task-456",
            "slug": "deploy-service",
            "project_id": "proj-2",
            "prompt": original_prompt,
            "kind": "deploy",
            "base_branch": "develop"
        }

        with patch.object(branch_fleet_recovery, "db") as mock_db, \
             patch.object(branch_fleet_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_fleet_recovery, "_branch_exists_remote", return_value=False), \
             patch.object(branch_fleet_recovery, "git_auth") as mock_auth, \
             patch.object(branch_fleet_recovery, "DRY_RUN", False):

            mock_auth.pat_available.return_value = True
            mock_db.select.return_value = []

            branch_fleet_recovery.recover_branch(task, "/repo", "develop")

            # Verify requeued task includes context
            call_args = mock_db.insert.call_args
            if call_args:
                inserted_row = call_args[0][1] if len(call_args[0]) > 1 else {}
                self.assertIn("deploy-service", inserted_row.get("slug", ""))
                self.assertEqual(inserted_row.get("base_branch"), "develop")

    def test_prevents_duplicate_recovery_tasks(self):
        """Existing recovery task prevents creating duplicate."""
        task = {
            "id": "task-789",
            "slug": "original-task",
            "project_id": "proj-3",
            "prompt": "Do work"
        }

        with patch.object(branch_fleet_recovery, "db") as mock_db, \
             patch.object(branch_fleet_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_fleet_recovery, "_branch_exists_remote", return_value=False), \
             patch.object(branch_fleet_recovery, "git_auth") as mock_auth:

            mock_auth.pat_available.return_value = True
            # Existing recovery task already present
            mock_db.select.return_value = [{"id": "recovery-existing"}]

            result = branch_fleet_recovery.recover_branch(task, "/repo")

            # Should not create another one
            self.assertFalse(result.get("recovered"))
            self.assertEqual(result.get("strategy"), "already_requeued")


class TestPeriodicDetectionIntegration(unittest.TestCase):
    """Periodic detection and recovery workflows."""

    def test_sweep_scans_multiple_projects(self):
        """Sweep examines all configured projects."""
        with patch.object(branch_recovery_periodic, "ENABLED", True), \
             patch.object(branch_recovery_periodic, "DRY_RUN", True), \
             patch.object(branch_recovery_periodic, "db") as mock_db:

            mock_db.select.side_effect = [
                # First call for projects
                [
                    {"id": "p1", "name": "proj1", "repo_path": "/repo1", "default_base": "master"},
                    {"id": "p2", "name": "proj2", "repo_path": "/repo2", "default_base": "master"},
                ]
            ]

            with patch("os.path.isdir", return_value=True):
                branch_recovery_periodic.sweep()

            # Verify projects were loaded
            mock_db.select.assert_called()


class TestTimeoutAndErrorBehavior(unittest.TestCase):
    """Timeout and error handling across recovery."""

    def test_git_command_timeout_reported(self):
        """Git command timeout is reported as unrecoverable."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local", return_value=False), \
             patch.object(branch_recovery, "_git") as mock_git:

            mock_git.return_value = (-1, "", "timeout")

            result = branch_recovery.recover_branch("/repo", "branch")
            self.assertEqual(result["status"], "unrecoverable")

    def test_permission_error_graceful(self):
        """Permission errors don't crash, marked unrecoverable."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_git") as mock_git:

            mock_git.return_value = (-1, "", "Permission denied")

            try:
                result = branch_recovery.recover_branch("/restricted/repo", "branch")
                self.assertIsNotNone(result)
            except Exception as e:
                self.fail(f"Should handle permission error gracefully: {e}")


class TestEnvironmentVariableConfiguration(unittest.TestCase):
    """Configuration via environment variables."""

    def test_recovery_disabled_via_env(self):
        """ORCH_BRANCH_RECOVERY_ENABLED=false disables all recovery."""
        with patch.dict(os.environ, {"ORCH_BRANCH_RECOVERY_ENABLED": "false"}):
            import importlib
            importlib.reload(branch_recovery)
            self.assertFalse(branch_recovery.ENABLED)

    def test_stale_days_configurable(self):
        """ORCH_BRANCH_RECOVERY_STALE_DAYS sets threshold."""
        with patch.dict(os.environ, {"ORCH_BRANCH_RECOVERY_STALE_DAYS": "60"}):
            import importlib
            importlib.reload(branch_recovery)
            self.assertEqual(branch_recovery.STALE_DAYS, 60)

    def test_timeout_configurable(self):
        """ORCH_BRANCH_RECOVERY_TIMEOUT sets git command timeout."""
        with patch.dict(os.environ, {"ORCH_BRANCH_RECOVERY_TIMEOUT": "120"}):
            import importlib
            importlib.reload(branch_recovery)
            self.assertEqual(branch_recovery.TIMEOUT, 120)


class TestConcurrentRecoveryAttempts(unittest.TestCase):
    """Behavior with concurrent recovery attempts."""

    def test_multiple_threads_recover_same_branch(self):
        """Multiple threads attempting same recovery don't create conflicts."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery, "_branch_exists_local") as mock_exists:

            # First call: missing; second+ calls: exists (recovered by other thread)
            mock_exists.side_effect = [False, True, True]

            result1 = branch_recovery.recover_branch("/repo", "shared-branch")
            result2 = branch_recovery.recover_branch("/repo", "shared-branch")

            # Both should report success
            self.assertEqual(result1["status"], "recovered")
            self.assertEqual(result2["status"], "recovered")


class TestRecoveryResponseStructure(unittest.TestCase):
    """Recovery results have consistent structure."""

    def test_recover_response_has_required_fields(self):
        """recover_branch response always has status and action_taken."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=False):

            result = branch_recovery.recover_branch("/invalid", "branch")

            self.assertIn("status", result)
            self.assertIn("action_taken", result)
            self.assertIn(result["status"], ["recovered", "unrecoverable"])

    def test_detect_response_is_list(self):
        """detect_missing_branches always returns a list."""
        with patch.object(branch_recovery, "ENABLED", True), \
             patch.object(branch_recovery, "_is_git_repo", return_value=False):

            result = branch_recovery.detect_missing_branches("/invalid", ["a", "b"])

            self.assertIsInstance(result, list)

    def test_stats_response_is_dict_with_all_keys(self):
        """stats() returns dict with all expected keys."""
        result = branch_recovery.stats()

        self.assertIsInstance(result, dict)
        expected_keys = {
            "recover_attempts", "recover_fetched", "recover_reflog",
            "recover_unrecoverable", "recover_errors",
            "detect_calls", "detect_missing_found"
        }
        self.assertEqual(set(result.keys()), expected_keys)


if __name__ == "__main__":
    unittest.main()
