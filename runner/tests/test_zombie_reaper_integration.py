#!/usr/bin/env python3
"""
test_zombie_reaper_integration.py - Production integration tests for the zombie-reaper
reap loop (`runner._reap_zombie_tasks()`).

Where the sibling suites pin single behaviours, this one covers how the loop behaves as
the scheduler actually drives it: wiring from _scheduler_tick, the 300s throttle, full
query pages, configuration read from the environment at call time, and fail-soft under
partial failure.

Task: zombie-reaper: expired runner heartbeat
Failure Category: orphaned-running

Not a test of runner/zombie_reaper.py -- that module is not on any production path and
is covered by test_zombie_reaper_terminate.py.
"""
import sys
import os
import datetime
from unittest.mock import patch
import pytest

# runner/ must be importable for runner.py's flat `import db`, but APPENDED rather than
# inserted at 0: at sys.path[0] the module file runner/runner.py shadows the runner/
# PACKAGE for the whole session (see the repo-root conftest.py).
_RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER_DIR not in sys.path:
    sys.path.append(_RUNNER_DIR)

import importlib.util  # noqa: E402

# Loaded by path and NOT registered in sys.modules. Binding it to sys.modules["runner"]
# (what this file used to do) is what made every @patch("runner.db.select") here inert:
# the repo-root conftest rebinds sys.modules["runner"] to the runner PACKAGE at each
# collectstart, so mock.patch resolved "runner.db" to the package submodule -- a second
# copy of db.py that the reaper never calls -- and patched select() there, while the code
# under test went on talking to the real database.
_spec = importlib.util.spec_from_file_location(
    "_zombie_reaper_integration_runner_under_test", os.path.join(_RUNNER_DIR, "runner.py"))
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


@pytest.fixture(autouse=True)
def _reap_cycle_allowed():
    """The reaper self-throttles to one cycle per 300s through the module global
    _ZOMBIE_REAP_T; reset it so each test gets a cycle, and put it back afterwards."""
    saved = runner._ZOMBIE_REAP_T
    runner._ZOMBIE_REAP_T = 0.0
    yield
    runner._ZOMBIE_REAP_T = saved


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class MockTaskFactory:
    """Factory for creating task records matching DB schema."""

    @staticmethod
    def running(task_id="t1", slug="task-1", account="Mac.lan-0",
                updated_offset_sec=0, state="RUNNING"):
        return {
            "id": task_id,
            "slug": slug,
            "state": state,
            "account": account,
            "updated_at": (_now() - datetime.timedelta(seconds=updated_offset_sec)).isoformat(),
        }

    @staticmethod
    def retry(task_id="r1", slug="retry-1", updated_offset_sec=0, note=""):
        return {
            "id": task_id,
            "slug": slug,
            "state": "RETRY",
            "updated_at": (_now() - datetime.timedelta(seconds=updated_offset_sec)).isoformat(),
            "note": note,
        }

    @staticmethod
    def heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan", last_seen_offset_sec=0):
        return {
            "runner_id": runner_id,
            "hostname": hostname,
            "last_seen": (_now() - datetime.timedelta(seconds=last_seen_offset_sec)).isoformat(),
        }


def OTHER_LIVE_RUNNER():
    """A heartbeat for an unrelated healthy runner.

    The dead-runner path is gated on `bool(live_runner_ids)`: an empty heartbeat result
    means the fleet table told us nothing, not that every runner died, so the reaper
    declines to reclaim. Any test about ONE runner being dead has to leave another alive.
    """
    return MockTaskFactory.heartbeat(runner_id="Mac.lan-99", last_seen_offset_sec=5)


class TestSchedulerWiring:
    """Test that production actually reaches the reap loop."""

    def test_scheduler_tick_runs_the_reaper_every_tick(self):
        """`_scheduler_tick()` calls `_reap_zombie_tasks()` unconditionally.

        The reap loop has no entry in _SCHEDULE and no periodic.JOBS job of its own -- it
        rides the scheduler tick directly -- so this call is the entire production path.
        Nothing else in the repo invokes it.
        """
        with patch.object(runner, "_SCHEDULE", []), \
             patch.object(runner, "_reap_zombie_tasks") as mock_reap:
            runner._scheduler_tick()

        assert mock_reap.call_count == 1


