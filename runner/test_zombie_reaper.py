#!/usr/bin/env python3
"""
test_zombie_reaper.py - Core behaviour tests for zombie-reaper task reclamation.

Tests `runner._reap_zombie_tasks()` -- the reap loop that:
  - Reclaims RUNNING tasks whose claiming runner has no live heartbeat
  - Reclaims RUNNING tasks stale for >30min regardless of runner identity
  - Promotes elapsed RETRY tasks back to QUEUED
  - Skips cowork-dispatched tasks (separate execution context)
  - Fails soft: neither a bad row nor a dead DB may wedge the scheduler

NOTE ON SCOPE. This file, and the four other test_zombie_reaper_* suites, test the reap
loop in runner.py. They do NOT test runner/zombie_reaper.py, which is a different thing
with a different job (terminal disposal of ids the caller has already decided are
expired) and is covered by test_zombie_reaper_terminate.py. Nothing in this file imports
that module; the shared name is the only thing they have in common.

Environment variables exercised:
  ORCH_DEAD_RUNNER_RECLAIM_GRACE_S (default: 180s)
  FLEET_TTL_S (default: 180s)
  ORCH_RETRY_PROMOTE_AFTER_S (default: 120s)
"""
import sys
import os
import datetime
from unittest.mock import patch
import pytest

# runner/ must be importable so runner.py's own flat `import db` resolves, but it is
# APPENDED, never inserted at position 0: at sys.path[0] the module file runner/runner.py
# shadows the runner/ PACKAGE and package-style imports break for the rest of the session
# (the repo-root conftest.py documents this at length).
_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
if _RUNNER_DIR not in sys.path:
    sys.path.append(_RUNNER_DIR)

import importlib.util  # noqa: E402

# Load runner/runner.py by path, and deliberately do NOT publish it in sys.modules.
#
# WHY -- this is what made every failing test in this file fail, and made several of the
# "passing" ones meaningless. The file used to do `sys.modules["runner"] = <runner.py>`
# and patch through string targets ("runner.db.select", "runner.agentic_repair.
# repair_patch"). The repo-root conftest rebinds sys.modules["runner"] back to the runner
# PACKAGE at every collectstart, so by the time a test body ran, mock.patch resolved
# "runner.db" by importing the package submodule `runner.db` -- a SECOND copy of db.py
# that the reaper never calls -- and patched select() on that copy. Every mock here was
# installed on a module nobody used: assertions ran while the real db.select() reached for
# Supabase ("[zombie-reaper] error: set SUPABASE_URL and SUPABASE_SERVICE_KEY"), and every
# assert_not_called() passed for the same reason, which is worse than failing.
# patch.object(runner.db, ...) binds the object the code under test actually calls and
# needs no sys.modules entry at all.
_spec = importlib.util.spec_from_file_location(
    "_zombie_reaper_runner_under_test", os.path.join(_RUNNER_DIR, "runner.py"))
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


@pytest.fixture(autouse=True)
def _reap_cycle_allowed():
    """`_reap_zombie_tasks()` self-throttles to one cycle per 300s through the module
    global `_ZOMBIE_REAP_T`. Without this reset, every test after the first in the file
    exercises the early return rather than the reaper."""
    saved = runner._ZOMBIE_REAP_T
    runner._ZOMBIE_REAP_T = 0.0
    yield
    runner._ZOMBIE_REAP_T = saved


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class MockTask:
    """Factory for creating mock task dicts."""

    @staticmethod
    def running(task_id="t1", slug="task-1", account="Mac.lan-0", updated_at_offset_min=0):
        """Create a RUNNING task dict."""
        updated_at = (_now() - datetime.timedelta(minutes=updated_at_offset_min)).isoformat()
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
        updated_at = (_now() - datetime.timedelta(seconds=updated_at_offset_sec)).isoformat()
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
        last_seen = (_now() - datetime.timedelta(seconds=last_seen_offset_sec)).isoformat()
        return {
            "runner_id": runner_id,
            "hostname": hostname,
            "last_seen": last_seen,
        }


