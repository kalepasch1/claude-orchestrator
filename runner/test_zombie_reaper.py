#!/usr/bin/env python3
"""
test_zombie_reaper.py - Comprehensive tests for zombie-reaper task reclamation.

Tests the _reap_zombie_tasks() function that:
  - Detects and reclaims dead RUNNING tasks (runner heartbeat expired)
  - Detects and reclaims stale RUNNING tasks (>30min without update)
  - Promotes elapsed RETRY tasks back to QUEUED
  - Skips cowork-dispatched tasks (separate execution context)
  - Handles errors gracefully without wedging the runner

Environment variables tested:
  ORCH_DEAD_RUNNER_RECLAIM_GRACE_S (default: 180s)
  FLEET_TTL_S (default: 180s)
  ORCH_RETRY_PROMOTE_AFTER_S (default: 120s)
"""
import sys
import os
import time
import json
import datetime
from unittest.mock import patch, MagicMock, call
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB at module load
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

# PATCH TARGETS ARE `db.*` / `agentic_repair.*`, NOT `runner.db.*`
# -----------------------------------------------------------------
# Every @patch in this file used to name `runner.db.select`. That resolves through
# the runner PACKAGE, which has no `db` attribute, so mock imported a second copy
# of runner/db.py under the name `runner.db`. Meanwhile runner.py does
# `sys.path.insert(_RUNNER_DIR); import db` and calls the FLAT module. Same file,
# two module objects, two independent `select` attributes — the patch landed on the
# copy nobody calls, the real function ran, and 19 tests failed with
# "set SUPABASE_URL and SUPABASE_SERVICE_KEY": a credentials error with nothing to
# do with the behaviour under test.
#
# Patch the flat names. They are the ones runner.py holds a reference to.

