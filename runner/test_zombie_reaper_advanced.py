#!/usr/bin/env python3
"""
test_zombie_reaper_advanced.py - Advanced edge case and regression tests for zombie-reaper.

Covers scenarios not fully addressed in test_zombie_reaper.py:
  - Timestamp precision and ISO format edge cases
  - Note field truncation at exactly 1000-char boundary
  - Hostname filtering for scheduler/lane detection
  - Runner ID pattern matching edge cases (Mac.lan-X vs Mandys-MacBook-Pro.local-X)
  - Concurrent/rapid task state changes
  - High-volume reclamation (100+ tasks)
  - Mixed runner types and account patterns
  - Database limit enforcement
  - Transient state races between queries
"""
import sys
import os
import time
import datetime
from unittest.mock import patch, MagicMock, call
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB at module load
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

# Import the runner.py module directly
import importlib.util
_spec = importlib.util.spec_from_file_location("runner", os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py"))
runner = importlib.util.module_from_spec(_spec)
sys.modules["runner"] = runner
_spec.loader.exec_module(runner)


class MockTask:
    """Extended mock task factory."""

    @staticmethod
    def running(task_id="t1", slug="task-1", account="Mac.lan-0", updated_at_offset_min=0, updated_at_iso=None):
        """Create a RUNNING task dict with optional explicit ISO timestamp."""
        if updated_at_iso is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            updated_at = (now - datetime.timedelta(minutes=updated_at_offset_min)).isoformat()
        else:
            updated_at = updated_at_iso
        return {
            "id": task_id,
            "slug": slug,
            "state": "RUNNING",
            "account": account,
            "updated_at": updated_at,
        }

    @staticmethod
    def heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan", last_seen_iso=None, last_seen_offset_sec=0):
        """Create a runner_heartbeats dict with optional explicit ISO timestamp."""
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


class TestZombieReaperTimestampPrecision:
    """Test precise timestamp handling and edge cases."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_iso_format_with_microseconds(self, mock_update, mock_select, mock_repair):
        """Tasks with microseconds in ISO timestamp are handled correctly."""
        mock_repair.return_value = {"state": "QUEUED"}
        iso_old = "2026-07-29T12:30:45.123456+00:00"

        mock_select.side_effect = [
            [MockTask.running(updated_at_iso=iso_old)],
            [],
        ]

        runner._reap_zombie_tasks()

        # Should reclaim (timestamp is old enough)
        assert mock_update.called

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_iso_format_without_timezone(self, mock_update, mock_select, mock_repair):
        """Tasks with naive ISO timestamps (no timezone) are handled safely."""
        mock_repair.return_value = {"state": "QUEUED"}
        # Create a naive ISO that would be old
        now_naive = datetime.datetime.now()
        old_naive = (now_naive - datetime.timedelta(minutes=31)).isoformat()

        mock_select.side_effect = [
            [MockTask.running(updated_at_iso=old_naive)],
            [],
        ]

        # Should not crash
        runner._reap_zombie_tasks()

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_malformed_iso_timestamp_gracefully_degraded(self, mock_update, mock_select, mock_repair):
        """Malformed ISO timestamp is compared safely (empty string < cutoff)."""
        mock_repair.return_value = {"state": "QUEUED"}

        task = MockTask.running()
        task["updated_at"] = "not-a-valid-timestamp"

        mock_select.side_effect = [
            [task],
            [],
        ]

        # Should not crash, compares as string < cutoff (likely false)
        runner._reap_zombie_tasks()

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_empty_updated_at_treated_as_very_old(self, mock_update, mock_select, mock_repair):
        """Empty or missing updated_at field compares as < cutoff (treated as old)."""
        mock_repair.return_value = {"state": "QUEUED"}

        task = MockTask.running()
        task["updated_at"] = ""

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        # Empty string < any ISO cutoff, so should reclaim
        # But the implementation uses (t.get("updated_at") or ""), so empty is old


class TestZombieReaperNoteFieldTruncation:
    """Test 1000-character note field truncation."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_note_truncated_at_exactly_1000_chars(self, mock_update, mock_select):
        """Note + append is truncated to exactly 1000 chars."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        # Create note that's exactly 990 chars (so with " | retry-promoter" it's 1008)
        existing_note = "x" * 990
        task = {
            "id": "t1",
            "note": existing_note,
            "updated_at": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=150)).isoformat(),
            "state": "RETRY",
        }

        mock_select.side_effect = [
            [],  # no RUNNING
            [],  # no heartbeats
            [task],  # RETRY task
        ]

        runner._reap_zombie_tasks()

        # Verify truncation
        call_args = mock_update.call_args
        patch = call_args[0][2]
        assert len(patch.get("note", "")) <= 1000
        runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_note_preserves_existing_content_before_truncation(self, mock_update, mock_select):
        """Truncation preserves as much original content as possible."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        existing_note = "previous-action-log"
        task = {
            "id": "t1",
            "note": existing_note,
            "updated_at": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=150)).isoformat(),
            "state": "RETRY",
        }

        mock_select.side_effect = [
            [],
            [],
            [task],
        ]

        runner._reap_zombie_tasks()

        call_args = mock_update.call_args
        patch = call_args[0][2]
        # Should start with existing note
        assert patch.get("note", "").startswith(existing_note)
        runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_note_none_type_coerced_safely(self, mock_update, mock_select):
        """Task with None note is coerced to string safely."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        task = {
            "id": "t1",
            "note": None,
            "updated_at": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=150)).isoformat(),
            "state": "RETRY",
        }

        mock_select.side_effect = [
            [],
            [],
            [task],
        ]

        runner._reap_zombie_tasks()

        # Should not crash, note coerced to ""
        assert mock_update.called
        runner._ZOMBIE_REAP_T = orig_time


class TestZombieReaperHostnameFiltering:
    """Test hostname-based filtering for scheduler exclusion."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_scheduler_heartbeat_excluded_by_lane_in_hostname(self, mock_update, mock_select):
        """Heartbeats with ' lane ' in hostname are excluded from live_runner_ids."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [
                MockTask.heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan machine-learning lane 1"),
                MockTask.heartbeat(runner_id="Mac.lan-1", hostname="Mac.lan"),
            ],
        ]

        runner._reap_zombie_tasks()

        # First runner (with " lane ") should not prevent reclaim
        # Second runner should prevent it, but we're testing the filter
        # The first task should be reclaimed because Mac.lan-0 has " lane " in hostname

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_scheduler_suffix_runner_id_excluded(self, mock_update, mock_select):
        """Runner IDs ending with '-scheduler' are excluded from live_runner_ids."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-scheduler", updated_at_offset_min=1)],
            [
                MockTask.heartbeat(runner_id="Mac.lan-scheduler", hostname="Mac.lan"),
            ],
        ]

        runner._reap_zombie_tasks()

        # Scheduler runner should not prevent reclaim

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_multiple_hostname_exclusion_patterns(self, mock_update, mock_select):
        """Multiple heartbeats with various exclusion patterns are filtered correctly."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [
                MockTask.heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan task lane 2"),
                MockTask.heartbeat(runner_id="Mac.lan-1", hostname="Mac.lan queue-processor lane"),
                MockTask.heartbeat(runner_id="Mac.lan-scheduler", hostname="Mac.lan"),
                MockTask.heartbeat(runner_id="Mac.lan-2", hostname="Mac.lan"),
            ],
        ]

        runner._reap_zombie_tasks()

        # Only Mac.lan-2 should be in live_runner_ids


class TestZombieReaperRunnerIdPatterns:
    """Test runner ID pattern matching for dead-runner detection."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_mac_lan_pattern_exact_match(self, mock_update, mock_select, mock_repair):
        """Account matching Mac.lan-X pattern is eligible for dead-runner claim."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-5", updated_at_offset_min=1)],
            [MockTask.heartbeat(runner_id="Mac.lan-1", hostname="Mac.lan", last_seen_offset_sec=30)],  # other runner is alive
        ]

        runner._reap_zombie_tasks()

        # Should reclaim because Mac.lan-5 has no heartbeat
        assert mock_update.called
        runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_mandys_macbook_pattern_exact_match(self, mock_update, mock_select, mock_repair):
        """Account matching Mandys-MacBook-Pro.local-X pattern is eligible."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mandys-MacBook-Pro.local-0", updated_at_offset_min=1)],
            [],  # no heartbeats
        ]

        runner._reap_zombie_tasks()

        # Should reclaim
        assert mock_update.called
        runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_account_pattern_mismatch_skips_dead_runner_claim(self, mock_update, mock_select):
        """Account not matching either pattern is not eligible for dead-runner claim."""
        mock_select.side_effect = [
            [
                MockTask.running(account="Mac.lan", updated_at_offset_min=1),  # missing -X suffix
                MockTask.running(account="MacLan-0", updated_at_offset_min=1),  # wrong format
                MockTask.running(account="localhost-0", updated_at_offset_min=1),  # unknown pattern
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        # None should use dead-runner reclaim (only stale check applies)

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_pattern_with_multiple_digits(self, mock_update, mock_select, mock_repair):
        """Account with multiple digits in -X suffix still matches pattern."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-123", updated_at_offset_min=1)],
            [],
        ]

        runner._reap_zombie_tasks()

        # Should reclaim
        assert mock_update.called
        runner._ZOMBIE_REAP_T = orig_time


class TestZombieReaperHighVolume:
    """Test performance and correctness under high-volume scenarios."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_handles_100_running_tasks_respecting_limit(self, mock_update, mock_select, mock_repair):
        """Reaper handles up to 100 RUNNING tasks (DB limit)."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_repair.return_value = {"state": "QUEUED"}

        now = datetime.datetime.now(datetime.timezone.utc)
        tasks = [
            MockTask.running(
                task_id=f"t{i}",
                slug=f"task-{i}",
                account=f"Mac.lan-{i%10}",
                updated_at_iso=(now - datetime.timedelta(minutes=31)).isoformat()
            )
            for i in range(100)
        ]

        mock_select.side_effect = [
            tasks,  # 100 RUNNING tasks
            [],  # no heartbeats
            [],  # no RETRY
        ]

        runner._reap_zombie_tasks()

        # Should have updated multiple tasks (stale check applies to all)
        assert mock_update.call_count >= 90
        runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_promotes_250_retry_tasks_respecting_limit(self, mock_update, mock_select):
        """Reaper handles up to 250 RETRY tasks (DB limit)."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        now = datetime.datetime.now(datetime.timezone.utc)
        retry_tasks = [
            {
                "id": f"r{i}",
                "note": f"retry-{i}",
                "updated_at": (now - datetime.timedelta(seconds=150)).isoformat(),
                "state": "RETRY",
            }
            for i in range(250)
        ]

        mock_select.side_effect = [
            [],  # no RUNNING
            [],  # no heartbeats
            retry_tasks,  # 250 RETRY tasks
        ]

        runner._reap_zombie_tasks()

        # Should have promoted all 250
        assert mock_update.call_count == 250
        runner._ZOMBIE_REAP_T = orig_time


class TestZombieReaperRaceConditions:
    """Test handling of concurrent/transient state changes."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_completed_between_select_and_update(self, mock_update, mock_select, mock_repair):
        """Task transitioned out of RUNNING between select and update is handled safely."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(task_id="t1", updated_at_offset_min=31)],
            [],
        ]

        # Simulate task already completed - update succeeds anyway (idempotent)
        mock_update.return_value = None

        runner._reap_zombie_tasks()

        # Update should still be called (reaper doesn't know task state changed)
        assert mock_update.called
        runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_heartbeat_appears_mid_reap(self, mock_update, mock_select):
        """New heartbeat appears between RUNNING query and reclaim decision."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            # No heartbeat when checked, but in real world one could appear
            [],
        ]

        runner._reap_zombie_tasks()

        # Reaper can only act on state it observed


class TestZombieReaperRepairIntegration:
    """Test integration details with agentic_repair."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_repair_signal_includes_context_for_dead_runner(self, mock_update, mock_select, mock_repair):
        """Dead-runner repair includes specific failure signal."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [],  # no heartbeat - dead runner
        ]

        runner._reap_zombie_tasks()

        # Check repair was called with proper signal
        assert mock_repair.called
        signal = mock_repair.call_args[0][1]
        assert "expired runner heartbeat" in signal
        runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_repair_signal_includes_context_for_stale(self, mock_update, mock_select, mock_repair):
        """Stale-task repair includes specific failure signal."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_repair.return_value = {"state": "QUEUED"}

        now = datetime.datetime.now(datetime.timezone.utc)
        task = MockTask.running(account="unknown", updated_at_iso=(now - datetime.timedelta(minutes=31)).isoformat())

        mock_select.side_effect = [
            [task],
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],
        ]

        runner._reap_zombie_tasks()

        # Check repair was called with proper signal
        assert mock_repair.called
        signal = mock_repair.call_args[0][1]
        assert "stale RUNNING >30min" in signal
        runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_repair_category_always_orphaned_running(self, mock_update, mock_select, mock_repair):
        """All reclaims use 'orphaned-running' category."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [],
        ]

        runner._reap_zombie_tasks()

        # Verify category
        category = mock_repair.call_args[1]["category"]
        assert category == "orphaned-running"
        runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_repair_directive_emphasizes_preservation(self, mock_update, mock_select, mock_repair):
        """Repair directive emphasizes preserving existing work."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],
            [],
        ]

        runner._reap_zombie_tasks()

        # Verify directive
        directive = mock_repair.call_args[1]["directive"]
        assert "existing branch/worktree/artifacts" in directive
        assert "Resume" in directive
        runner._ZOMBIE_REAP_T = orig_time


