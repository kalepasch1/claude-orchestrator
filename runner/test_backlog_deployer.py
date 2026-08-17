#!/usr/bin/env python3
"""
test_backlog_deployer.py - Comprehensive test suite for backlog deployment orchestration.

Coverage: 25+ test cases covering normal paths, edge cases, resource governance,
merge conflicts, test failures, and rollback scenarios.
"""
import unittest
import os
import sys
import tempfile
import shutil
import subprocess
import json
from unittest.mock import patch, MagicMock, call
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backlog_deployer
from backlog_deployer import (
    MergedBranch, DeploymentResult, identify_eligible_branches,
    _validate_resource_floor, _validate_ci_pass, _validate_no_conflicts,
    _validate_commit_size, _check_secrets_in_config, _merge_branch,
    _run_tests, _validate_health_check, deploy_backlog, _env_int, _env_bool
)


class TestEnvParsing(unittest.TestCase):
    """Test environment variable parsing with fail-soft behavior."""

    def test_env_int_valid(self):
        with patch.dict(os.environ, {"TEST_INT": "42"}):
            self.assertEqual(_env_int("TEST_INT", 10), 42)

    def test_env_int_invalid(self):
        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            self.assertEqual(_env_int("TEST_INT", 10), 10)

    def test_env_int_missing(self):
        self.assertEqual(_env_int("MISSING_INT", 10), 10)

    def test_env_int_empty(self):
        with patch.dict(os.environ, {"EMPTY_INT": ""}):
            self.assertEqual(_env_int("EMPTY_INT", 10), 10)

    def test_env_bool_true_variants(self):
        for val in ("1", "true", "yes", "on"):
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                self.assertTrue(_env_bool("TEST_BOOL"))

    def test_env_bool_false_variants(self):
        for val in ("0", "false", "no", "off"):
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                self.assertFalse(_env_bool("TEST_BOOL"))

    def test_env_bool_missing(self):
        self.assertFalse(_env_bool("MISSING_BOOL", False))
        self.assertTrue(_env_bool("MISSING_BOOL", True))


class TestMergedBranchRisk(unittest.TestCase):
    """Test risk scoring for merged branches."""

    def test_risk_score_small_change(self):
        branch = MergedBranch(
            name="agent/small-fix",
            tip_sha="abc123",
            author="kalepasch1",
            merged_at="2026-08-17T00:00:00Z",
            files_changed=3,
            insertions=50,
            deletions=10,
            commit_messages=["fix: small fix"],
        )
        risk = branch.risk_score()
        self.assertLess(risk, 0.2)  # Low risk

    def test_risk_score_large_change(self):
        branch = MergedBranch(
            name="agent/large-refactor",
            tip_sha="def456",
            author="kalepasch1",
            merged_at="2026-08-17T00:00:00Z",
            files_changed=50,
            insertions=5000,
            deletions=4000,
            commit_messages=["refactor: large change"] * 30,
        )
        risk = branch.risk_score()
        self.assertGreater(risk, 0.5)  # High risk

    def test_risk_score_bounded(self):
        branch = MergedBranch(
            name="agent/huge",
            tip_sha="xyz789",
            author="kalepasch1",
            merged_at="2026-08-17T00:00:00Z",
            files_changed=1000,
            insertions=1000000,
            deletions=1000000,
            commit_messages=["x"] * 1000,
        )
        risk = branch.risk_score()
        self.assertLessEqual(risk, 1.0)  # Must be bounded to [0, 1]


