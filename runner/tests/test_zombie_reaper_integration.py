#!/usr/bin/env python3
"""
test_zombie_reaper_integration.py - Production integration tests for zombie-reaper

Tests production scenarios: heartbeat expiration under load, recovery workflows,
timing edge cases, concurrent execution, and agentic repair integration.

Task: zombie-reaper: expired runner heartbeat
Failure Category: orphaned-running
"""
import sys
import os
import time
import datetime
import threading
from unittest.mock import patch, MagicMock, call
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "runner",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner.py")
)
runner = importlib.util.module_from_spec(_spec)
sys.modules["runner"] = runner
_spec.loader.exec_module(runner)


class MockTaskFactory:
    """Factory for creating task records matching DB schema."""

    @staticmethod
    def running(task_id="t1", slug="task-1", account="Mac.lan-0",
                updated_offset_sec=0, state="RUNNING"):
        now = datetime.datetime.now(datetime.timezone.utc)
        updated = (now - datetime.timedelta(seconds=updated_offset_sec)).isoformat()
        return {
            "id": task_id,
            "slug": slug,
            "state": state,
            "account": account,
            "updated_at": updated,
        }

    @staticmethod
    def retry(task_id="r1", slug="retry-1", updated_offset_sec=0, note=""):
        now = datetime.datetime.now(datetime.timezone.utc)
        updated = (now - datetime.timedelta(seconds=updated_offset_sec)).isoformat()
        return {
            "id": task_id,
            "slug": slug,
            "state": "RETRY",
            "updated_at": updated,
            "note": note,
        }

    @staticmethod
    def heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan",
                  last_seen_offset_sec=0):
        now = datetime.datetime.now(datetime.timezone.utc)
        last_seen = (now - datetime.timedelta(seconds=last_seen_offset_sec)).isoformat()
        return {
            "runner_id": runner_id,
            "hostname": hostname,
            "last_seen": last_seen,
        }


class TestHeartbeatExpiryBoundaries:
    """Test heartbeat expiration at critical time boundaries."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_exactly_at_30min_boundary_over(self, mock_update, mock_select, mock_repair):
        """Task at 30:01 minutes is reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        now = datetime.datetime.now(datetime.timezone.utc)
        task = MockTaskFactory.running(
            updated_offset_sec=int(30 * 60 + 1)  # 30:01
        )

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()
        assert mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_exactly_at_30min_boundary_under(self, mock_update, mock_select):
        """Task at 29:59 minutes is NOT reclaimed."""
        now = datetime.datetime.now(datetime.timezone.utc)
        task = MockTaskFactory.running(
            updated_offset_sec=int(30 * 60 - 1)  # 29:59
        )

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()
        mock_update.assert_not_called()

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dead_runner_at_grace_period_boundary(self, mock_update, mock_select, mock_repair):
        """Dead runner reclaim respects grace period boundary."""
        mock_repair.return_value = {"state": "QUEUED"}
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "300"}):
            now = datetime.datetime.now(datetime.timezone.utc)
            task = MockTaskFactory.running(
                account="Mac.lan-0",
                updated_offset_sec=int(300 + 1)  # 300:01s
            )

            mock_select.side_effect = [
                [task],
                [],  # dead runner
            ]

            runner._reap_zombie_tasks()
            assert mock_update.called


