#!/usr/bin/env python3
"""
test_zombie_reaper_complete.py - End-to-end tests for the zombie-reaper reap loop
(`runner._reap_zombie_tasks()`).

Task: backlog-batch-illuminati-1d1b027
Failure Category: orphaned-running (expired runner heartbeat)

What this file owns that its siblings do not is the JOIN: the reap loop's notion of "that
runner is alive" is only as good as the row `db.heartbeat()` publishes, and nothing else
in the cluster tests the two halves against each other. runner_heartbeats sat empty for
weeks in 2026-07 because the publisher wrote a schema the table did not have, and the
consumer -- this reap loop -- has no way to tell an empty table from a dead fleet. The
first class below drives the real publisher and feeds its real output to the real
consumer. (Publisher-side field shape is owned by test_zombie_reaper_heartbeat.py; this
file asserts only the handshake between them.)

The rest covers detection, promotion, resilience and diagnostics end to end.
Not a test of runner/zombie_reaper.py -- see test_zombie_reaper_terminate.py.
"""

import sys
import os
import datetime
import threading
from unittest.mock import patch
import pytest

# Appended, never inserted at 0: runner/runner.py at sys.path[0] shadows the runner/
# PACKAGE for the whole session (see the repo-root conftest.py).
_RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER_DIR not in sys.path:
    sys.path.append(_RUNNER_DIR)

import importlib.util  # noqa: E402

# Loaded by path and NOT registered in sys.modules. Publishing it as "runner" -- what this
# file used to do -- is what made every @patch("runner.db.select") here inert: the
# repo-root conftest rebinds sys.modules["runner"] to the runner PACKAGE at collectstart,
# so mock.patch resolved "runner.db" to the package submodule (a second copy of db.py the
# reaper never calls) and patched select() there, while the code under test kept talking
# to the real database.
_spec = importlib.util.spec_from_file_location(
    "_zombie_reaper_complete_runner_under_test", os.path.join(_RUNNER_DIR, "runner.py"))
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


@pytest.fixture(autouse=True)
def _reap_cycle_allowed():
    """The reaper self-throttles to one cycle per 300s through _ZOMBIE_REAP_T."""
    saved = runner._ZOMBIE_REAP_T
    runner._ZOMBIE_REAP_T = 0.0
    yield
    runner._ZOMBIE_REAP_T = saved


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class HeartbeatRecordFactory:
    """Factory for heartbeat rows shaped like the live runner_heartbeats schema.

    Only the three columns the reap loop reads. There is no `active` column -- that shape
    is the one that made every insert fail in 2026-07 (db.py:2642-2648), and carrying it
    in a fixture here would quietly re-document the bug.
    """

    @staticmethod
    def fresh(runner_id="Mac.lan-0", hostname="Mac.lan", seconds_ago=30):
        return {
            "runner_id": runner_id,
            "hostname": hostname,
            "last_seen": (_now() - datetime.timedelta(seconds=seconds_ago)).isoformat(),
        }


def OTHER_LIVE_RUNNER():
    """A heartbeat for an unrelated healthy runner.

    Required by every dead-runner test: the reaper only declares a runner dead when it has
    seen at least one live one (`bool(live_runner_ids)`), because an empty heartbeat result
    means "no fleet visibility", not "the fleet died".
    """
    return HeartbeatRecordFactory.fresh(runner_id="Mac.lan-99", seconds_ago=5)


class TaskRecordFactory:
    """Factory for creating task records matching DB schema."""

    @staticmethod
    def running(task_id="t1", slug="task-1", account="Mac.lan-0", minutes_old=0, state="RUNNING"):
        return {
            "id": task_id,
            "slug": slug,
            "state": state,
            "account": account,
            "updated_at": (_now() - datetime.timedelta(minutes=minutes_old)).isoformat(),
        }

    @staticmethod
    def retry(task_id="r1", slug="retry-1", seconds_old=0, note=""):
        return {
            "id": task_id,
            "slug": slug,
            "state": "RETRY",
            "updated_at": (_now() - datetime.timedelta(seconds=seconds_old)).isoformat(),
            "note": note,
        }