# Import the runner.py module directly (not the package)
import importlib.util
_spec = importlib.util.spec_from_file_location("runner", os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py"))
runner = importlib.util.module_from_spec(_spec)
sys.modules["runner"] = runner  # Register in sys.modules so patches work
_spec.loader.exec_module(runner)


@pytest.fixture(autouse=True)
def _clear_reap_throttle():
    """Reset the reaper's 300s cooldown before and after every test in this file.

    `_reap_zombie_tasks()` opens with `if time.time() - _ZOMBIE_REAP_T < 300: return`,
    and `_ZOMBIE_REAP_T` is module state that survives between tests. So the FIRST
    test to call the reaper armed the cooldown and every later test in the same
    process got an early return — no queries, no updates, and assertions failing on
    an empty `call_args_list` for reasons that had nothing to do with the code under
    test. Which tests failed depended on collection order, which is why this looked
    intermittent.

    Individual tests that need a specific cooldown value (the throttling test) still
    set it themselves; this only guarantees a clean starting point.
    """
    import time as real_time
    runner._ZOMBIE_REAP_T = 0.0
    yield
    runner._ZOMBIE_REAP_T = 0.0
    del real_time


class MockTask:
    """Factory for creating mock task dicts."""

    @staticmethod
    def running(task_id="t1", slug="task-1", account="Mac.lan-0", updated_at_offset_min=0):
        """Create a RUNNING task dict."""
        now = datetime.datetime.now(datetime.timezone.utc)
        updated_at = (now - datetime.timedelta(minutes=updated_at_offset_min)).isoformat()
        return {
            "id": task_id,
            "slug": slug,
            "state": "RUNNING",
            "account": account,
            "updated_at": updated_at,
        }

    @staticmethod
    def retry(task_id="t2", slug="task-2", updated_at_offset_sec=0):
        """Create a RETRY task dict."""
        now = datetime.datetime.now(datetime.timezone.utc)
        updated_at = (now - datetime.timedelta(seconds=updated_at_offset_sec)).isoformat()
        return {
            "id": task_id,
            "slug": slug,
            "state": "RETRY",
            "updated_at": updated_at,
            "note": "initial note",
        }

    @staticmethod
    def heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan", last_seen_offset_sec=0):
        """Create a runner_heartbeats dict."""
        now = datetime.datetime.now(datetime.timezone.utc)
        last_seen = (now - datetime.timedelta(seconds=last_seen_offset_sec)).isoformat()
        return {
            "runner_id": runner_id,
            "hostname": hostname,
            "last_seen": last_seen,
        }


class TestZombieReaperDeadRunnerDetection:
    """Test detection of dead runners via heartbeat expiration."""

    @patch("agentic_repair.repair_patch")
    @patch("db.select")
    @patch("db.update")
    def test_reclaims_task_whose_runner_is_absent_from_a_live_heartbeat_table(
            self, mock_update, mock_select, mock_repair):
        """A claim held by a runner that other live runners have outlived is reclaimed.

        Note what "dead runner" requires: OTHER runners must be heartbeating. The
        implementation guards on `bool(live_runner_ids)` on purpose — an empty
        heartbeat table means the heartbeat feed itself is down, not that every
        runner in the fleet died, and reclaiming the whole RUNNING census off a
        failed query is the more expensive mistake. The task must also be older
        than ORCH_DEAD_RUNNER_RECLAIM_GRACE_S (180s), hence the 5-minute age.
        """
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],  # RUNNING query
            [MockTask.heartbeat(runner_id="Mac.lan-9", last_seen_offset_sec=5)],  # a DIFFERENT runner is live
            [],  # RETRY query
        ]

        runner._reap_zombie_tasks()

        # Should call update with agentic-repair patch
        assert mock_update.called
        assert mock_repair.called
        call_args = mock_update.call_args
        assert call_args[0][0] == "tasks"

    @patch("agentic_repair.repair_patch")
    @patch("db.select")
    @patch("db.update")
    def test_empty_heartbeat_table_reclaims_nothing_recent(
            self, mock_update, mock_select, mock_repair):
        """No heartbeats at all means the feed is down — do not mass-reclaim."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],  # RUNNING query
            [],  # heartbeats query — empty, i.e. unknowable
            [],  # RETRY query
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch("db.select")
    @patch("db.update")
    def test_skips_task_with_live_runner_heartbeat(self, mock_update, mock_select):
        """Task with live runner heartbeat (within TTL) is not reclaimed."""
        # Runner heartbeat exists and is recent
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=1)],  # RUNNING
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],  # heartbeat is recent
        ]

        runner._reap_zombie_tasks()

        # Should NOT update this task
        mock_update.assert_not_called()

    @patch("db.select")
    @patch("db.update")
    def test_requires_matching_account_pattern_for_dead_runner_claim(self, mock_update, mock_select):
        """Dead runner reclaim requires account matching runner ID pattern (Mac.lan-X or Mandys-MacBook-Pro.local-X)."""
        # Account name doesn't match Mac.lan-X pattern, so shouldn't claim as dead runner
        mock_select.side_effect = [
            [MockTask.running(account="unknown-runner-0", updated_at_offset_min=1)],  # unknown account
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=400)],  # runner is alive
        ]

        runner._reap_zombie_tasks()

        # Should NOT claim as dead-runner (pattern mismatch)
        mock_update.assert_not_called()

    @patch("db.select")
    @patch("db.update")
    def test_grace_period_for_dead_runner_reclaim(self, mock_update, mock_select):
        """Dead runner reclaim requires task to be older than ORCH_DEAD_RUNNER_RECLAIM_GRACE_S."""
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "300"}):
            # Task is only 200s old (within grace period)
            now = datetime.datetime.now(datetime.timezone.utc)
            updated_at = (now - datetime.timedelta(seconds=200)).isoformat()
            task = MockTask.running(account="Mac.lan-0")
            task["updated_at"] = updated_at

            mock_select.side_effect = [
                [task],
                [],  # no heartbeats (runner is dead)
            ]

            runner._reap_zombie_tasks()

            # Should NOT reclaim (within grace period)
            mock_update.assert_not_called()


class TestZombieReaperStaleTaskDetection:
    """Test detection of stale RUNNING tasks (>30min without update)."""

    @patch("agentic_repair.repair_patch")
    @patch("db.select")
    @patch("db.update")
    def test_reclaims_stale_running_task_exceeding_30_minutes(self, mock_update, mock_select, mock_repair):
        """RUNNING task >30min without update is reclaimed (stale threshold)."""
        mock_repair.return_value = {"state": "QUEUED"}
        now = datetime.datetime.now(datetime.timezone.utc)
        old_time = (now - datetime.timedelta(minutes=31)).isoformat()

        task = MockTask.running(account="unknown-account")
        task["updated_at"] = old_time

        mock_select.side_effect = [
            [task],  # stale RUNNING
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],  # runner is live
            [],  # no RETRY tasks
        ]

        runner._reap_zombie_tasks()

        # Should reclaim as stale RUNNING
        assert mock_update.called
        assert mock_repair.called

    @patch("db.select")
    @patch("db.update")
    def test_skips_recent_running_task_under_30_minutes(self, mock_update, mock_select):
        """RUNNING task <30min old is not reclaimed."""
        mock_select.side_effect = [
            [MockTask.running(account="unknown-account", updated_at_offset_min=15)],  # recent
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],
        ]

        runner._reap_zombie_tasks()

        # Should NOT reclaim (recent)
        mock_update.assert_not_called()

    @patch("agentic_repair.repair_patch")
    @patch("db.select")
    @patch("db.update")
    def test_boundary_30_minute_threshold(self, mock_update, mock_select, mock_repair):
        """RUNNING task exactly at 30min boundary: just under is safe, just over is reclaimed."""
        import time as real_time
        mock_repair.return_value = {"state": "QUEUED"}
        now = datetime.datetime.now(datetime.timezone.utc)

        # Just under 30 minutes
        task_under = MockTask.running(account="unknown")
        task_under["updated_at"] = (now - datetime.timedelta(minutes=29, seconds=59)).isoformat()

        # Reset last reap time to allow execution
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_select.side_effect = [
            [task_under],
            [],
        ]

        runner._reap_zombie_tasks()
        mock_update.assert_not_called()

        # Just over 30 minutes
        mock_update.reset_mock()
        mock_select.reset_mock()
        mock_repair.reset_mock()
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        task_over = MockTask.running(account="unknown")
        task_over["updated_at"] = (now - datetime.timedelta(minutes=30, seconds=1)).isoformat()

        mock_select.side_effect = [
            [task_over],
            [],
        ]

        runner._reap_zombie_tasks()
        assert mock_update.called
        runner._ZOMBIE_REAP_T = orig_time


class TestZombieReaperRetryPromotion:
    """Test promotion of elapsed RETRY tasks back to QUEUED."""

    @patch("db.select")
    @patch("db.update")
    def test_promotes_retry_task_exceeding_promote_threshold(self, mock_update, mock_select):
        """RETRY task older than ORCH_RETRY_PROMOTE_AFTER_S is promoted to QUEUED."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_select.side_effect = [
            [],  # no RUNNING tasks
            [],  # no heartbeats
            [MockTask.retry(updated_at_offset_sec=150)],  # RETRY older than 120s default
        ]

        runner._reap_zombie_tasks()

        # Should promote to QUEUED
        assert mock_update.called
        patch = mock_update.call_args[0][2]
        assert patch["state"] == "QUEUED"
        assert "retry-promoter" in patch.get("note", "")
        runner._ZOMBIE_REAP_T = orig_time

    @patch("db.select")
    @patch("db.update")
    def test_skips_recent_retry_task(self, mock_update, mock_select):
        """RETRY task younger than threshold is not promoted."""
        mock_select.side_effect = [
            [],
            [MockTask.retry(updated_at_offset_sec=60)],  # RETRY younger than 120s
        ]

        runner._reap_zombie_tasks()

        # Should NOT promote (recent)
        mock_update.assert_not_called()

    @patch("db.select")
    @patch("db.update")
    def test_retry_promotion_appends_to_note(self, mock_update, mock_select):
        """Promoting RETRY appends 'retry-promoter' to existing note (with 1000-char limit)."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        existing_note = "x" * 900
        task = MockTask.retry(updated_at_offset_sec=150)
        task["note"] = existing_note

        mock_select.side_effect = [
            [],  # no RUNNING tasks
            [],  # no heartbeats
            [task],  # RETRY task
        ]

        runner._reap_zombie_tasks()

        patch = mock_update.call_args[0][2]
        # Should have original note + " | retry-promoter" (limited to 1000 chars)
        assert "retry-promoter" in patch.get("note", "")
        assert len(patch.get("note", "")) <= 1000
        runner._ZOMBIE_REAP_T = orig_time

    @patch("db.select")
    @patch("db.update")
    def test_respects_orch_retry_promote_after_s_env_var(self, mock_update, mock_select):
        """ORCH_RETRY_PROMOTE_AFTER_S env var controls promotion threshold."""
        import time as real_time
        original_val = os.environ.get("ORCH_RETRY_PROMOTE_AFTER_S")
        orig_time = runner._ZOMBIE_REAP_T

        try:
            os.environ["ORCH_RETRY_PROMOTE_AFTER_S"] = "300"

            # The threshold is applied SERVER-side, as an `updated_at=lt.<cutoff>`
            # filter on the query — not by re-checking ages on rows that came back.
            # So what the env var controls, and what this asserts, is the cutoff the
            # query carries. (Asserting "an under-threshold row is not promoted"
            # would only be testing the mock, which returns rows regardless of filter.)
            runner._ZOMBIE_REAP_T = real_time.time() - 400
            mock_select.side_effect = [
                [],  # no RUNNING tasks
                [],  # no heartbeats
                [],  # no RETRY tasks past the cutoff
            ]

            runner._reap_zombie_tasks()
            mock_update.assert_not_called()

            retry_call = [c for c in mock_select.call_args_list
                          if c[0][1].get("state") == "eq.RETRY"][0]
            cutoff = retry_call[0][1]["updated_at"]
            assert cutoff.startswith("lt.")
            cutoff_dt = datetime.datetime.fromisoformat(cutoff[3:])
            age_s = (datetime.datetime.now(datetime.timezone.utc) - cutoff_dt).total_seconds()
            assert 290 <= age_s <= 320, f"cutoff should be ~300s ago, was {age_s}s"

            # Task is 310s old (exceeds 300s threshold)
            mock_update.reset_mock()
            mock_select.reset_mock()
            runner._ZOMBIE_REAP_T = real_time.time() - 400

            mock_select.side_effect = [
                [],  # no RUNNING tasks
                [],  # no heartbeats
                [MockTask.retry(updated_at_offset_sec=310)],  # RETRY task over threshold
            ]

            runner._reap_zombie_tasks()
            assert mock_update.called
        finally:
            if original_val is not None:
                os.environ["ORCH_RETRY_PROMOTE_AFTER_S"] = original_val
            elif "ORCH_RETRY_PROMOTE_AFTER_S" in os.environ:
                del os.environ["ORCH_RETRY_PROMOTE_AFTER_S"]
            runner._ZOMBIE_REAP_T = orig_time


class TestZombieReaperCoworkDispatch:
    """Test skipping cowork-dispatched tasks (separate execution context)."""

    @patch("db.select")
    @patch("db.update")
    def test_skips_cowork_dispatched_tasks(self, mock_update, mock_select):
        """Tasks with account starting 'cowork-' are skipped (separate execution context)."""
        mock_select.side_effect = [
            [MockTask.running(account="cowork-session-123", updated_at_offset_min=31)],  # stale, but cowork
            [],
        ]

        runner._reap_zombie_tasks()

        # Should NOT reclaim cowork tasks
        mock_update.assert_not_called()

    @patch("db.select")
    @patch("db.update")
    def test_skips_cowork_prefixed_variations(self, mock_update, mock_select):
        """All cowork-* prefixed accounts are skipped."""
        tasks = [
            MockTask.running(account="cowork-123", updated_at_offset_min=31),
            MockTask.running(account="cowork-team-456", updated_at_offset_min=31),
            MockTask.running(account="cowork-adhoc", updated_at_offset_min=31),
        ]
        mock_select.side_effect = [
            tasks,
            [],
        ]

        runner._reap_zombie_tasks()

        # None should be reclaimed
        mock_update.assert_not_called()


class TestZombieReaperMultipleTasks:
    """Test handling multiple tasks in a single reap cycle."""

    @patch("agentic_repair.repair_patch")
    @patch("db.select")
    @patch("db.update")
    def test_reclaims_multiple_stale_tasks_in_one_cycle(self, mock_update, mock_select, mock_repair):
        """Reaper finds and reclaims multiple stale RUNNING tasks."""
        import time as real_time
        mock_repair.return_value = {"state": "QUEUED"}

        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        now = datetime.datetime.now(datetime.timezone.utc)
        t1 = MockTask.running(task_id="t1", slug="task-1")
        t1["updated_at"] = (now - datetime.timedelta(minutes=31)).isoformat()
        t2 = MockTask.running(task_id="t2", slug="task-2")
        t2["updated_at"] = (now - datetime.timedelta(minutes=40)).isoformat()
        t3 = MockTask.running(task_id="t3", slug="task-3")
        t3["updated_at"] = (now - datetime.timedelta(minutes=15)).isoformat()

        mock_select.side_effect = [
            [t1, t2, t3],  # RUNNING tasks
            [],  # heartbeats
            [],  # RETRY tasks
        ]

        runner._reap_zombie_tasks()

        # Should update 2 (t1, t2) but not t3
        assert mock_update.call_count == 2
        calls = mock_update.call_args_list
        updated_ids = {call[0][1]["id"] for call in calls}
        assert "t1" in updated_ids
        assert "t2" in updated_ids
        assert "t3" not in updated_ids
        runner._ZOMBIE_REAP_T = orig_time

    @patch("db.select")
    @patch("db.update")
    def test_promotes_multiple_retry_tasks(self, mock_update, mock_select):
        """Reaper promotes multiple expired RETRY tasks in one cycle."""
        import time as real_time
        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        mock_select.side_effect = [
            [],  # no RUNNING tasks
            [],  # no heartbeats
            [
                MockTask.retry(task_id="r1", slug="retry-1", updated_at_offset_sec=150),
                MockTask.retry(task_id="r2", slug="retry-2", updated_at_offset_sec=200),
            ],  # RETRY tasks
        ]

        runner._reap_zombie_tasks()

        # Should update 2 RETRY tasks
        assert mock_update.call_count == 2
        runner._ZOMBIE_REAP_T = orig_time

    @patch("agentic_repair.repair_patch")
    @patch("db.select")
    @patch("db.update")
    def test_mixes_reclaim_and_promote_in_single_cycle(self, mock_update, mock_select, mock_repair):
        """Reaper reclaims RUNNING and promotes RETRY in the same cycle."""
        import time as real_time
        mock_repair.return_value = {"state": "QUEUED"}

        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        now = datetime.datetime.now(datetime.timezone.utc)
        t1 = MockTask.running(task_id="t1")
        t1["updated_at"] = (now - datetime.timedelta(minutes=31)).isoformat()

        mock_select.side_effect = [
            [t1],  # stale RUNNING
            [],  # no heartbeats
            [MockTask.retry(task_id="r1", updated_at_offset_sec=150)],  # expired RETRY
        ]

        runner._reap_zombie_tasks()

        # Should update 2 tasks (1 RUNNING, 1 RETRY)
        assert mock_update.call_count == 2
        runner._ZOMBIE_REAP_T = orig_time


class TestZombieReaperEdgeCases:
    """Test edge cases and error conditions."""

    @patch("db.select")
    @patch("db.update")
    def test_handles_db_select_failure_gracefully(self, mock_update, mock_select):
        """DB select failure is caught, logged, and doesn't wedge runner."""
        mock_select.side_effect = Exception("DB connection lost")

        # Should not raise
        runner._reap_zombie_tasks()

        # Should not attempt update
        mock_update.assert_not_called()

    @patch("agentic_repair.repair_patch")
    @patch("db.select")
    @patch("db.update")
    def test_handles_db_update_failure_gracefully(self, mock_update, mock_select, mock_repair):
        """DB update failure for a task doesn't prevent other tasks from being updated."""
        import time as real_time
        mock_repair.return_value = {"state": "QUEUED"}

        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        now = datetime.datetime.now(datetime.timezone.utc)
        t1 = MockTask.running(task_id="t1")
        t1["updated_at"] = (now - datetime.timedelta(minutes=31)).isoformat()
        t2 = MockTask.running(task_id="t2")
        t2["updated_at"] = (now - datetime.timedelta(minutes=35)).isoformat()

        mock_select.side_effect = [
            [t1, t2],  # RUNNING tasks
            [],  # heartbeats
            [],  # RETRY tasks
        ]
        # First update fails, second succeeds
        mock_update.side_effect = [Exception("DB error"), None]

        # Should not raise
        runner._reap_zombie_tasks()

        # Should have attempted both updates
        assert mock_update.call_count == 2
        runner._ZOMBIE_REAP_T = orig_time

    @patch("db.select")
    @patch("db.update")
    def test_empty_running_and_retry_lists(self, mock_update, mock_select):
        """Reaper handles empty task lists gracefully."""
        mock_select.side_effect = [
            [],  # no RUNNING
            [],  # no RETRY
        ]

        # Should not crash
        runner._reap_zombie_tasks()

        # No updates
        mock_update.assert_not_called()

    @patch("db.select")
    @patch("db.update")
    def test_missing_updated_at_field_defaults_safely(self, mock_update, mock_select):
        """Tasks without updated_at field are handled safely."""
        task = MockTask.running(updated_at_offset_min=31)
        del task["updated_at"]

        mock_select.side_effect = [
            [task],
            [],
        ]

        # Should not crash (uses default empty string which is < cutoff)
        runner._reap_zombie_tasks()

    @patch("db.select")
    @patch("db.update")
    def test_missing_account_field_defaults_safely(self, mock_update, mock_select):
        """Tasks without account field are handled safely."""
        task = MockTask.running(updated_at_offset_min=31)
        del task["account"]

        mock_select.side_effect = [
            [task],
            [],
        ]

        # Should not crash (uses default empty string)
        runner._reap_zombie_tasks()

    @patch("agentic_repair.repair_patch")
    @patch("db.select")
    @patch("db.update")
    def test_heartbeat_query_failure_falls_back_to_stale_check(self, mock_update, mock_select, mock_repair):
        """If heartbeat query fails, still reclaims via stale check."""
        import time as real_time
        mock_repair.return_value = {"state": "QUEUED"}

        orig_time = runner._ZOMBIE_REAP_T
        runner._ZOMBIE_REAP_T = real_time.time() - 400

        now = datetime.datetime.now(datetime.timezone.utc)
        t1 = MockTask.running(task_id="t1")
        t1["updated_at"] = (now - datetime.timedelta(minutes=31)).isoformat()

        mock_select.side_effect = [
            [t1],
            Exception("Heartbeat query failed"),
        ]

        runner._reap_zombie_tasks()

        # Should still reclaim as stale (via fallback)
        assert mock_update.called
        runner._ZOMBIE_REAP_T = orig_time