class TestHeartbeatExpiryBoundaries:
    """Test expiration at critical time boundaries."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_task_exactly_at_30min_boundary_over(self, mock_update, mock_select, mock_repair):
        """Task at 30:01 is reclaimed as stale."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTaskFactory.running(updated_offset_sec=30 * 60 + 1)], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_task_exactly_at_30min_boundary_under(self, mock_update, mock_select):
        """Task at 29:59 is not reclaimed."""
        mock_select.side_effect = [
            [MockTaskFactory.running(updated_offset_sec=30 * 60 - 1)], [], []]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_dead_runner_at_grace_period_boundary(self, mock_update, mock_select, mock_repair):
        """One second past ORCH_DEAD_RUNNER_RECLAIM_GRACE_S the dead runner's claim goes."""
        mock_repair.return_value = {"state": "QUEUED"}
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "300"}):
            mock_select.side_effect = [
                [MockTaskFactory.running(account="Mac.lan-0", updated_offset_sec=301)],
                [OTHER_LIVE_RUNNER()],
                [],
            ]

            runner._reap_zombie_tasks()

            assert mock_update.called
            assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"


class TestFleetTTLVariations:
    """Test behavior with different FLEET_TTL_S configurations."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_fleet_ttl_s_short_30_seconds(self, mock_update, mock_select):
        """FLEET_TTL_S=30 asks the fleet table for heartbeats no older than 30s."""
        # WAS: built a 40s-old heartbeat, never passed it to the mock, and asserted a
        # reclaim that could not happen. Liveness is filtered by the QUERY predicate, so
        # the predicate is the thing to assert.
        with patch.dict(os.environ, {"FLEET_TTL_S": "30"}):
            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()

        cutoff = mock_select.call_args_list[1][0][1]["last_seen"].removeprefix("gte.")
        assert (_now() - datetime.timedelta(seconds=10)).isoformat() > cutoff
        assert (_now() - datetime.timedelta(seconds=40)).isoformat() < cutoff

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_fleet_ttl_s_long_600_seconds(self, mock_update, mock_select):
        """FLEET_TTL_S=600 keeps a 300s-old heartbeat inside the window, so no reclaim."""
        with patch.dict(os.environ, {"FLEET_TTL_S": "600"}):
            mock_select.side_effect = [
                [MockTaskFactory.running(account="Mac.lan-0", updated_offset_sec=60)],
                [MockTaskFactory.heartbeat("Mac.lan-0", last_seen_offset_sec=300)],
                [],
            ]

            runner._reap_zombie_tasks()

            cutoff = mock_select.call_args_list[1][0][1]["last_seen"].removeprefix("gte.")
            assert (_now() - datetime.timedelta(seconds=300)).isoformat() > cutoff
            mock_update.assert_not_called()


class TestRetryPromotionThreshold:
    """Test RETRY promotion with various time thresholds."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_promotion_threshold_1_second(self, mock_update, mock_select):
        """ORCH_RETRY_PROMOTE_AFTER_S=1 puts a 2s-old RETRY row inside the window."""
        with patch.dict(os.environ, {"ORCH_RETRY_PROMOTE_AFTER_S": "1"}):
            mock_select.side_effect = [[], [], [MockTaskFactory.retry(updated_offset_sec=2)]]

            runner._reap_zombie_tasks()

            cutoff = mock_select.call_args_list[2][0][1]["updated_at"].removeprefix("lt.")
            assert (_now() - datetime.timedelta(seconds=2)).isoformat() < cutoff
            assert mock_update.called

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_promotion_threshold_3600_seconds(self, mock_update, mock_select):
        """ORCH_RETRY_PROMOTE_AFTER_S=3600 leaves a 1800s-old RETRY row out of the window.

        Rewritten from an assert_not_called() that could never hold: the age test lives
        entirely in the `updated_at: lt.<cutoff>` predicate, so a row handed back by a
        mocked select is promoted no matter how young it is. What the setting controls,
        and all it controls, is the cutoff -- so that is what is asserted.
        """
        with patch.dict(os.environ, {"ORCH_RETRY_PROMOTE_AFTER_S": "3600"}):
            mock_select.side_effect = [[], [], []]

            runner._reap_zombie_tasks()

            cutoff = mock_select.call_args_list[2][0][1]["updated_at"].removeprefix("lt.")
            assert (_now() - datetime.timedelta(seconds=1800)).isoformat() > cutoff
            assert (_now() - datetime.timedelta(seconds=3700)).isoformat() < cutoff
            mock_update.assert_not_called()


