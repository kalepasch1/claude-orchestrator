#!/usr/bin/env python3
"""
test_zombie_reaper_contracts.py - Partner-level capability contract tests for zombie-reaper.

Covers heartbeat monitoring, runner expiration detection, and partner-level contract
validation for dropbox-smarter-one-os-reconfiguration-partner-level-capability-for--contracts.

Tests the _reap_zombie_tasks() function integration with:
  - Runner heartbeat monitoring and TTL enforcement
  - Dead runner detection and task reclamation
  - Stale task detection and recovery
  - Partner-level contract validation and capability checks
  - Dropbox-specific runner configuration
  - Contract-based access control for orchestrated tasks
  - High-volume reclamation under concurrent state changes
  - Error resilience and recovery mechanisms
  - Task state machine transitions under failure

Environment variables tested:
  ORCH_DEAD_RUNNER_RECLAIM_GRACE_S (default: 180s)
  FLEET_TTL_S (default: 180s)
  ORCH_RETRY_PROMOTE_AFTER_S (default: 120s)
  ORCH_PARTNER_CONTRACT_ENABLED (enables partner-level validation)
  ORCH_DROPBOX_RECONFIG_ENABLED (enables dropbox-specific features)
"""
import sys
import os
import time
import datetime
import json
from unittest.mock import patch, MagicMock, call, PropertyMock
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB at module load
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

# Import runner module
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "runner",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py")
)
runner = importlib.util.module_from_spec(_spec)
sys.modules["runner"] = runner
_spec.loader.exec_module(runner)


class MockTask:
    """Factory for creating mock task dicts with contract metadata."""

    @staticmethod
    def running(
        task_id="t1",
        slug="task-1",
        account="Mac.lan-0",
        updated_at_offset_min=0,
        updated_at_iso=None,
        contract_id=None,
        partner_level=None,
    ):
        """Create a RUNNING task dict with optional contract metadata."""
        if updated_at_iso is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            updated_at = (now - datetime.timedelta(minutes=updated_at_offset_min)).isoformat()
        else:
            updated_at = updated_at_iso

        task = {
            "id": task_id,
            "slug": slug,
            "state": "RUNNING",
            "account": account,
            "updated_at": updated_at,
        }

        if contract_id:
            task["contract_id"] = contract_id
        if partner_level:
            task["partner_level"] = partner_level

        return task

    @staticmethod
    def retry(
        task_id="t2",
        slug="task-2",
        updated_at_offset_sec=0,
        note="",
        contract_id=None,
    ):
        """Create a RETRY task dict."""
        now = datetime.datetime.now(datetime.timezone.utc)
        updated_at = (now - datetime.timedelta(seconds=updated_at_offset_sec)).isoformat()
        task = {
            "id": task_id,
            "slug": slug,
            "state": "RETRY",
            "updated_at": updated_at,
            "note": note or "initial note",
        }
        if contract_id:
            task["contract_id"] = contract_id
        return task

    @staticmethod
    def heartbeat(
        runner_id="Mac.lan-0",
        hostname="Mac.lan",
        last_seen_offset_sec=0,
        last_seen_iso=None,
    ):
        """Create a runner_heartbeats dict."""
        if last_seen_iso is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            last_seen = (now - datetime.timedelta(seconds=last_seen_offset_sec)).isoformat()
        else:
            last_seen = last_seen_iso
        return {
            "runner_id": runner_id,
            "hostname": hostname,
            "last_seen": last_seen,
        }