class TestZombieReaperThrottling:
    """Test reaper throttling (300s cooldown between runs)."""

    @patch("db.select")
    @patch("db.update")
    def test_throttles_calls_300_seconds_apart(self, mock_update, mock_select):
        """Reaper skips execution if called within 300s of last run."""
        import time as real_time

        # Save original time value
        orig_time = runner._ZOMBIE_REAP_T
        try:
            runner._ZOMBIE_REAP_T = real_time.time() - 400  # Set to 400s ago to allow execution

            # First call - should execute
            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()
            first_call_count = mock_select.call_count
            assert first_call_count > 0

            # Second call immediately - should skip
            mock_select.reset_mock()
            runner._reap_zombie_tasks()
            assert mock_select.call_count == 0  # Should skip within 300s
        finally:
            runner._ZOMBIE_REAP_T = orig_time


class TestZombieReaperAgenticRepairIntegration:
    """Test integration with agentic_repair module."""

    @patch("agentic_repair.repair_patch")
    @patch("db.select")
    @patch("db.update")
    def test_calls_agentic_repair_for_dead_runner_task(self, mock_update, mock_select, mock_repair_patch):
        """Reclaimed task uses agentic_repair.repair_patch() to build update."""
        mock_repair_patch.return_value = {"state": "QUEUED", "prompt": "..."}

        # A dead-runner claim needs OTHER runners alive (see the guard on
        # `live_runner_ids`) and the task older than the 180s reclaim grace.
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],  # RUNNING task
            [MockTask.heartbeat(runner_id="Mac.lan-9", last_seen_offset_sec=5)],  # another runner is live
            [],  # RETRY tasks
        ]

        runner._reap_zombie_tasks()

        # Should have called repair_patch with category="orphaned-running"
        assert mock_repair_patch.called
        call_args = mock_repair_patch.call_args
        assert call_args[1]["category"] == "orphaned-running"
        # The reason lives in the positional signal; `directive` is the generic
        # instruction handed to the resuming agent and is the same either way.
        assert "expired runner heartbeat" in call_args[0][1]
        assert "RUNNING task" in call_args[1]["directive"]

    @patch("agentic_repair.repair_patch")
    @patch("db.select")
    @patch("db.update")
    def test_repair_prompt_includes_failure_context(self, mock_update, mock_select, mock_repair_patch):
        """Agentic repair prompt includes zombie-reaper context."""
        mock_repair_patch.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],  # RUNNING task
            [MockTask.heartbeat(runner_id="Mac.lan-9", last_seen_offset_sec=5)],  # another runner is live
            [],  # RETRY tasks
        ]

        runner._reap_zombie_tasks()

        # Verify repair_patch was called with proper signal
        assert mock_repair_patch.called
        signal_arg = mock_repair_patch.call_args[0][1]
        assert "zombie-reaper: expired runner heartbeat" in signal_arg