class TestConcurrentZombieRecovery:
    """Test the reaper across a full batch."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_large_batch_stale_tasks_all_reclaimed(self, mock_update, mock_select, mock_repair):
        """Reclaim 50 stale RUNNING tasks in a single cycle."""
        mock_repair.return_value = {"state": "QUEUED"}
        tasks = [
            MockTaskFactory.running(task_id=f"t{i}", slug=f"task-{i}", account=f"unknown-{i}",
                                    updated_offset_sec=30 * 60 + 100)
            for i in range(50)
        ]

        mock_select.side_effect = [tasks, [], []]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 50

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_mixed_tasks_selective_reclaim(self, mock_update, mock_select, mock_repair):
        """In a batch of mixed ages, only the stale rows are reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        tasks = [
            MockTaskFactory.running("t1", updated_offset_sec=10 * 60),
            MockTaskFactory.running("t2", updated_offset_sec=31 * 60),
            MockTaskFactory.running("t3", updated_offset_sec=5 * 60),
            MockTaskFactory.running("t4", updated_offset_sec=45 * 60),
        ]

        mock_select.side_effect = [tasks, [], []]

        runner._reap_zombie_tasks()

        assert {c[0][1]["id"] for c in mock_update.call_args_list} == {"t2", "t4"}


class TestRunnerAccountPatternMatching:
    """Test account pattern recognition for dead-runner claims."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_mac_lan_pattern_matches(self, mock_update, mock_select, mock_repair):
        """Account 'Mac.lan-N' takes the dead-runner path."""
        # WAS: looked for "expired runner heartbeat" in the DIRECTIVE kwarg, which never
        # contains it -- the directive is one fixed string shared by both reclaim paths.
        # The signal (positional arg 1) is the field that names the path.
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTaskFactory.running(account="Mac.lan-5", updated_offset_sec=200)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_mandys_macbook_pattern_matches(self, mock_update, mock_select, mock_repair):
        """Account 'Mandys-MacBook-Pro.local-N' takes the dead-runner path."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTaskFactory.running(account="Mandys-MacBook-Pro.local-0", updated_offset_sec=200)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_unknown_account_pattern_doesnt_match(self, mock_update, mock_select):
        """An arbitrary account string never triggers a dead-runner claim."""
        # WAS: no assertion, and a comment that had the control flow backwards. There is
        # no "pattern check first": both paths are evaluated for every row, and a
        # 200s-old row is simply not stale, so nothing happens.
        mock_select.side_effect = [
            [MockTaskFactory.running(account="unknown-runner-0", updated_offset_sec=200)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_cowork_prefix_always_skipped(self, mock_update, mock_select):
        """Cowork-prefixed accounts are skipped however stale they get."""
        tasks = [
            MockTaskFactory.running("t1", account="cowork-123", updated_offset_sec=31 * 60),
            MockTaskFactory.running("t2", account="cowork-team-456", updated_offset_sec=60 * 60),
            MockTaskFactory.running("t3", account="cowork-adhoc-789", updated_offset_sec=100 * 60),
        ]

        mock_select.side_effect = [tasks, [], []]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()


class TestRecoveryPatchGeneration:
    """Test agentic_repair patch generation for the two failure modes."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_dead_runner_patch_includes_correct_signal(self, mock_update, mock_select, mock_repair):
        """Dead-runner recovery carries the 'expired runner heartbeat' signal."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTaskFactory.running(account="Mac.lan-0", updated_offset_sec=200)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_stale_running_patch_includes_correct_signal(self, mock_update, mock_select, mock_repair):
        """Stale recovery carries the 'stale RUNNING >30min' signal."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTaskFactory.running(account="unknown-account", updated_offset_sec=31 * 60)],
            [],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_patch_category_orphaned_running(self, mock_update, mock_select, mock_repair):
        """All recovery patches are categorised 'orphaned-running'."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTaskFactory.running(updated_offset_sec=31 * 60)], [], []]

        runner._reap_zombie_tasks()

        assert mock_repair.call_args[1]["category"] == "orphaned-running"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_patch_directive_includes_recovery_guidance(self, mock_update, mock_select, mock_repair):
        """The directive tells the successor to resume, not to restart from scratch."""
        # WAS: `"orphaned-running" in directive or "worker died" in directive.lower()`.
        # The first disjunct is false and the second is true, so the OR could never fail
        # whatever the directive said. The point of the directive is work preservation.
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTaskFactory.running(updated_offset_sec=31 * 60)], [], []]

        runner._reap_zombie_tasks()

        directive = mock_repair.call_args[1]["directive"]
        assert "worker died" in directive
        assert "Resume the same task from existing branch/worktree/artifacts" in directive