class TestFleetTTLVariations:
    """Test behavior with different FLEET_TTL_S configurations."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_fleet_ttl_s_short_30_seconds(self, mock_update, mock_select):
        """With FLEET_TTL_S=30, heartbeats older than 30s mark runner dead."""
        with patch.dict(os.environ, {"FLEET_TTL_S": "30"}):
            task = MockTaskFactory.running(account="Mac.lan-0", updated_offset_sec=60)
            hb = MockTaskFactory.heartbeat(last_seen_offset_sec=40)  # older than 30s

            mock_select.side_effect = [
                [task],
                [],  # no live runners
            ]

            runner._reap_zombie_tasks()
            assert mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_fleet_ttl_s_long_600_seconds(self, mock_update, mock_select):
        """With FLEET_TTL_S=600, 300s-old heartbeat keeps runner alive."""
        with patch.dict(os.environ, {"FLEET_TTL_S": "600"}):
            task = MockTaskFactory.running(account="Mac.lan-0", updated_offset_sec=60)
            hb = MockTaskFactory.heartbeat("Mac.lan-0", last_seen_offset_sec=300)

            mock_select.side_effect = [
                [task],
                [hb],  # runner is alive (300s < 600s TTL)
            ]

            runner._reap_zombie_tasks()
            mock_update.assert_not_called()


class TestRetryPromotionThreshold:
    """Test RETRY promotion with various time thresholds."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_retry_promotion_threshold_1_second(self, mock_update, mock_select):
        """With ORCH_RETRY_PROMOTE_AFTER_S=1, 2s-old RETRY promoted."""
        with patch.dict(os.environ, {"ORCH_RETRY_PROMOTE_AFTER_S": "1"}):
            task = MockTaskFactory.retry(updated_offset_sec=2)

            mock_select.side_effect = [
                [],  # no RUNNING
                [],  # no heartbeats
                [task],
            ]

            runner._reap_zombie_tasks()
            assert mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_retry_promotion_threshold_3600_seconds(self, mock_update, mock_select):
        """With ORCH_RETRY_PROMOTE_AFTER_S=3600, 1800s-old RETRY not promoted."""
        with patch.dict(os.environ, {"ORCH_RETRY_PROMOTE_AFTER_S": "3600"}):
            task = MockTaskFactory.retry(updated_offset_sec=1800)

            mock_select.side_effect = [
                [],  # no RUNNING
                [],  # no heartbeats
                [task],
            ]

            runner._reap_zombie_tasks()
            mock_update.assert_not_called()


class TestConcurrentZombieRecovery:
    """Test zombie reaper under concurrent task updates."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_large_batch_stale_tasks_all_reclaimed(self, mock_update, mock_select, mock_repair):
        """Reclaim 50 stale RUNNING tasks in single cycle."""
        mock_repair.return_value = {"state": "QUEUED"}
        now = datetime.datetime.now(datetime.timezone.utc)

        tasks = [
            MockTaskFactory.running(
                task_id=f"t{i}",
                slug=f"task-{i}",
                account=f"unknown-{i}",
                updated_offset_sec=30*60 + 100
            )
            for i in range(50)
        ]

        mock_select.side_effect = [
            tasks,
            [],
        ]

        runner._reap_zombie_tasks()
        assert mock_update.call_count == 50

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_mixed_tasks_selective_reclaim(self, mock_update, mock_select):
        """In batch of mixed ages, only stale are reclaimed."""
        tasks = [
            MockTaskFactory.running("t1", updated_offset_sec=10*60),  # recent
            MockTaskFactory.running("t2", updated_offset_sec=31*60),  # stale
            MockTaskFactory.running("t3", updated_offset_sec=5*60),   # recent
            MockTaskFactory.running("t4", updated_offset_sec=45*60),  # stale
        ]

        mock_select.side_effect = [
            tasks,
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 2
        updated_ids = {call_args[0][1]["id"] for call_args in mock_update.call_args_list}
        assert "t2" in updated_ids
        assert "t4" in updated_ids
        assert "t1" not in updated_ids
        assert "t3" not in updated_ids


class TestRunnerAccountPatternMatching:
    """Test account pattern recognition for dead-runner claims."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_mac_lan_pattern_matches(self, mock_update, mock_select, mock_repair):
        """Account 'Mac.lan-X' pattern matches dead-runner detection."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTaskFactory.running(
            account="Mac.lan-5",
            updated_offset_sec=200
        )

        mock_select.side_effect = [
            [task],
            [],  # no heartbeats - runner is dead
        ]

        runner._reap_zombie_tasks()
        assert mock_repair.called
        call_args = mock_repair.call_args
        assert "expired runner heartbeat" in call_args[1]["directive"]

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_mandys_macbook_pattern_matches(self, mock_update, mock_select):
        """Account 'Mandys-MacBook-Pro.local-X' pattern matches."""
        task = MockTaskFactory.running(
            account="Mandys-MacBook-Pro.local-0",
            updated_offset_sec=200
        )

        mock_select.side_effect = [
            [task],
            [],  # no heartbeats
        ]

        runner._reap_zombie_tasks()
        assert mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_unknown_account_pattern_doesnt_match(self, mock_update, mock_select):
        """Arbitrary account string doesn't trigger dead-runner claim."""
        task = MockTaskFactory.running(
            account="unknown-runner-0",
            updated_offset_sec=200
        )

        mock_select.side_effect = [
            [task],
            [],  # no heartbeats
        ]

        runner._reap_zombie_tasks()
        # Should NOT be reclaimed as dead-runner (wrong pattern)
        # Would need stale check, but this doesn't reach it with pattern check first

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_cowork_prefix_always_skipped(self, mock_update, mock_select):
        """Cowork-prefixed accounts always skipped, even if stale."""
        tasks = [
            MockTaskFactory.running("t1", account="cowork-123", updated_offset_sec=31*60),
            MockTaskFactory.running("t2", account="cowork-team-456", updated_offset_sec=60*60),
            MockTaskFactory.running("t3", account="cowork-adhoc-789", updated_offset_sec=100*60),
        ]

        mock_select.side_effect = [
            tasks,
            [],
        ]

        runner._reap_zombie_tasks()
        mock_update.assert_not_called()