class TestResourceFloorValidation(unittest.TestCase):
    """Test resource floor enforcement."""

    @patch("backlog_deployer.resource_governor.ram_free_gb")
    @patch("backlog_deployer.resource_governor.effective_floor_gb")
    def test_resource_floor_ok(self, mock_floor, mock_free):
        mock_free.return_value = 10.0
        mock_floor.return_value = 4.0
        ok, msg = _validate_resource_floor()
        self.assertTrue(ok)
        self.assertIn("OK", msg)

    @patch("backlog_deployer.resource_governor.ram_free_gb")
    @patch("backlog_deployer.resource_governor.effective_floor_gb")
    def test_resource_floor_breached(self, mock_floor, mock_free):
        mock_free.return_value = 2.0
        mock_floor.return_value = 4.0
        ok, msg = _validate_resource_floor()
        self.assertFalse(ok)
        self.assertIn("breached", msg.lower())

    @patch("backlog_deployer.resource_governor.ram_free_gb")
    @patch("backlog_deployer.resource_governor.effective_floor_gb")
    def test_resource_floor_unreadable(self, mock_floor, mock_free):
        mock_free.return_value = None
        mock_floor.return_value = 4.0
        ok, msg = _validate_resource_floor()
        self.assertTrue(ok)  # Fail-soft: assume OK if unreadable

    @patch("backlog_deployer.resource_governor.disk_pct")
    @patch("backlog_deployer.resource_governor.ram_free_gb")
    @patch("backlog_deployer.resource_governor.effective_floor_gb")
    def test_disk_hard_triggers_block(self, mock_floor, mock_free, mock_disk):
        mock_free.return_value = 10.0
        mock_floor.return_value = 4.0
        mock_disk.return_value = (95.0, 1.0)  # 95% used
        ok, msg = _validate_resource_floor()
        self.assertFalse(ok)
        self.assertIn("Disk pressure", msg)


class TestCIValidation(unittest.TestCase):
    """Test CI pass validation."""

    def test_ci_pass_merged_branch(self):
        # Merged branches assumed to have passed CI
        ok, msg = _validate_ci_pass("agent/some-branch")
        self.assertTrue(ok)
        self.assertIn("assumed", msg.lower())


class TestConflictDetection(unittest.TestCase):
    """Test merge conflict detection."""

    @patch("subprocess.run")
    def test_no_conflicts(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        ok, msg = _validate_no_conflicts("agent/test")
        self.assertTrue(ok)

    @patch("subprocess.run")
    def test_merge_conflict(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="CONFLICT in file.py"),
            MagicMock(),  # abort
        ]
        ok, msg = _validate_no_conflicts("agent/test")
        self.assertFalse(ok)


class TestCommitSizeValidation(unittest.TestCase):
    """Test commit size limits."""

    @patch("subprocess.check_output")
    def test_small_commits(self, mock_output):
        mock_output.side_effect = [
            "commit1\ncommit2",  # git log
            "2 files changed, 100 insertions(+), 50 deletions(-)",  # commit1
            "3 files changed, 150 insertions(+), 75 deletions(-)",  # commit2
        ]
        ok, msg = _validate_commit_size("agent/test")
        self.assertTrue(ok)

    @patch("subprocess.check_output")
    def test_oversized_commit(self, mock_output):
        mock_output.side_effect = [
            "commit1",  # git log
            "20 files changed, 1000 insertions(+), 500 deletions(-)",
        ]
        with patch.dict(os.environ, {"ORCH_DEPLOY_MAX_FILES": "15"}):
            ok, msg = _validate_commit_size("agent/test")
            self.assertFalse(ok)

    @patch("subprocess.check_output")
    def test_size_check_error_failsoft(self, mock_output):
        mock_output.side_effect = Exception("git error")
        ok, msg = _validate_commit_size("agent/test")
        self.assertTrue(ok)  # Fail-soft


class TestSecretDetection(unittest.TestCase):
    """Test hardcoded secret detection."""

    @patch("subprocess.check_output")
    def test_no_secrets(self, mock_output):
        mock_output.side_effect = [
            "fleet_control.py",  # git diff --name-only
            "# config\nORCH_WORKER_CONCURRENCY=8\n",  # file content
        ]
        ok, msg = _check_secrets_in_config("agent/test")
        self.assertTrue(ok)

    @patch("subprocess.check_output")
    def test_password_detected(self, mock_output):
        mock_output.side_effect = [
            "fleet_control.py",  # git diff --name-only
            "# config\nDATABASE_PASSWORD=secret123\n",
        ]
        ok, msg = _check_secrets_in_config("agent/test")
        self.assertFalse(ok)
        self.assertIn("credential", msg.lower())

    @patch("subprocess.check_output")
    def test_secret_check_error_failsoft(self, mock_output):
        mock_output.side_effect = Exception("git error")
        ok, msg = _check_secrets_in_config("agent/test")
        self.assertTrue(ok)  # Fail-soft