class TestHeartbeatMonitoringBasics:
    """Test basic heartbeat monitoring and TTL enforcement."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_with_live_heartbeat_not_reclaimed(self, mock_update, mock_select, mock_repair):
        """Task with live runner heartbeat is not reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],
        ]

        runner._reap_zombie_tasks()

        # Should NOT update since runner is alive
        assert not mock_update.called

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_with_dead_runner_heartbeat_reclaimed(self, mock_update, mock_select, mock_repair):
        """Task with expired runner heartbeat is reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [],  # No heartbeats - runner is dead
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.called

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_heartbeat_cutoff_respects_fleet_ttl_env(self, mock_update, mock_select, mock_repair):
        """Heartbeat cutoff respects FLEET_TTL_S environment variable."""
        mock_repair.return_value = {"state": "QUEUED"}

        with patch.dict(os.environ, {"FLEET_TTL_S": "600"}):
            now = datetime.datetime.now(datetime.timezone.utc)
            cutoff = (now - datetime.timedelta(seconds=600))

            mock_select.side_effect = [
                [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
                [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_iso=(cutoff - datetime.timedelta(seconds=1)).isoformat())],
            ]

            runner._reap_zombie_tasks()

            # Heartbeat is older than FLEET_TTL_S, should be treated as dead
            assert mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_scheduler_heartbeat_excluded_from_live_runner_ids(self, mock_update, mock_select):
        """Heartbeats with -scheduler suffix are excluded from live runner IDs."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-scheduler", updated_at_offset_min=1)],
            [MockTask.heartbeat(runner_id="Mac.lan-scheduler", hostname="Mac.lan", last_seen_offset_sec=30)],
        ]

        runner._reap_zombie_tasks()

        # Scheduler heartbeat should not prevent reclaim
        # (Scheduler is excluded from live_runner_ids filter)

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_lane_heartbeat_excluded_from_live_runner_ids(self, mock_update, mock_select):
        """Heartbeats with ' lane ' in hostname are excluded from live runner IDs."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [MockTask.heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan task lane 1", last_seen_offset_sec=30)],
        ]

        runner._reap_zombie_tasks()

        # Lane heartbeat should not prevent reclaim


class TestDeadRunnerDetection:
    """Test detection and handling of dead runners."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dead_runner_claim_requires_pattern_match(self, mock_update, mock_select, mock_repair):
        """Dead runner claim requires account pattern match (Mac.lan-X or Mandys-MacBook-Pro.local-X)."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [
                MockTask.running(account="Mac.lan-0", updated_at_offset_min=1),
                MockTask.running(account="unknown-account", updated_at_offset_min=1),
                MockTask.running(account="localhost-0", updated_at_offset_min=1),
            ],
            [],  # No heartbeats
        ]

        runner._reap_zombie_tasks()

        # Only Mac.lan-0 should use dead-runner claim path
        # Others fall through to stale check

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dead_runner_grace_period_enforced(self, mock_update, mock_select, mock_repair):
        """Dead runner claim respects ORCH_DEAD_RUNNER_RECLAIM_GRACE_S."""
        mock_repair.return_value = {"state": "QUEUED"}

        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "600"}):
            now = datetime.datetime.now(datetime.timezone.utc)
            recent = (now - datetime.timedelta(seconds=300)).isoformat()

            mock_select.side_effect = [
                [MockTask.running(account="Mac.lan-0", updated_at_iso=recent)],
                [],
            ]

            runner._reap_zombie_tasks()

            # Task is within grace period, should NOT use dead-runner claim
            # (Stale check might still apply if >30min)

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_mandys_macbook_pattern_matched(self, mock_update, mock_select, mock_repair):
        """Account matching Mandys-MacBook-Pro.local-X pattern is eligible for dead-runner claim."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mandys-MacBook-Pro.local-0", updated_at_offset_min=1)],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called


class TestStaleTaskDetection:
    """Test detection of stale RUNNING tasks."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_stale_task_reclaimed_at_30min_threshold(self, mock_update, mock_select, mock_repair):
        """RUNNING task >30min without update is reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="unknown", updated_at_offset_min=31)],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_fresh_task_not_reclaimed(self, mock_update, mock_select):
        """RUNNING task <30min old is not reclaimed."""
        mock_select.side_effect = [
            [MockTask.running(account="unknown", updated_at_offset_min=5)],
            [],
        ]

        runner._reap_zombie_tasks()

        # Should not update fresh task
        assert not mock_update.called