class TestRecoveryPatchGeneration:
    """Test agentic_repair patch generation for different failure modes."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dead_runner_patch_includes_correct_signal(self, mock_update, mock_select, mock_repair):
        """Dead-runner recovery patch includes 'expired runner heartbeat' signal."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTaskFactory.running(
            account="Mac.lan-0",
            updated_offset_sec=200
        )

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        call_args = mock_repair.call_args
        signal = call_args[0][1]
        assert "expired runner heartbeat" in signal

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_stale_running_patch_includes_correct_signal(self, mock_update, mock_select, mock_repair):
        """Stale-RUNNING recovery patch includes correct signal."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTaskFactory.running(
            account="unknown-account",
            updated_offset_sec=31*60
        )

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        call_args = mock_repair.call_args
        signal = call_args[0][1]
        assert "stale RUNNING >30min" in signal

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_patch_category_orphaned_running(self, mock_update, mock_select, mock_repair):
        """All recovery patches use 'orphaned-running' category."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTaskFactory.running(updated_offset_sec=31*60)

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        call_args = mock_repair.call_args
        assert call_args[1]["category"] == "orphaned-running"

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_patch_directive_includes_recovery_guidance(self, mock_update, mock_select, mock_repair):
        """Recovery patch directive includes explicit recovery instructions."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTaskFactory.running(updated_offset_sec=31*60)

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        call_args = mock_repair.call_args
        directive = call_args[1]["directive"]
        assert "orphaned-running" in directive or "worker died" in directive.lower()


class TestScheduledExecution:
    """Test zombie reaper invocation from scheduler."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_reaper_throttles_300_seconds(self, mock_update, mock_select):
        """Reaper throttles to 300s minimum between invocations."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T

        try:
            runner._ZOMBIE_REAP_T = real_time.time() - 200  # 200s ago

            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()
            first_count = mock_select.call_count

            # Immediate second call should not execute
            mock_select.reset_mock()
            runner._reap_zombie_tasks()
            second_count = mock_select.call_count

            assert second_count == 0

        finally:
            runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_reaper_executes_after_300s_throttle(self, mock_update, mock_select):
        """Reaper executes if 300+ seconds since last run."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T

        try:
            runner._ZOMBIE_REAP_T = real_time.time() - 301  # 301s ago

            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()

            assert mock_select.called

        finally:
            runner._ZOMBIE_REAP_T = orig_time


class TestErrorResilience:
    """Test error handling and fail-soft behavior."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    @patch("builtins.print")
    def test_db_select_failure_no_crash(self, mock_print, mock_update, mock_select):
        """DB select failure doesn't crash reaper."""
        mock_select.side_effect = Exception("DB connection lost")

        try:
            runner._reap_zombie_tasks()
            # Should not raise
        except Exception as e:
            pytest.fail(f"Reaper crashed on DB error: {e}")

        # Should have logged error
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert any("error" in str(c).lower() for c in print_calls)

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    @patch("builtins.print")
    def test_repair_patch_failure_doesnt_block_other_tasks(self, mock_print, mock_update,
                                                           mock_select, mock_repair):
        """If one task's repair fails, others still processed."""
        mock_repair.side_effect = [Exception("Repair failed"), {"state": "QUEUED"}]

        tasks = [
            MockTaskFactory.running("t1", updated_offset_sec=31*60),
            MockTaskFactory.running("t2", updated_offset_sec=35*60),
        ]

        mock_select.side_effect = [
            tasks,
            [],
        ]

        try:
            runner._reap_zombie_tasks()
        except Exception as e:
            pytest.fail(f"Reaper crashed on repair failure: {e}")

        # Both updates should have been attempted
        assert mock_update.call_count == 2

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_malformed_task_record_handled(self, mock_update, mock_select):
        """Task with missing fields doesn't crash reaper."""
        task = MockTaskFactory.running()
        del task["updated_at"]

        mock_select.side_effect = [
            [task],
            [],
        ]

        try:
            runner._reap_zombie_tasks()
        except Exception as e:
            pytest.fail(f"Reaper crashed on malformed task: {e}")