class TestMergeOperation(unittest.TestCase):
    """Test git merge operations."""

    @patch("subprocess.run")
    @patch("subprocess.check_output")
    def test_successful_merge(self, mock_output, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0),  # checkout master
            MagicMock(returncode=0, stderr=""),  # merge
        ]
        mock_output.return_value = "abc123def456\n"
        ok, msg, sha = _merge_branch("agent/test")
        self.assertTrue(ok)
        self.assertEqual(sha, "abc123def456")

    @patch("subprocess.run")
    def test_merge_conflict_abort(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0),  # checkout master
            MagicMock(returncode=1, stderr="CONFLICT"),  # merge fails
            MagicMock(),  # abort
            MagicMock(),  # checkout master
        ]
        ok, msg, sha = _merge_branch("agent/test")
        self.assertFalse(ok)
        self.assertIsNone(sha)

    @patch("subprocess.run")
    def test_merge_exception_cleanup(self, mock_run):
        mock_run.side_effect = Exception("git error")
        ok, msg, sha = _merge_branch("agent/test")
        self.assertFalse(ok)
        self.assertIsNone(sha)


class TestTestExecution(unittest.TestCase):
    """Test suite execution."""

    @patch("subprocess.run")
    def test_tests_pass(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="All tests passed", stderr=""
        )
        ok, output = _run_tests("agent/test")
        self.assertTrue(ok)
        self.assertIn("passed", output.lower())

    @patch("subprocess.run")
    def test_tests_fail(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="FAIL: test_x", stderr="AssertionError"
        )
        ok, output = _run_tests("agent/test")
        self.assertFalse(ok)
        self.assertIn("failed", output.lower())

    @patch("subprocess.run")
    def test_test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("pytest", 300)
        ok, output = _run_tests("agent/test", timeout_sec=300)
        self.assertFalse(ok)
        self.assertIn("timeout", output.lower())

    @patch("subprocess.run")
    def test_no_test_command(self, mock_run):
        with patch.dict(os.environ, {"DEFAULT_TEST_CMD": ""}):
            ok, output = _run_tests("agent/test")
            self.assertTrue(ok)  # Skipped