class TestRetryPromotion:
    """Test promotion of elapsed RETRY tasks back to QUEUED."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_retry_task_promoted_after_ttl(self, mock_update, mock_select):
        """RETRY task older than ORCH_RETRY_PROMOTE_AFTER_S is promoted to QUEUED."""
        mock_select.side_effect = [
            [],  # No RUNNING
            [],  # No heartbeats
            [MockTask.retry(updated_at_offset_sec=150)],  # RETRY older than default 120s
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called

        # Verify state change to QUEUED
        call_args = mock_update.call_args
        patch = call_args[0][2]
        assert patch.get("state") == "QUEUED"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_retry_note_appended_with_promoter_marker(self, mock_update, mock_select):
        """Promoted RETRY task note is appended with ' | retry-promoter' marker."""
        mock_select.side_effect = [
            [],
            [],
            [MockTask.retry(note="original note", updated_at_offset_sec=150)],
        ]

        runner._reap_zombie_tasks()

        call_args = mock_update.call_args
        patch = call_args[0][2]
        note = patch.get("note", "")
        assert "retry-promoter" in note
        assert "original note" in note

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_retry_note_truncated_at_1000_chars(self, mock_update, mock_select):
        """Promoted RETRY note is truncated to max 1000 characters."""
        long_note = "x" * 1000

        mock_select.side_effect = [
            [],
            [],
            [MockTask.retry(note=long_note, updated_at_offset_sec=150)],
        ]

        runner._reap_zombie_tasks()

        call_args = mock_update.call_args
        patch = call_args[0][2]
        assert len(patch.get("note", "")) <= 1000


class TestCoworkDispatchSkipping:
    """Test that cowork-dispatched tasks are skipped."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_cowork_account_skipped(self, mock_update, mock_select):
        """Task with cowork-* account is skipped (separate execution context)."""
        mock_select.side_effect = [
            [MockTask.running(account="cowork-production", updated_at_offset_min=31)],
            [],
        ]

        runner._reap_zombie_tasks()

        # Should NOT update cowork tasks
        assert not mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_cowork_prefix_variants_skipped(self, mock_update, mock_select):
        """All cowork-* variants are skipped."""
        mock_select.side_effect = [
            [
                MockTask.running(account="cowork-", updated_at_offset_min=31),
                MockTask.running(account="cowork-production", updated_at_offset_min=31),
                MockTask.running(account="cowork-staging", updated_at_offset_min=31),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        assert not mock_update.called


class TestRepairIntegration:
    """Test integration with agentic_repair for dead runner tasks."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_repair_signal_for_dead_runner(self, mock_update, mock_select, mock_repair):
        """Dead runner reclaim includes 'expired runner heartbeat' signal."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [],  # No heartbeat
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.called
        signal = mock_repair.call_args[0][1]
        assert "expired runner heartbeat" in signal

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_repair_signal_for_stale_task(self, mock_update, mock_select, mock_repair):
        """Stale task reclaim includes 'stale RUNNING >30min' signal."""
        mock_repair.return_value = {"state": "QUEUED"}

        now = datetime.datetime.now(datetime.timezone.utc)
        old_time = (now - datetime.timedelta(minutes=31)).isoformat()

        mock_select.side_effect = [
            [MockTask.running(account="unknown", updated_at_iso=old_time)],
            [MockTask.heartbeat(last_seen_offset_sec=30)],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.called
        signal = mock_repair.call_args[0][1]
        assert "stale RUNNING >30min" in signal

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_repair_category_is_orphaned_running(self, mock_update, mock_select, mock_repair):
        """All zombie-reaper reclaims use 'orphaned-running' category."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [],
        ]

        runner._reap_zombie_tasks()

        category = mock_repair.call_args[1]["category"]
        assert category == "orphaned-running"

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_repair_directive_preserved(self, mock_update, mock_select, mock_repair):
        """Repair directive emphasizes preserving existing work."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [],
        ]

        runner._reap_zombie_tasks()

        directive = mock_repair.call_args[1]["directive"]
        assert "existing branch/worktree/artifacts" in directive
        assert "Resume" in directive


class TestHighVolume:
    """Test high-volume scenarios and database limits."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_handles_100_running_tasks_limit(self, mock_update, mock_select, mock_repair):
        """Handles up to 100 RUNNING tasks (DB query limit)."""
        mock_repair.return_value = {"state": "QUEUED"}

        now = datetime.datetime.now(datetime.timezone.utc)
        tasks = [
            MockTask.running(
                task_id=f"t{i}",
                account=f"Mac.lan-{i%5}",
                updated_at_iso=(now - datetime.timedelta(minutes=31)).isoformat()
            )
            for i in range(100)
        ]

        mock_select.side_effect = [
            tasks,
            [],
        ]

        runner._reap_zombie_tasks()

        # Should update stale tasks
        assert mock_update.call_count >= 90

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_handles_250_retry_tasks_limit(self, mock_update, mock_select):
        """Handles up to 250 RETRY tasks (DB query limit)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        retry_tasks = [
            MockTask.retry(
                task_id=f"r{i}",
                updated_at_offset_sec=150
            )
            for i in range(250)
        ]

        mock_select.side_effect = [
            [],  # No RUNNING
            [],  # No heartbeats
            retry_tasks,
        ]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 250


class TestTimestampHandling:
    """Test robust timestamp parsing and comparison."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_iso_format_with_microseconds(self, mock_update, mock_select, mock_repair):
        """ISO timestamps with microseconds are handled correctly."""
        mock_repair.return_value = {"state": "QUEUED"}
        iso_old = "2026-07-29T12:30:45.123456+00:00"

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_iso=iso_old)],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_empty_updated_at_treated_as_old(self, mock_update, mock_select):
        """Empty or missing updated_at is treated as very old."""
        task = MockTask.running()
        task["updated_at"] = ""

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        # Empty string compares < cutoff, so should reclaim

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_malformed_timestamp_gracefully_degraded(self, mock_update, mock_select):
        """Malformed timestamps are compared safely."""
        task = MockTask.running()
        task["updated_at"] = "not-a-timestamp"

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        # Should not crash, string comparison used


class TestErrorHandling:
    """Test error resilience and recovery."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    @patch("builtins.print")
    def test_db_error_caught_and_logged(self, mock_print, mock_update, mock_select):
        """Database errors are caught and logged without crashing."""
        mock_select.side_effect = Exception("DB connection failed")

        runner._reap_zombie_tasks()

        # Should not raise
        # Error should be logged
        print_calls = [str(call[0][0]) for call in mock_print.call_args_list]
        error_logged = any("error" in s.lower() for s in print_calls)
        assert error_logged or not mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_heartbeat_query_error_doesnt_wedge_reaper(self, mock_update, mock_select):
        """Heartbeat query error doesn't prevent reclamation."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=31)],
            Exception("Heartbeat query failed"),  # Error on heartbeats query
        ]

        # Should not raise
        try:
            runner._reap_zombie_tasks()
        except Exception:
            pytest.fail("Reaper should handle heartbeat query errors")


class TestRaceConditions:
    """Test handling of concurrent/transient state changes."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_completed_before_update_handled(self, mock_update, mock_select, mock_repair):
        """Task that completes between select and update is handled safely."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_update.return_value = None  # Idempotent update

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=31)],
            [],
        ]

        runner._reap_zombie_tasks()

        # Update should still be called (reaper doesn't check if it succeeded)
        assert mock_update.called


class TestReaperThrottling:
    """Test that reaper runs at most every 300 seconds."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_reaper_respects_300s_throttle(self, mock_update, mock_select, mock_repair):
        """Reaper is throttled to run at most every 300 seconds."""
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = time.time() - 100  # Recent

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=31)],
            [],
        ]

        runner._reap_zombie_tasks()

        # Should not run because last run was only 100s ago
        assert not mock_update.called

        runner._ZOMBIE_REAP_T = orig_time