def OTHER_LIVE_RUNNER():
    """A heartbeat proving the fleet table is readable and some runner is alive.

    Required by almost every dead-runner test: the reaper only declares a runner dead
    when it has seen at least one live runner (`bool(live_runner_ids)`). An empty result
    means "no fleet visibility", not "the whole fleet died" -- see
    test_empty_heartbeat_table_does_not_mass_reclaim.
    """
    return MockTask.heartbeat(runner_id="Mac.lan-99", hostname="Mac.lan",
                              last_seen_offset_sec=5)


class TestZombieReaperDeadRunnerDetection:
    """Test detection of dead runners via heartbeat expiration."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reclaims_task_with_expired_runner_heartbeat(self, mock_update, mock_select, mock_repair):
        """A claim held by a runner absent from a readable fleet table is reclaimed."""
        # WAS: passed an EMPTY heartbeat list as "the runner died". That is not what an
        # empty list means to the reaper -- see the sibling test below -- so nothing was
        # ever reclaimed and the assertion could only have passed while the db mock was
        # inert. The dead runner has to be absent from a table that still shows somebody.
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],  # RUNNING
            [OTHER_LIVE_RUNNER()],                                            # heartbeats
            [],                                                               # RETRY
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.called
        table, match, patch_body = mock_update.call_args[0]
        assert table == "tasks"
        assert match == {"id": "t1"}
        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_empty_heartbeat_table_does_not_mass_reclaim(self, mock_update, mock_select):
        """No visible heartbeats at all means no fleet visibility, not a dead fleet.

        The `bool(live_runner_ids)` interlock in _reap_zombie_tasks is the only thing
        making the swallowed heartbeat-query error safe: without it, one unavailable
        heartbeat table would reclaim every in-flight claim on the fleet at once.
        """
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [],   # heartbeat table empty / unreadable
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_skips_task_with_live_runner_heartbeat(self, mock_update, mock_select):
        """Task with live runner heartbeat (within TTL) is not reclaimed."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_requires_matching_account_pattern_for_dead_runner_claim(self, mock_update, mock_select):
        """Dead-runner reclaim requires account matching Mac.lan-N / Mandys-MacBook-Pro.local-N."""
        mock_select.side_effect = [
            [MockTask.running(account="unknown-runner-0", updated_at_offset_min=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        # Not a runner-shaped account, so the dead-runner path never applies; at 5 minutes
        # old the 30-minute stale path does not apply either.
        mock_update.assert_not_called()

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_grace_period_for_dead_runner_reclaim(self, mock_update, mock_select):
        """Dead-runner reclaim requires the task to be older than ORCH_DEAD_RUNNER_RECLAIM_GRACE_S."""
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "300"}):
            task = MockTask.running(account="Mac.lan-0")
            task["updated_at"] = (_now() - datetime.timedelta(seconds=200)).isoformat()

            mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]

            runner._reap_zombie_tasks()

            mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reclaims_once_grace_period_elapsed(self, mock_update, mock_select, mock_repair):
        """The same task past ORCH_DEAD_RUNNER_RECLAIM_GRACE_S is reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "300"}):
            task = MockTask.running(account="Mac.lan-0")
            task["updated_at"] = (_now() - datetime.timedelta(seconds=400)).isoformat()

            mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]

            runner._reap_zombie_tasks()

            assert mock_update.called


class TestZombieReaperStaleTaskDetection:
    """Test detection of stale RUNNING tasks (>30min without update)."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reclaims_stale_running_task_exceeding_30_minutes(self, mock_update, mock_select, mock_repair):
        """RUNNING task >30min without update is reclaimed even when its runner is alive."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTask.running(account="unknown-account", updated_at_offset_min=31)

        mock_select.side_effect = [
            [task],
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_skips_recent_running_task_under_30_minutes(self, mock_update, mock_select):
        """RUNNING task <30min old is not reclaimed."""
        mock_select.side_effect = [
            [MockTask.running(account="unknown-account", updated_at_offset_min=15)],
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_boundary_30_minute_threshold(self, mock_update, mock_select, mock_repair):
        """Either side of the 30-minute stale threshold behaves differently.

        Deliberately 29:50 / 30:10 rather than 29:59 / 30:00. The cutoff is computed
        inside the reaper, microseconds AFTER the test builds `updated_at`, so a task
        stamped "exactly 30 minutes old" is always fractionally over the line. A test
        pinned to the exact second asserts the scheduling jitter, not the threshold.
        """
        mock_repair.return_value = {"state": "QUEUED"}

        task_under = MockTask.running(account="unknown")
        task_under["updated_at"] = (_now() - datetime.timedelta(minutes=29, seconds=50)).isoformat()
        mock_select.side_effect = [[task_under], [], []]

        runner._reap_zombie_tasks()
        mock_update.assert_not_called()

        mock_update.reset_mock()
        mock_select.reset_mock()
        mock_repair.reset_mock()
        runner._ZOMBIE_REAP_T = 0.0

        task_over = MockTask.running(account="unknown")
        task_over["updated_at"] = (_now() - datetime.timedelta(minutes=30, seconds=10)).isoformat()
        mock_select.side_effect = [[task_over], [], []]

        runner._reap_zombie_tasks()
        assert mock_update.called


class TestZombieReaperRetryPromotion:
    """Test promotion of elapsed RETRY tasks back to QUEUED."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_promotes_retry_task_exceeding_promote_threshold(self, mock_update, mock_select):
        """RETRY task older than ORCH_RETRY_PROMOTE_AFTER_S is promoted to QUEUED."""
        mock_select.side_effect = [
            [],
            [],
            [MockTask.retry(updated_at_offset_sec=150)],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        table, match, body = mock_update.call_args[0]
        assert table == "tasks"
        assert match == {"id": "t2"}
        assert body["state"] == "QUEUED"
        assert body["updated_at"] == "now()"
        assert "retry-promoter" in body["note"]

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_skips_recent_retry_task(self, mock_update, mock_select):
        """A RETRY row younger than the threshold is filtered out by the query itself."""
        # The age filter lives in the `updated_at: lt.<cutoff>` predicate, so the reaper
        # promotes whatever the query returns. Assert the predicate, which is the part
        # that decides: a 60s-old row is on the wrong side of the default 120s cutoff.
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        retry_query = mock_select.call_args_list[2][0][1]
        assert retry_query["state"] == "eq.RETRY"
        cutoff = retry_query["updated_at"].removeprefix("lt.")
        young = (_now() - datetime.timedelta(seconds=60)).isoformat()
        assert young > cutoff, "a 60s-old RETRY row must not match the promotion cutoff"
        mock_update.assert_not_called()

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_promotion_appends_to_note(self, mock_update, mock_select):
        """Promoting RETRY appends 'retry-promoter' to the existing note, byte-bounded at 1000."""
        existing_note = "x" * 900
        task = MockTask.retry(updated_at_offset_sec=150)
        task["note"] = existing_note

        mock_select.side_effect = [[], [], [task]]

        runner._reap_zombie_tasks()

        body = mock_update.call_args[0][2]
        assert body["note"].startswith(existing_note)
        assert "retry-promoter" in body["note"]
        assert len(body["note"].encode("utf-8")) <= 1000

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_respects_orch_retry_promote_after_s_env_var(self, mock_update, mock_select):
        """ORCH_RETRY_PROMOTE_AFTER_S moves the promotion cutoff."""
        # patch.dict restores the variable even if the assertions blow up, which the
        # previous hand-rolled try/finally only did for the happy path.
        with patch.dict(os.environ, {"ORCH_RETRY_PROMOTE_AFTER_S": "300"}):
            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()
            cutoff_300 = mock_select.call_args_list[2][0][1]["updated_at"].removeprefix("lt.")

            mock_select.reset_mock()
            runner._ZOMBIE_REAP_T = 0.0
            mock_select.side_effect = [[], [], [MockTask.retry(updated_at_offset_sec=310)]]
            runner._reap_zombie_tasks()
            assert mock_update.called

        # A 250s-old row sits inside the widened window; a 310s-old row does not.
        inside = (_now() - datetime.timedelta(seconds=250)).isoformat()
        outside = (_now() - datetime.timedelta(seconds=310)).isoformat()
        assert inside > cutoff_300
        assert outside < cutoff_300


class TestZombieReaperCoworkDispatch:
    """Test skipping cowork-dispatched tasks (separate execution context)."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_skips_cowork_dispatched_tasks(self, mock_update, mock_select):
        """Tasks with account starting 'cowork-' are skipped even when long stale."""
        mock_select.side_effect = [
            [MockTask.running(account="cowork-session-123", updated_at_offset_min=31)],
            [],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_skips_cowork_prefixed_variations(self, mock_update, mock_select):
        """All cowork-* prefixed accounts are skipped."""
        tasks = [
            MockTask.running(task_id="c1", account="cowork-123", updated_at_offset_min=31),
            MockTask.running(task_id="c2", account="cowork-team-456", updated_at_offset_min=31),
            MockTask.running(task_id="c3", account="cowork-adhoc", updated_at_offset_min=31),
        ]
        mock_select.side_effect = [tasks, [], []]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()


class TestZombieReaperMultipleTasks:
    """Test handling multiple tasks in a single reap cycle."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reclaims_multiple_stale_tasks_in_one_cycle(self, mock_update, mock_select, mock_repair):
        """Reaper finds and reclaims multiple stale RUNNING tasks, leaving fresh ones alone."""
        mock_repair.return_value = {"state": "QUEUED"}

        t1 = MockTask.running(task_id="t1", slug="task-1", updated_at_offset_min=31)
        t2 = MockTask.running(task_id="t2", slug="task-2", updated_at_offset_min=40)
        t3 = MockTask.running(task_id="t3", slug="task-3", updated_at_offset_min=15)

        mock_select.side_effect = [[t1, t2, t3], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 2
        updated_ids = {c[0][1]["id"] for c in mock_update.call_args_list}
        assert updated_ids == {"t1", "t2"}

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_promotes_multiple_retry_tasks(self, mock_update, mock_select):
        """Reaper promotes every expired RETRY task in one cycle."""
        mock_select.side_effect = [
            [],
            [],
            [
                MockTask.retry(task_id="r1", slug="retry-1", updated_at_offset_sec=150),
                MockTask.retry(task_id="r2", slug="retry-2", updated_at_offset_sec=200),
            ],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 2
        assert {c[0][1]["id"] for c in mock_update.call_args_list} == {"r1", "r2"}

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_mixes_reclaim_and_promote_in_single_cycle(self, mock_update, mock_select, mock_repair):
        """Reaper reclaims RUNNING and promotes RETRY in the same cycle."""
        mock_repair.return_value = {"state": "QUEUED"}
        t1 = MockTask.running(task_id="t1", updated_at_offset_min=31)

        mock_select.side_effect = [
            [t1],
            [],
            [MockTask.retry(task_id="r1", updated_at_offset_sec=150)],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 2
        bodies = {c[0][1]["id"]: c[0][2] for c in mock_update.call_args_list}
        assert set(bodies) == {"t1", "r1"}
        assert bodies["r1"]["state"] == "QUEUED"


class TestZombieReaperEdgeCases:
    """Test edge cases and error conditions."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_handles_db_select_failure_gracefully(self, mock_update, mock_select):
        """DB select failure is caught, logged, and doesn't wedge the runner."""
        mock_select.side_effect = Exception("DB connection lost")

        runner._reap_zombie_tasks()  # must not raise

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_handles_db_update_failure_gracefully(self, mock_update, mock_select, mock_repair):
        """A failed write for one task does not abandon the rest of the batch.

        This is the rule zombie_reaper.terminate_expired() is built on ("a reaper that
        throws on one bad id would abandon the rest of the batch, which is exactly the
        failure mode that produced the orphan backlog"). The reap loop did not honour it
        until runner.py:3542 grew a per-row handler.
        """
        mock_repair.return_value = {"state": "QUEUED"}

        t1 = MockTask.running(task_id="t1", updated_at_offset_min=31)
        t2 = MockTask.running(task_id="t2", updated_at_offset_min=35)

        mock_select.side_effect = [[t1, t2], [], []]
        mock_update.side_effect = [Exception("DB error"), None]

        runner._reap_zombie_tasks()  # must not raise

        assert mock_update.call_count == 2
        assert {c[0][1]["id"] for c in mock_update.call_args_list} == {"t1", "t2"}

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_promotion_survives_one_failed_write(self, mock_update, mock_select):
        """One RETRY row that cannot be promoted must not strand the rest in limbo."""
        mock_select.side_effect = [
            [],
            [],
            [MockTask.retry(task_id="r1", updated_at_offset_sec=150),
             MockTask.retry(task_id="r2", updated_at_offset_sec=150)],
        ]
        mock_update.side_effect = [Exception("row locked"), None]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 2

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_empty_running_and_retry_lists(self, mock_update, mock_select):
        """Reaper handles empty task lists gracefully and still runs all three queries."""
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        assert mock_select.call_count == 3
        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_missing_updated_at_field_reclaimed_as_very_old(self, mock_update, mock_select, mock_repair):
        """A row with no updated_at is treated as very old and reclaimed as stale."""
        # WAS: test_missing_updated_at_field_defaults_safely, which called the reaper and
        # asserted nothing at all. common_utils.is_older_than documents the real rule --
        # "treating invalid timestamps as very old" -- so it is assertable.
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTask.running(updated_at_offset_min=31)
        del task["updated_at"]

        mock_select.side_effect = [[task], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_missing_account_field_falls_back_to_stale_path(self, mock_update, mock_select, mock_repair):
        """A row with no account can never be dead-runner claimed, only stale-claimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTask.running(updated_at_offset_min=31)
        del task["account"]

        mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_heartbeat_query_failure_falls_back_to_stale_check(self, mock_update, mock_select, mock_repair):
        """If the heartbeat query fails, the stale check still runs (dead-runner does not)."""
        mock_repair.return_value = {"state": "QUEUED"}
        t1 = MockTask.running(task_id="t1", updated_at_offset_min=31)

        mock_select.side_effect = [[t1], Exception("Heartbeat query failed"), []]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"


class TestZombieReaperThrottling:
    """Test reaper throttling (300s cooldown between runs)."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_throttles_calls_300_seconds_apart(self, mock_update, mock_select):
        """Reaper skips execution if called within 300s of its last run."""
        mock_select.side_effect = [[], [], []]
        runner._reap_zombie_tasks()
        assert mock_select.call_count == 3

        mock_select.reset_mock()
        runner._reap_zombie_tasks()
        assert mock_select.call_count == 0


class TestZombieReaperAgenticRepairIntegration:
    """Test integration with agentic_repair module."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_calls_agentic_repair_for_dead_runner_task(self, mock_update, mock_select, mock_repair_patch):
        """Reclaimed task uses agentic_repair.repair_patch() to build the update body."""
        mock_repair_patch.return_value = {"state": "QUEUED", "prompt": "..."}

        task = MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)
        mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]

        runner._reap_zombie_tasks()

        assert mock_repair_patch.called
        args, kwargs = mock_repair_patch.call_args
        assert args[0] is task            # the whole row is handed to the repairer
        assert kwargs["category"] == "orphaned-running"
        assert "worker died" in kwargs["directive"]
        # The patch repair_patch returns is what gets written, verbatim.
        assert mock_update.call_args[0][2] == {"state": "QUEUED", "prompt": "..."}

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_repair_signal_distinguishes_the_two_reclaim_reasons(self, mock_update, mock_select, mock_repair_patch):
        """The positional signal names which of the two reclaim paths fired."""
        # WAS: test_repair_prompt_includes_failure_context, which asserted only the
        # dead-runner string. The signal is the one field that distinguishes the paths,
        # so assert both halves of the distinction in one place.
        mock_repair_patch.return_value = {"state": "QUEUED"}

        dead = MockTask.running(task_id="dead", account="Mac.lan-0", updated_at_offset_min=5)
        stale = MockTask.running(task_id="stale", account="not-a-runner", updated_at_offset_min=31)
        mock_select.side_effect = [[dead, stale], [OTHER_LIVE_RUNNER()], []]

        runner._reap_zombie_tasks()

        signals = {c[0][0]["id"]: c[0][1] for c in mock_repair_patch.call_args_list}
        assert signals["dead"] == "zombie-reaper: expired runner heartbeat"
        assert signals["stale"] == "zombie-reaper: stale RUNNING >30min"


class TestZombieReaperPrintOutput:
    """Test diagnostic print output."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_prints_reclaim_count_on_success(self, mock_print, mock_update, mock_select, mock_repair):
        """Reaper prints the count of reclaimed tasks."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [
                MockTask.running(task_id="t1", updated_at_offset_min=31),
                MockTask.running(task_id="t2", updated_at_offset_min=35),
            ],
            [],
            [],
        ]

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[zombie-reaper] reclaimed 2 stale RUNNING tasks" in printed

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_prints_promote_count_on_success(self, mock_print, mock_update, mock_select):
        """Reaper prints the count of promoted RETRY tasks."""
        mock_select.side_effect = [[], [], [MockTask.retry(updated_at_offset_sec=150)]]

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[retry-promoter] returned 1 elapsed RETRY tasks to QUEUED" in printed

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_prints_error_on_exception(self, mock_print, mock_update, mock_select):
        """Reaper prints a diagnosable error message on an unexpected exception."""
        mock_select.side_effect = Exception("DB failure")

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[zombie-reaper] error: DB failure" in printed


class TestZombieReaperDbQuery:
    """Test database query structure and parameters."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_running_query_selects_correct_fields(self, mock_update, mock_select):
        """RUNNING query requests id, slug, updated_at, account and caps at 100 rows."""
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        table, query = mock_select.call_args_list[0][0]
        assert table == "tasks"
        assert set(query["select"].split(",")) == {"id", "slug", "updated_at", "account"}
        assert query["state"] == "eq.RUNNING"
        assert query["limit"] == "100"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_heartbeat_query_filters_by_recency(self, mock_update, mock_select):
        """Heartbeat query asks only for heartbeats newer than the FLEET_TTL_S cutoff."""
        # WAS: guarded by `if heartbeat_calls:`, so it asserted nothing whenever the query
        # was absent -- which, with the mock inert, was always.
        with patch.dict(os.environ, {"FLEET_TTL_S": "180"}):
            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()

        table, query = mock_select.call_args_list[1][0]
        assert table == "runner_heartbeats"
        assert query["last_seen"].startswith("gte.")
        assert query["order"] == "last_seen.desc"
        cutoff = query["last_seen"].removeprefix("gte.")
        fresh = (_now() - datetime.timedelta(seconds=30)).isoformat()
        old = (_now() - datetime.timedelta(seconds=300)).isoformat()
        assert fresh > cutoff and old < cutoff

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_query_selects_correct_fields(self, mock_update, mock_select):
        """RETRY query requests id, note, updated_at and caps at 250 rows."""
        # WAS: indexed call_args_list[1] -- the heartbeat query. RETRY is the THIRD select.
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        table, query = mock_select.call_args_list[2][0]
        assert table == "tasks"
        assert set(query["select"].split(",")) == {"id", "note", "updated_at"}
        assert query["state"] == "eq.RETRY"
        assert query["limit"] == "250"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