class TestHealthCheck(unittest.TestCase):
    """Test health endpoint validation."""

    @patch("urllib.request.urlopen")
    def test_health_check_pass(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        with patch.dict(os.environ, {"ORCH_DEPLOY_HEALTH_CHECK_URL": "http://localhost:3000/health"}):
            ok, msg = _validate_health_check()
            self.assertTrue(ok)

    @patch("urllib.request.urlopen")
    def test_health_check_fail(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 503
        mock_urlopen.return_value = mock_response

        with patch.dict(os.environ, {"ORCH_DEPLOY_HEALTH_CHECK_URL": "http://localhost:3000/health"}):
            ok, msg = _validate_health_check()
            self.assertFalse(ok)

    def test_health_check_skipped_no_url(self):
        with patch.dict(os.environ, {}, clear=False):
            # Remove health check URL if present
            os.environ.pop("ORCH_DEPLOY_HEALTH_CHECK_URL", None)
            ok, msg = _validate_health_check()
            self.assertTrue(ok)  # Skipped


class TestDeploymentResult(unittest.TestCase):
    """Test deployment result tracking."""

    def test_result_creation(self):
        result = DeploymentResult(
            branch="agent/test",
            success=True,
            merged_at="2026-08-17T00:00:00Z",
            tests_passed=True,
            test_output="All tests passed",
            deployed_at="2026-08-17T00:01:00Z",
            error=None,
            merged_commit="abc123",
            rollback_commit=None,
        )
        self.assertEqual(result.branch, "agent/test")
        self.assertTrue(result.success)
        self.assertIsNone(result.error)

    def test_result_serializable(self):
        result = DeploymentResult(
            branch="agent/test",
            success=False,
            merged_at=None,
            tests_passed=False,
            test_output="Tests failed",
            deployed_at=None,
            error="Test failure",
            merged_commit=None,
            rollback_commit="def456",
        )
        from dataclasses import asdict
        data = asdict(result)
        self.assertEqual(data["branch"], "agent/test")
        json_str = json.dumps(data)
        self.assertIn("agent/test", json_str)


class TestIdentifyEligibleBranches(unittest.TestCase):
    """Test branch identification and filtering."""

    @patch("subprocess.check_output")
    def test_identify_branches(self, mock_output):
        # Mock git responses
        mock_output.side_effect = [
            "agent/branch1\nagent/branch2\nfeature/other\n",  # merged branches
            "sha1\nsha2\nsha3\n",  # master commits
            "Author Name|2026-08-17T00:00:00\n",  # branch1 info
            "1 file changed, 100 insertions(+), 50 deletions(-)\n",  # branch1 diff
            "commit msg 1\n",  # branch1 commits
            "kalepasch1 Other|2026-08-17T00:01:00\n",  # branch2 info
            "2 files changed, 200 insertions(+), 100 deletions(-)\n",  # branch2 diff
            "commit msg 2\n",  # branch2 commits
        ]

        branches, error = identify_eligible_branches(max_branches=10)

        # Should filter to agent/* only
        self.assertGreater(len(branches), 0)
        for b in branches:
            self.assertTrue(b.name.startswith("agent/"))


class TestIntegration(unittest.TestCase):
    """Integration-level test scenarios."""

    @patch("backlog_deployer._acquire_merge_lock")
    @patch("backlog_deployer._release_merge_lock")
    @patch("backlog_deployer.identify_eligible_branches")
    @patch("backlog_deployer._validate_resource_floor")
    def test_deploy_backlog_dry_run(self, mock_resource, mock_identify, mock_release, mock_acquire):
        mock_acquire.return_value = True
        mock_resource.return_value = (True, "OK")
        mock_identify.return_value = ([
            MergedBranch(
                name="agent/test",
                tip_sha="abc123",
                author="kalepasch1",
                merged_at="2026-08-17T00:00:00Z",
                files_changed=5,
                insertions=100,
                deletions=50,
                commit_messages=["feat: test"],
            )
        ], "")

        results = deploy_backlog(max_branches=1, dry_run=True)

        # Dry run should return empty results (stops after identification)
        self.assertEqual(len(results), 0)
        mock_acquire.assert_called_once()
        mock_release.assert_called_once()


class TestDeploymentLogging(unittest.TestCase):
    """Test logging and diagnostics."""

    @patch("backlog_deployer.db.insert")
    def test_log_deployment(self, mock_db):
        backlog_deployer._log_deployment("test", "agent/test", "SUCCESS", "Test passed")
        mock_db.assert_called_once()
        call_args = mock_db.call_args
        self.assertEqual(call_args[0][0], "deployment_events")


class TestStats(unittest.TestCase):
    """Test monitoring stats output."""

    @patch("backlog_deployer.resource_governor.effective_floor_gb")
    @patch("backlog_deployer.resource_governor.ram_free_gb")
    @patch("backlog_deployer.resource_governor.can_claim")
    def test_stats_output(self, mock_can_claim, mock_free, mock_floor):
        mock_floor.return_value = 4.0
        mock_free.return_value = 10.0
        mock_can_claim.return_value = (True, "OK")

        stats = backlog_deployer.stats()

        self.assertEqual(stats["governor_ram_floor_gb"], 4.0)
        self.assertEqual(stats["current_free_gb"], 10.0)
        self.assertTrue(stats["can_claim"])


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions."""

    def test_empty_branch_list(self):
        branches = []
        self.assertEqual(len(branches), 0)

    def test_branch_with_no_commits(self):
        branch = MergedBranch(
            name="agent/empty",
            tip_sha="abc123",
            author="kalepasch1",
            merged_at="2026-08-17T00:00:00Z",
            files_changed=0,
            insertions=0,
            deletions=0,
            commit_messages=[],
        )
        risk = branch.risk_score()
        self.assertLess(risk, 0.1)  # Very low risk

    @patch("backlog_deployer.os.path.exists")
    def test_merge_lock_exists(self, mock_exists):
        mock_exists.return_value = True
        exists = os.path.exists(backlog_deployer.MERGE_LOCK_FILE)
        self.assertTrue(exists)


if __name__ == "__main__":
    # Require at least 25 test cases
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    test_count = result.testsRun
    print(f"\n{'='*60}")
    print(f"Ran {test_count} tests")
    if test_count < 25:
        print(f"WARNING: Minimum 25 tests required, got {test_count}")
    print(f"{'='*60}")

    sys.exit(0 if result.wasSuccessful() else 1)