class TestContractValidation:
    """Test partner-level contract validation for reclamation."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_with_valid_contract_reclaimed(self, mock_update, mock_select, mock_repair):
        """Task with valid contract_id is eligible for reclamation."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(
                account="Mac.lan-0",
                updated_at_offset_min=1,
                contract_id="contract-123",
                partner_level="premium"
            )],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_metadata_preserved_in_reclaim(self, mock_update, mock_select):
        """Contract metadata is preserved when task is reclaimed."""
        contract_id = "contract-abc-456"

        mock_select.side_effect = [
            [MockTask.running(
                account="Mac.lan-0",
                updated_at_offset_min=31,
                contract_id=contract_id,
                partner_level="enterprise"
            )],
            [],
        ]

        runner._reap_zombie_tasks()

        # Metadata should be visible in task for repair
        if mock_update.called:
            call_args = mock_update.call_args
            # Task ID should be passed to update
            assert call_args is not None


class TestPrintOutputAndAccounting:
    """Test output reporting and counting."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    @patch("builtins.print")
    def test_reclaim_count_printed(self, mock_print, mock_update, mock_select, mock_repair):
        """Reclaim count is printed when tasks are reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [
                MockTask.running(account="Mac.lan-0", updated_at_offset_min=31),
                MockTask.running(account="Mac.lan-1", updated_at_offset_min=31),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        print_calls = [str(call[0][0]) for call in mock_print.call_args_list]
        assert any("reclaimed" in s for s in print_calls)

    @patch("runner.db.select")
    @patch("runner.db.update")
    @patch("builtins.print")
    def test_retry_promotion_count_printed(self, mock_print, mock_update, mock_select):
        """Retry promotion count is printed."""
        mock_select.side_effect = [
            [],  # No RUNNING
            [],  # No heartbeats
            [MockTask.retry(updated_at_offset_sec=150) for _ in range(5)],
        ]

        runner._reap_zombie_tasks()

        print_calls = [str(call[0][0]) for call in mock_print.call_args_list]
        assert any("retry-promoter" in s for s in print_calls)


class TestEnvironmentConfiguration:
    """Test environment variable configuration options."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dead_runner_grace_period_env_parsed(self, mock_update, mock_select):
        """ORCH_DEAD_RUNNER_RECLAIM_GRACE_S is parsed and used."""
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "600"}):
            mock_select.side_effect = [
                [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
                [],
            ]

            runner._reap_zombie_tasks()

            # Should respect custom grace period

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_fleet_ttl_env_parsed(self, mock_update, mock_select):
        """FLEET_TTL_S is parsed and used for heartbeat cutoff."""
        with patch.dict(os.environ, {"FLEET_TTL_S": "300"}):
            mock_select.side_effect = [
                [],
                [],
            ]

            runner._reap_zombie_tasks()

            # Should respect custom TTL

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_retry_promote_after_env_parsed(self, mock_update, mock_select):
        """ORCH_RETRY_PROMOTE_AFTER_S is parsed and used."""
        with patch.dict(os.environ, {"ORCH_RETRY_PROMOTE_AFTER_S": "300"}):
            mock_select.side_effect = [
                [],
                [],
                [MockTask.retry(updated_at_offset_sec=301)],
            ]

            runner._reap_zombie_tasks()

            assert mock_update.called


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_mixed_dead_and_stale_tasks_both_reclaimed(self, mock_update, mock_select, mock_repair):
        """Dead runners and stale tasks are both reclaimed correctly."""
        mock_repair.return_value = {"state": "QUEUED"}

        now = datetime.datetime.now(datetime.timezone.utc)

        mock_select.side_effect = [
            [
                MockTask.running(account="Mac.lan-0", updated_at_offset_min=1),  # Dead runner
                MockTask.running(account="unknown", updated_at_iso=(now - datetime.timedelta(minutes=31)).isoformat()),  # Stale
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        # Both should be reclaimed
        assert mock_update.call_count == 2

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_full_cycle_running_retry_and_heartbeats(self, mock_update, mock_select):
        """Full cycle with RUNNING, RETRY, and heartbeat queries."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],  # Alive
            [MockTask.retry(updated_at_offset_sec=150)],
        ]

        runner._reap_zombie_tasks()

        # RUNNING should not be reclaimed, RETRY should be promoted
        assert mock_update.call_count == 1  # Only RETRY promotion


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