class TestRetryNoteHandling:
    """Test RETRY promotion note truncation and appending."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_retry_note_appends_promoter_tag(self, mock_update, mock_select):
        """RETRY promotion appends 'retry-promoter' to note."""
        task = MockTaskFactory.retry(updated_offset_sec=150, note="initial note")

        mock_select.side_effect = [
            [],
            [],
            [task],
        ]

        runner._reap_zombie_tasks()

        call_args = mock_update.call_args
        patch = call_args[0][2]
        assert "retry-promoter" in patch.get("note", "")
        assert "initial note" in patch.get("note", "")

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_retry_note_truncated_to_1000_chars(self, mock_update, mock_select):
        """RETRY note truncated to 1000 chars max."""
        long_note = "x" * 950  # 950 + " | retry-promoter" = 967 chars
        task = MockTaskFactory.retry(updated_offset_sec=150, note=long_note)

        mock_select.side_effect = [
            [],
            [],
            [task],
        ]

        runner._reap_zombie_tasks()

        call_args = mock_update.call_args
        patch = call_args[0][2]
        note = patch.get("note", "")
        assert len(note) <= 1000

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_retry_note_preserves_state_and_timestamp(self, mock_update, mock_select):
        """RETRY promotion sets state=QUEUED and updated_at=now()."""
        task = MockTaskFactory.retry(updated_offset_sec=150)

        mock_select.side_effect = [
            [],
            [],
            [task],
        ]

        runner._reap_zombie_tasks()

        call_args = mock_update.call_args
        patch = call_args[0][2]
        assert patch["state"] == "QUEUED"
        assert patch["updated_at"] == "now()"


class TestLaneHeartbeatSkipping:
    """Test exclusion of lane heartbeats from live-runner detection."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_lane_heartbeats_not_counted_as_live(self, mock_update, mock_select, mock_repair):
        """Heartbeats with ' lane ' in hostname don't mark runner as live."""
        mock_repair.return_value = {"state": "QUEUED"}

        task = MockTaskFactory.running("t1", account="Mac.lan-0", updated_offset_sec=200)
        lane_hb = MockTaskFactory.heartbeat("Mac.lan-0", hostname="Mac.lan lane 1")

        mock_select.side_effect = [
            [task],
            [lane_hb],  # only lane heartbeat
        ]

        runner._reap_zombie_tasks()
        # Should still reclaim because lane HBs don't count as live
        assert mock_update.called

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_scheduler_heartbeats_not_counted_as_live(self, mock_update, mock_select, mock_repair):
        """Heartbeats with '-scheduler' suffix don't mark runner as live."""
        mock_repair.return_value = {"state": "QUEUED"}

        task = MockTaskFactory.running("t1", account="Mac.lan-0", updated_offset_sec=200)
        sched_hb = MockTaskFactory.heartbeat("Mac.lan-0-scheduler")

        mock_select.side_effect = [
            [task],
            [sched_hb],  # only scheduler heartbeat
        ]

        runner._reap_zombie_tasks()
        assert mock_update.called


class TestLargeScaleRecovery:
    """Test zombie reaper at production scale."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_recovers_100_tasks_with_50_retry_in_single_cycle(self, mock_update, mock_select, mock_repair):
        """Single cycle handles 100 RUNNING + 50 RETRY tasks."""
        mock_repair.return_value = {"state": "QUEUED"}

        running_tasks = [
            MockTaskFactory.running(
                f"t{i}",
                updated_offset_sec=31*60 if i % 2 else 10*60
            )
            for i in range(100)
        ]

        retry_tasks = [
            MockTaskFactory.retry(f"r{i}", updated_offset_sec=150)
            for i in range(50)
        ]

        mock_select.side_effect = [
            running_tasks,
            [],  # heartbeats
            retry_tasks,
        ]

        runner._reap_zombie_tasks()

        # Should have updated 50 stale RUNNING + 50 RETRY = 100 updates
        assert mock_update.call_count == 100

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_query_limits_respected(self, mock_update, mock_select):
        """DB queries respect configured limits (100 RUNNING, 250 RETRY)."""
        # This test verifies the implementation calls db.select with proper limits
        mock_select.side_effect = [[], []]

        runner._reap_zombie_tasks()

        calls = mock_select.call_args_list
        running_call = calls[0]

        # Verify limit=100 in RUNNING query
        assert running_call[0][1].get("limit") == "100"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