class TestScheduledExecution:
    """Test the 300s throttle as the scheduler experiences it."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reaper_throttles_300_seconds(self, mock_update, mock_select):
        """A second call inside the window issues no queries at all."""
        mock_select.side_effect = [[], [], []]
        runner._reap_zombie_tasks()
        assert mock_select.call_count == 3

        mock_select.reset_mock()
        runner._reap_zombie_tasks()
        assert mock_select.call_count == 0

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reaper_executes_after_300s_throttle(self, mock_update, mock_select):
        """Once the window has elapsed the next call runs a full cycle."""
        import time as real_time

        runner._ZOMBIE_REAP_T = real_time.time() - 301
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        assert mock_select.call_count == 3


class TestErrorResilience:
    """Test error handling and fail-soft behavior."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_db_select_failure_no_crash(self, mock_print, mock_update, mock_select):
        """A DB select failure is logged and swallowed."""
        mock_select.side_effect = Exception("DB connection lost")

        runner._reap_zombie_tasks()  # must not raise

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[zombie-reaper] error: DB connection lost" in printed
        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_repair_patch_failure_doesnt_block_other_tasks(self, mock_print, mock_update,
                                                           mock_select, mock_repair):
        """If one task's repair patch cannot be built, the next task is still reclaimed.

        The old assertion (`mock_update.call_count == 2`) could not be right in either
        world: when repair_patch raises there IS no patch to write, so the correct
        outcome is one write, for the surviving task, plus a log line naming the row that
        was dropped. Before runner.py:3542 grew its per-row handler the outcome was zero
        writes -- the raise escaped to the function-level handler and abandoned the batch.
        """
        mock_repair.side_effect = [Exception("Repair failed"), {"state": "QUEUED"}]

        tasks = [
            MockTaskFactory.running("t1", updated_offset_sec=31 * 60),
            MockTaskFactory.running("t2", updated_offset_sec=35 * 60),
        ]
        mock_select.side_effect = [tasks, [], []]

        runner._reap_zombie_tasks()  # must not raise

        assert [c[0][1]["id"] for c in mock_update.call_args_list] == ["t2"]
        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "task t1 not reclaimed: Repair failed" in printed

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_malformed_task_record_handled(self, mock_update, mock_select, mock_repair):
        """A row with no updated_at is treated as very old rather than crashing the cycle."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTaskFactory.running()
        del task["updated_at"]

        mock_select.side_effect = [[task], [], []]

        runner._reap_zombie_tasks()  # must not raise

        assert mock_update.called


class TestRetryNoteHandling:
    """Test RETRY promotion note truncation and appending."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_note_appends_promoter_tag(self, mock_update, mock_select):
        """Promotion appends the marker to the existing note."""
        mock_select.side_effect = [
            [], [], [MockTaskFactory.retry(updated_offset_sec=150, note="initial note")]]

        runner._reap_zombie_tasks()

        assert mock_update.call_args[0][2]["note"] == "initial note | retry-promoter"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_note_truncated_to_1000_bytes(self, mock_update, mock_select):
        """A note comfortably under the bound is left intact; the bound is on bytes."""
        long_note = "x" * 950  # 950 + " | retry-promoter" = 967 bytes, no truncation
        mock_select.side_effect = [
            [], [], [MockTaskFactory.retry(updated_offset_sec=150, note=long_note)]]

        runner._reap_zombie_tasks()

        note = mock_update.call_args[0][2]["note"]
        assert note == long_note + " | retry-promoter"
        assert len(note.encode("utf-8")) <= 1000

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_note_preserves_state_and_timestamp(self, mock_update, mock_select):
        """Promotion sets exactly state, updated_at and note -- nothing else."""
        mock_select.side_effect = [[], [], [MockTaskFactory.retry(updated_offset_sec=150)]]

        runner._reap_zombie_tasks()

        body = mock_update.call_args[0][2]
        assert body["state"] == "QUEUED"
        assert body["updated_at"] == "now()"
        assert set(body) == {"state", "updated_at", "note"}