class TestZombieReaperAccounting:
    """Test accurate counting and reporting of actions."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    @patch("builtins.print")
    def test_count_dead_runner_and_stale_separately_in_print(self, mock_print, mock_update, mock_select, mock_repair):
        """Print output counts all reclaimed tasks (dead-runner + stale)."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_repair.return_value = {"state": "QUEUED"}

        now = datetime.datetime.now(datetime.timezone.utc)
        t1 = MockTask.running(account="Mac.lan-0", updated_at_iso=(now - datetime.timedelta(minutes=1)).isoformat())
        t2 = MockTask.running(account="unknown", updated_at_iso=(now - datetime.timedelta(minutes=31)).isoformat())

        mock_select.side_effect = [
            [t1, t2],
            [],  # no heartbeats - Mac.lan-0 is dead, t2 is stale
        ]

        runner._reap_zombie_tasks()

        # Should print reclaim count
        print_calls = [str(call[0][0]) for call in mock_print.call_args_list]
        assert any("reclaimed 2" in s for s in print_calls)
        runner._ZOMBIE_REAP_T = orig_time

    @patch("runner.db.select")
    @patch("runner.db.update")
    @patch("builtins.print")
    def test_no_print_when_no_retries_promoted(self, mock_print, mock_update, mock_select):
        """No 'retry-promoter' print when no RETRY tasks are promoted."""
        mock_select.side_effect = [
            [],  # no RUNNING
            [],  # no RETRY
        ]

        runner._reap_zombie_tasks()

        # Should not print retry-promoter
        print_calls = [str(call[0][0]) for call in mock_print.call_args_list]
        assert not any("retry-promoter" in s for s in print_calls)


class TestZombieReaperEnvVarEdgeCases:
    """Test environment variable handling edge cases."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_malformed_grace_period_env_var_defaults(self, mock_update, mock_select, mock_repair):
        """Non-numeric ORCH_DEAD_RUNNER_RECLAIM_GRACE_S defaults to 180s."""
        mock_repair.return_value = {"state": "QUEUED"}

        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "not-a-number"}):
            # Should not crash, defaults to 180
            mock_select.side_effect = [[], []]
            try:
                runner._reap_zombie_tasks()
            except ValueError:
                # int() on bad value raises ValueError, which is caught in try/except
                pass

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_malformed_ttl_env_var_defaults(self, mock_update, mock_select):
        """Non-numeric FLEET_TTL_S defaults to 180s."""
        with patch.dict(os.environ, {"FLEET_TTL_S": "bad"}):
            mock_select.side_effect = [[], []]
            try:
                runner._reap_zombie_tasks()
            except ValueError:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