class TestPublisherConsumerHandshake:
    """Test the row db.heartbeat() writes against the row the reap loop reads."""

    @staticmethod
    def _published_row(runner_id="Mac.lan-0", hostname="Mac.lan"):
        """Run the real publisher and return the row it hands to the database."""
        with patch.object(runner.db, "db") as mock_client, \
             patch.object(runner.db, "_prune_stale_heartbeats", lambda *a, **k: None):
            mock_client.insert.return_value = None
            runner.db.heartbeat(runner_id, hostname, active=True)
            return dict(mock_client.insert.call_args[0][1])

    def test_published_row_carries_every_column_the_reaper_queries(self):
        """The publisher's row supplies exactly the columns the reaper's query names.

        WAS: five tests that computed `now - 179 < 180` and friends -- arithmetic on local
        variables that never touched db or runner at all, and could not fail. The real
        question they were gesturing at is whether the two halves of the heartbeat
        contract agree on field names, which is answerable and has been wrong before.
        """
        row = self._published_row()

        with patch.object(runner.db, "select") as mock_select, \
             patch.object(runner.db, "update"):
            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()
        requested = mock_select.call_args_list[1][0][1]["select"].split(",")

        assert set(requested) == {"runner_id", "hostname", "last_seen"}
        for column in requested:
            assert column in row, f"db.heartbeat() never publishes {column}"

    def test_last_seen_is_an_iso_string_the_cutoff_can_be_compared_against(self):
        """last_seen must be ISO text: the reaper filters it with `gte.<iso>`.

        An epoch float -- the shape the publisher used to write -- would compare against
        the cutoff as a string and match essentially at random.
        """
        row = self._published_row()

        assert isinstance(row["last_seen"], str)
        parsed = datetime.datetime.fromisoformat(row["last_seen"])
        assert parsed.tzinfo is not None
        assert abs((_now() - parsed).total_seconds()) < 60

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_published_heartbeat_keeps_its_runners_claim(self, mock_update, mock_select):
        """A runner that just published is live to the reaper, and keeps its RUNNING task."""
        row = self._published_row(runner_id="Mac.lan-0", hostname="Mac.lan")

        mock_select.side_effect = [
            [TaskRecordFactory.running(account="Mac.lan-0", minutes_old=5)],
            [row],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_runner_that_stopped_publishing_loses_its_claim(self, mock_update, mock_select, mock_repair):
        """The same task is reclaimed once that runner's row stops coming back."""
        mock_repair.return_value = {"state": "QUEUED"}
        other = self._published_row(runner_id="Mac.lan-99", hostname="Mac.lan")

        mock_select.side_effect = [
            [TaskRecordFactory.running(account="Mac.lan-0", minutes_old=5)],
            [other],   # Mac.lan-0 is simply absent now
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"


class TestDeadRunnerDetection:
    """Test detection of dead runners via expired heartbeats."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_detects_task_with_no_heartbeat(self, mock_update, mock_select, mock_repair):
        """A runner-shaped account absent from a readable fleet table is reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [TaskRecordFactory.running(account="Mac.lan-0", minutes_old=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.called

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_ignores_task_with_live_heartbeat(self, mock_update, mock_select):
        """Task whose runner has a recent heartbeat is not reclaimed."""
        mock_select.side_effect = [
            [TaskRecordFactory.running(account="Mac.lan-0", minutes_old=5)],
            [HeartbeatRecordFactory.fresh(runner_id="Mac.lan-0", seconds_ago=30)],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_expired_heartbeat_is_filtered_by_the_query_not_by_the_loop(self, mock_update, mock_select):
        """Expiry lives in the `last_seen: gte.<cutoff>` predicate, not in Python.

        WAS: handed the reaper a two-hour-old heartbeat row and expected a reclaim. The
        loop does no client-side age check at all, so that row would have kept the runner
        alive; the row simply never comes back from a real query. Assert the cutoff.
        """
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        cutoff = mock_select.call_args_list[1][0][1]["last_seen"].removeprefix("gte.")
        two_hours_ago = (_now() - datetime.timedelta(seconds=7200)).isoformat()
        assert two_hours_ago < cutoff, "a 2h-old heartbeat must fall outside the TTL window"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_account_pattern_matching_for_runner_identity(self, mock_update, mock_select):
        """An account that is not runner-shaped can never take the dead-runner path."""
        mock_select.side_effect = [
            [TaskRecordFactory.running(account="unknown-runner", minutes_old=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_grace_period_prevents_early_reclaim(self, mock_update, mock_select, mock_repair):
        """A dead runner's freshly-touched task is left alone until the grace period ends."""
        mock_repair.return_value = {"state": "QUEUED"}
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "300"}):
            mock_select.side_effect = [
                [TaskRecordFactory.running(account="Mac.lan-0", minutes_old=1)],
                [OTHER_LIVE_RUNNER()],
                [],
            ]

            runner._reap_zombie_tasks()

            mock_update.assert_not_called()


class TestStaleTaskDetection:
    """Test detection and reclamation of stale RUNNING tasks."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reclaims_task_over_30_minute_threshold(self, mock_update, mock_select, mock_repair):
        """A RUNNING task >30min old is reclaimed even while its runner is alive."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [TaskRecordFactory.running(account="unknown-runner", minutes_old=31)],
            [HeartbeatRecordFactory.fresh()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_ignores_task_under_30_minute_threshold(self, mock_update, mock_select):
        """A RUNNING task <30min old is not reclaimed."""
        mock_select.side_effect = [
            [TaskRecordFactory.running(account="unknown-runner", minutes_old=15)],
            [HeartbeatRecordFactory.fresh()],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_boundary_just_under_30_minutes(self, mock_update, mock_select, mock_repair):
        """29:50 stays; the threshold is not applied early."""
        # WAS: test_boundary_at_exactly_30_minutes, asserting that a task stamped exactly
        # 30:00 old is NOT reclaimed. It always is: the reaper computes its cutoff
        # microseconds AFTER the fixture computes updated_at, so "exactly 30 minutes" is
        # unavoidably a hair over the line. The test was asserting scheduling jitter.
        mock_repair.return_value = {"state": "QUEUED"}
        task = TaskRecordFactory.running(account="unknown")
        task["updated_at"] = (_now() - datetime.timedelta(minutes=29, seconds=50)).isoformat()

        mock_select.side_effect = [[task], [], []]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_boundary_just_over_30_minutes(self, mock_update, mock_select, mock_repair):
        """30:10 goes."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = TaskRecordFactory.running(account="unknown")
        task["updated_at"] = (_now() - datetime.timedelta(minutes=30, seconds=10)).isoformat()

        mock_select.side_effect = [[task], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called


class TestRetryTaskPromotion:
    """Test promotion of elapsed RETRY tasks back to QUEUED."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_promotes_retry_task_over_threshold(self, mock_update, mock_select):
        """An elapsed RETRY row is written back to QUEUED."""
        mock_select.side_effect = [[], [], [TaskRecordFactory.retry(seconds_old=150)]]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_update.call_args[0][2]["state"] == "QUEUED"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_age_filter_for_retry_lives_in_the_query(self, mock_update, mock_select):
        """A RETRY row under the threshold is excluded by the predicate, not by the loop.

        WAS: test_ignores_recent_retry_task, which returned a 60s-old row from a mocked
        select and asserted it was not promoted. The loop promotes every row it is given;
        the age test is `updated_at: lt.<cutoff>` in the query.
        """
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        cutoff = mock_select.call_args_list[2][0][1]["updated_at"].removeprefix("lt.")
        assert (_now() - datetime.timedelta(seconds=60)).isoformat() > cutoff
        assert (_now() - datetime.timedelta(seconds=150)).isoformat() < cutoff
        mock_update.assert_not_called()

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_promotion_respects_env_var(self, mock_update, mock_select):
        """ORCH_RETRY_PROMOTE_AFTER_S moves the promotion cutoff."""
        with patch.dict(os.environ, {"ORCH_RETRY_PROMOTE_AFTER_S": "300"}):
            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()

        cutoff = mock_select.call_args_list[2][0][1]["updated_at"].removeprefix("lt.")
        assert (_now() - datetime.timedelta(seconds=250)).isoformat() > cutoff
        assert (_now() - datetime.timedelta(seconds=350)).isoformat() < cutoff

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_promotion_appends_to_existing_note(self, mock_update, mock_select):
        """Promotion preserves the existing note and appends the marker, byte-bounded."""
        task = TaskRecordFactory.retry(seconds_old=150)
        task["note"] = "x" * 900

        mock_select.side_effect = [[], [], [task]]

        runner._reap_zombie_tasks()

        note = mock_update.call_args[0][2]["note"]
        assert note == "x" * 900 + " | retry-promoter"
        assert len(note.encode("utf-8")) <= 1000


class TestCoworkTaskHandling:
    """Test proper handling of cowork-dispatched tasks."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_skips_cowork_prefixed_tasks(self, mock_update, mock_select):
        """Tasks with a cowork-* account are skipped."""
        mock_select.side_effect = [
            [TaskRecordFactory.running(account="cowork-session-123", minutes_old=31)], [], []]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_skips_all_cowork_variations(self, mock_update, mock_select):
        """Every cowork-* prefixed account is skipped."""
        mock_select.side_effect = [
            [
                TaskRecordFactory.running(task_id="c1", account="cowork-123", minutes_old=31),
                TaskRecordFactory.running(task_id="c2", account="cowork-team-456", minutes_old=31),
                TaskRecordFactory.running(task_id="c3", account="cowork-adhoc-789", minutes_old=31),
            ],
            [],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()


class TestAgenticRepairIntegration:
    """Test integration with agentic repair for recovery."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_calls_repair_patch_for_dead_runner(self, mock_update, mock_select, mock_repair):
        """A dead runner's task is routed through agentic_repair.repair_patch()."""
        # WAS: asserted "expired runner heartbeat" in the DIRECTIVE kwarg. The directive
        # is one fixed string shared by both reclaim paths and has never contained it;
        # the positional signal is the field that names the path.
        mock_repair.return_value = {"state": "QUEUED", "prompt": "..."}
        task = TaskRecordFactory.running(account="Mac.lan-0", minutes_old=5)

        mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]

        runner._reap_zombie_tasks()

        assert mock_repair.called
        assert mock_repair.call_args[0][0] is task
        assert mock_repair.call_args[1]["category"] == "orphaned-running"
        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_repair_signal_names_the_reaper(self, mock_update, mock_select, mock_repair):
        """The signal is prefixed 'zombie-reaper:' so the origin survives into the note."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [TaskRecordFactory.running(account="Mac.lan-0", minutes_old=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.call_args[0][1].startswith("zombie-reaper: ")


class TestErrorResilience:
    """Test graceful error handling."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_handles_select_failure(self, mock_update, mock_select):
        """A DB select failure does not crash the runner and writes nothing."""
        mock_select.side_effect = Exception("DB connection lost")

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_continues_after_update_failure(self, mock_update, mock_select, mock_repair):
        """A failed write for one task does not abandon the rest of the batch.

        Pinned by runner.py:3542 (per-row handler). Before it, the first raise escaped to
        the function-level handler and took every remaining orphan -- and the whole RETRY
        promotion below it -- down with it.
        """
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [TaskRecordFactory.running(task_id="t1", minutes_old=31),
             TaskRecordFactory.running(task_id="t2", minutes_old=35)],
            [],
            [],
        ]
        mock_update.side_effect = [Exception("DB error"), None]

        runner._reap_zombie_tasks()

        assert [c[0][1]["id"] for c in mock_update.call_args_list] == ["t1", "t2"]

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reclaim_failure_does_not_stop_retry_promotion(self, mock_update, mock_select, mock_repair):
        """The RETRY promoter still runs after a RUNNING row fails to reclaim.

        The two halves share one cycle, so before per-row isolation a single unwritable
        orphan left every elapsed RETRY task in the limbo the promoter exists to drain.
        """
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [TaskRecordFactory.running(task_id="t1", minutes_old=31)],
            [],
            [TaskRecordFactory.retry(task_id="r1", seconds_old=150)],
        ]
        mock_update.side_effect = [Exception("DB error"), None]

        runner._reap_zombie_tasks()

        assert [c[0][1]["id"] for c in mock_update.call_args_list] == ["t1", "r1"]

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_handles_missing_updated_at_field(self, mock_update, mock_select, mock_repair):
        """A row with no updated_at is treated as very old, not as a crash."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = TaskRecordFactory.running(minutes_old=31)
        del task["updated_at"]

        mock_select.side_effect = [[task], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_handles_missing_account_field(self, mock_update, mock_select, mock_repair):
        """A row with no account is stale-reclaimed, never dead-runner-reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = TaskRecordFactory.running(minutes_old=31)
        del task["account"]

        mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]

        runner._reap_zombie_tasks()

        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"


class TestMultipleTaskHandling:
    """Test reaper processing multiple tasks in one cycle."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_processes_multiple_stale_tasks(self, mock_update, mock_select, mock_repair):
        """Multiple stale tasks in one cycle; the fresh one is left alone."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [TaskRecordFactory.running(task_id="t1", minutes_old=31),
             TaskRecordFactory.running(task_id="t2", minutes_old=40),
             TaskRecordFactory.running(task_id="t3", minutes_old=15)],
            [],
            [],
        ]

        runner._reap_zombie_tasks()

        assert {c[0][1]["id"] for c in mock_update.call_args_list} == {"t1", "t2"}

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_processes_multiple_retry_tasks(self, mock_update, mock_select):
        """Every elapsed RETRY row in the page is promoted."""
        mock_select.side_effect = [
            [], [],
            [TaskRecordFactory.retry(task_id="r1", seconds_old=150),
             TaskRecordFactory.retry(task_id="r2", seconds_old=200)],
        ]

        runner._reap_zombie_tasks()

        assert {c[0][1]["id"] for c in mock_update.call_args_list} == {"r1", "r2"}

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_mixes_reclaim_and_promote_in_cycle(self, mock_update, mock_select, mock_repair):
        """Reclaim and promotion happen in the same cycle, in that order."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [TaskRecordFactory.running(task_id="t1", minutes_old=31)],
            [],
            [TaskRecordFactory.retry(task_id="r1", seconds_old=150)],
        ]

        runner._reap_zombie_tasks()

        assert [c[0][1]["id"] for c in mock_update.call_args_list] == ["t1", "r1"]


class TestThrottling:
    """Test reaper throttling and rate limiting."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_throttles_300_seconds_apart(self, mock_update, mock_select):
        """A second call inside the window issues no queries."""
        mock_select.side_effect = [[], [], []]
        runner._reap_zombie_tasks()
        assert mock_select.call_count == 3

        mock_select.reset_mock()
        runner._reap_zombie_tasks()
        assert mock_select.call_count == 0


class TestDatabaseQueryStructure:
    """Test database query correctness."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_running_query_structure(self, mock_update, mock_select):
        """RUNNING query: four columns, state filter, 100-row cap."""
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        table, query = mock_select.call_args_list[0][0]
        assert table == "tasks"
        assert set(query["select"].split(",")) == {"id", "slug", "updated_at", "account"}
        assert query["state"] == "eq.RUNNING"
        assert query["limit"] == "100"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_query_structure(self, mock_update, mock_select):
        """RETRY query: three columns, state filter, age predicate, 250-row cap."""
        # WAS: `calls = [c for c in ... if "RETRY" in str(c)]` then `if calls:` -- so when
        # the query was absent (which, with the mock inert, was always) it asserted
        # nothing. The RETRY query is unconditionally the third select.
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        table, query = mock_select.call_args_list[2][0]
        assert table == "tasks"
        assert set(query["select"].split(",")) == {"id", "note", "updated_at"}
        assert query["state"] == "eq.RETRY"
        assert query["updated_at"].startswith("lt.")
        assert query["limit"] == "250"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_empty_task_and_heartbeat_lists(self, mock_update, mock_select):
        """An entirely empty cycle still runs all three queries and writes nothing."""
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        assert mock_select.call_count == 3
        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_heartbeat_query_exception_falls_back(self, mock_update, mock_select, mock_repair):
        """A failed heartbeat query degrades to stale-only reclamation."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [TaskRecordFactory.running(task_id="t1", minutes_old=31)],
            Exception("Heartbeat query failed"),
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_duplicate_runner_id_rows_collapse_to_one_live_runner(self, mock_update, mock_select):
        """Two rows for one runner_id (PID reuse, a late upsert) still mean "alive".

        WAS: test_pid_reuse_scenario, which built two dicts and asserted that the
        runner_id it had just written into both was equal to itself. live_runner_ids is a
        set comprehension, so the real, checkable consequence is that a duplicated id
        cannot double-count or shadow itself -- the claim is kept either way.
        """
        mock_select.side_effect = [
            [TaskRecordFactory.running(account="Mac.lan-0", minutes_old=5)],
            [HeartbeatRecordFactory.fresh(runner_id="Mac.lan-0", seconds_ago=170),
             HeartbeatRecordFactory.fresh(runner_id="Mac.lan-0", seconds_ago=5)],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_future_dated_updated_at_is_never_reclaimed(self, mock_update, mock_select):
        """Clock skew that puts updated_at in the future reads as "very recent", not stale.

        WAS: test_clock_skew_handling, which defined a local `is_reasonable()` helper and
        asserted things about that helper. The reaper has no skew defence; the honest
        statement of its behaviour is that a future timestamp fails both age tests, so a
        skewed host loses reclamation rather than gaining spurious reclaims.
        """
        task = TaskRecordFactory.running(account="Mac.lan-0")
        task["updated_at"] = (_now() + datetime.timedelta(hours=1)).isoformat()

        mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()


class TestPrintDiagnostics:
    """Test diagnostic output."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_prints_reclaim_summary(self, mock_print, mock_update, mock_select, mock_repair):
        """The reaper prints how many tasks it reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [TaskRecordFactory.running(task_id="t1", minutes_old=31),
             TaskRecordFactory.running(task_id="t2", minutes_old=35)],
            [],
            [],
        ]

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[zombie-reaper] reclaimed 2 stale RUNNING tasks" in printed

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_prints_error_on_failure(self, mock_print, mock_update, mock_select):
        """The reaper prints a diagnosable error line on an unexpected exception."""
        mock_select.side_effect = Exception("DB failure")

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[zombie-reaper] error: DB failure" in printed


class TestConcurrentAccess:
    """Test behaviour when several threads reach the reaper at once."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_concurrent_reaper_calls(self, mock_update, mock_select):
        """Concurrent calls are safe, and the throttle closes behind them.

        WAS: `assert call_count[0] >= 0`, true of every possible outcome. An exact query
        count is genuinely untestable here -- the throttle's check-and-set is not atomic,
        so two threads can both pass it -- but two things are: no call may raise, and
        after the burst the window must be shut, which is what the scheduler relies on.
        """
        mock_select.side_effect = lambda *a, **k: []
        errors = []

        def worker():
            try:
                runner._reap_zombie_tasks()
            except Exception as e:  # pragma: no cover - the assertion below reports it
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert mock_select.call_count >= 3, "at least one full cycle must have run"

        mock_select.reset_mock()
        runner._reap_zombie_tasks()
        assert mock_select.call_count == 0, "the throttle window must be closed afterwards"
        mock_update.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