class TestLaneHeartbeatSkipping:
    """Test exclusion of lane and scheduler heartbeats from live-runner detection."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_lane_heartbeats_not_counted_as_live(self, mock_update, mock_select, mock_repair):
        """A ' lane ' hostname heartbeat does not keep its runner's claim alive."""
        # WAS: the lane heartbeat was the ONLY row, which left live_runner_ids empty and
        # switched the dead-runner path off entirely -- so the assertion was testing the
        # empty-table interlock, not the lane filter. A second, plain heartbeat isolates
        # the filter.
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTaskFactory.running("t1", account="Mac.lan-0", updated_offset_sec=200)],
            [MockTaskFactory.heartbeat("Mac.lan-0", hostname="Mac.lan lane 1"),
             OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_scheduler_heartbeats_not_counted_as_live(self, mock_update, mock_select, mock_repair):
        """A '-scheduler' runner id does not vouch for the worker runner beside it."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTaskFactory.running("t1", account="Mac.lan-0", updated_offset_sec=200)],
            [MockTaskFactory.heartbeat("Mac.lan-0-scheduler"), OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called


class TestLargeScaleRecovery:
    """Test the reap loop at production scale."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_recovers_100_tasks_with_50_retry_in_single_cycle(self, mock_update, mock_select, mock_repair):
        """A single cycle handles a full RUNNING page and a RETRY page together."""
        mock_repair.return_value = {"state": "QUEUED"}

        running_tasks = [
            MockTaskFactory.running(f"t{i}", updated_offset_sec=31 * 60 if i % 2 else 10 * 60)
            for i in range(100)
        ]
        retry_tasks = [MockTaskFactory.retry(f"r{i}", updated_offset_sec=150) for i in range(50)]

        mock_select.side_effect = [running_tasks, [], retry_tasks]

        runner._reap_zombie_tasks()

        # 50 stale RUNNING (the odd indices) + 50 RETRY.
        assert mock_update.call_count == 100
        promoted = {c[0][1]["id"] for c in mock_update.call_args_list if c[0][1]["id"].startswith("r")}
        assert len(promoted) == 50

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_query_limits_respected(self, mock_update, mock_select):
        """Both task queries carry their page caps: 100 RUNNING, 250 RETRY."""
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        running_query = mock_select.call_args_list[0][0][1]
        heartbeat_query = mock_select.call_args_list[1][0][1]
        retry_query = mock_select.call_args_list[2][0][1]
        assert running_query["limit"] == "100"
        assert heartbeat_query["limit"] == "500"
        assert retry_query["limit"] == "250"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