class TestZombieReaperPrintOutput:
    """Test diagnostic print output."""

    @patch("db.select")
    @patch("db.update")
    @patch("builtins.print")
    def test_prints_reclaim_count_on_success(self, mock_print, mock_update, mock_select):
        """Reaper prints count of reclaimed tasks."""
        mock_select.side_effect = [
            [
                MockTask.running(task_id="t1", updated_at_offset_min=31),
                MockTask.running(task_id="t2", updated_at_offset_min=35),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        # Should have printed reclaim count
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert any("reclaimed 2" in str(call) for call in print_calls)

    @patch("db.select")
    @patch("db.update")
    @patch("builtins.print")
    def test_prints_promote_count_on_success(self, mock_print, mock_update, mock_select):
        """Reaper prints count of promoted RETRY tasks."""
        mock_select.side_effect = [
            [],  # RUNNING tasks
            [],  # heartbeats
            [MockTask.retry(updated_at_offset_sec=150)],  # RETRY tasks
        ]

        runner._reap_zombie_tasks()

        # Should have printed promotion count
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert any("returned" in str(call) for call in print_calls)

    @patch("db.select")
    @patch("db.update")
    @patch("builtins.print")
    def test_prints_error_on_exception(self, mock_print, mock_update, mock_select):
        """Reaper prints error message on exception."""
        mock_select.side_effect = Exception("DB failure")

        runner._reap_zombie_tasks()

        # Should have printed error
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert any("error" in str(call).lower() for call in print_calls)


class TestZombieReaperDbQuery:
    """Test database query structure and parameters."""

    @patch("db.select")
    @patch("db.update")
    def test_running_query_selects_correct_fields(self, mock_update, mock_select):
        """RUNNING query requests id, slug, updated_at, account fields."""
        mock_select.side_effect = [[], []]

        runner._reap_zombie_tasks()

        # Check first query (RUNNING tasks)
        first_call = mock_select.call_args_list[0]
        assert first_call[0][0] == "tasks"
        query = first_call[0][1]
        assert "id" in query["select"]
        assert "slug" in query["select"]
        assert "updated_at" in query["select"]
        assert "account" in query["select"]
        assert query["state"] == "eq.RUNNING"

    @patch("db.select")
    @patch("db.update")
    def test_heartbeat_query_filters_by_recency(self, mock_update, mock_select):
        """Heartbeat query filters by last_seen > cutoff."""
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        # Check heartbeat query
        heartbeat_calls = [c for c in mock_select.call_args_list if c[0][0] == "runner_heartbeats"]
        if heartbeat_calls:
            query = heartbeat_calls[0][0][1]
            assert "last_seen" in query
            # Should have gte filter
            assert any("gte" in str(v) for v in query.values())

    @patch("db.select")
    @patch("db.update")
    def test_retry_query_selects_correct_fields(self, mock_update, mock_select):
        """RETRY query requests id, note, updated_at fields."""
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        # Select the RETRY query by its filter, not by position. Positional indexing
        # broke silently the moment the runner_heartbeats query was inserted between
        # the two `tasks` queries — index 1 became a different table entirely.
        retry_calls = [c for c in mock_select.call_args_list
                       if c[0][0] == "tasks" and c[0][1].get("state") == "eq.RETRY"]
        assert retry_calls, "reaper never queried RETRY tasks"
        query = retry_calls[0][0][1]
        assert "id" in query["select"]
        assert "note" in query["select"]
        assert "updated_at" in query["select"]
        assert query["state"] == "eq.RETRY"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
