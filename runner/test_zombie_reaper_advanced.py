#!/usr/bin/env python3
"""
test_zombie_reaper_advanced.py - Edge-case and regression tests for the zombie-reaper
reap loop (`runner._reap_zombie_tasks()`).

Scope kept deliberately disjoint from test_zombie_reaper.py, which owns the core
reclaim/promote/skip behaviour. What lives here is the awkward stuff:
  - Timestamp shapes: microseconds, naive (no offset), malformed, empty
  - Note truncation at the 1000-byte boundary
  - The heartbeat filter: ' lane ' hostnames and '-scheduler' runner ids
  - Account pattern matching (Mac.lan-N vs Mandys-MacBook-Pro.local-N)
  - High-volume reclamation at the query limits (100 RUNNING / 250 RETRY)
  - What the reaper can and cannot see about concurrent state changes
  - Malformed environment configuration

This file does not test runner/zombie_reaper.py (a separate module with a separate job);
that is test_zombie_reaper_terminate.py.
"""
import sys
import os
import datetime
from unittest.mock import patch
import pytest

# Appended, never inserted at 0: runner/runner.py at sys.path[0] shadows the runner/
# PACKAGE for the whole session. See the repo-root conftest.py.
_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
if _RUNNER_DIR not in sys.path:
    sys.path.append(_RUNNER_DIR)

import importlib.util  # noqa: E402

# runner.py is loaded by path and NOT registered in sys.modules. Registering it as
# "runner" (what this file used to do) is what made every @patch("runner.db.select") here
# inert: the repo-root conftest rebinds sys.modules["runner"] to the runner PACKAGE at
# each collectstart, so mock.patch imported the package submodule `runner.db` -- a second
# copy of db.py the reaper never calls -- and patched that. patch.object(runner.db, ...)
# binds the module object the code under test actually uses.
_spec = importlib.util.spec_from_file_location(
    "_zombie_reaper_advanced_runner_under_test", os.path.join(_RUNNER_DIR, "runner.py"))
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


@pytest.fixture(autouse=True)
def _reap_cycle_allowed():
    """The reaper self-throttles to one cycle per 300s via the module global
    _ZOMBIE_REAP_T; without this reset only the first test in the file would run a cycle."""
    saved = runner._ZOMBIE_REAP_T
    runner._ZOMBIE_REAP_T = 0.0
    yield
    runner._ZOMBIE_REAP_T = saved


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class MockTask:
    """Extended mock task factory."""

    @staticmethod
    def running(task_id="t1", slug="task-1", account="Mac.lan-0", updated_at_offset_min=0,
                updated_at_iso=None):
        """Create a RUNNING task dict with optional explicit ISO timestamp."""
        if updated_at_iso is None:
            updated_at_iso = (_now() - datetime.timedelta(minutes=updated_at_offset_min)).isoformat()
        return {
            "id": task_id,
            "slug": slug,
            "state": "RUNNING",
            "account": account,
            "updated_at": updated_at_iso,
        }

    @staticmethod
    def heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan", last_seen_iso=None,
                  last_seen_offset_sec=0):
        """Create a runner_heartbeats dict with optional explicit ISO timestamp."""
        if last_seen_iso is None:
            last_seen_iso = (_now() - datetime.timedelta(seconds=last_seen_offset_sec)).isoformat()
        return {
            "runner_id": runner_id,
            "hostname": hostname,
            "last_seen": last_seen_iso,
        }


def OTHER_LIVE_RUNNER():
    """A heartbeat for an unrelated, healthy runner.

    The dead-runner path is gated on `bool(live_runner_ids)`: an empty heartbeat result
    means "no fleet visibility", never "the fleet is dead". Any test about a *specific*
    runner being dead therefore has to leave somebody else alive.
    """
    return MockTask.heartbeat(runner_id="Mac.lan-99", hostname="Mac.lan", last_seen_offset_sec=5)


class TestZombieReaperTimestampPrecision:
    """Test precise timestamp handling and edge cases."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_iso_format_with_microseconds(self, mock_update, mock_select, mock_repair):
        """Microsecond precision in updated_at does not disturb the stale comparison."""
        # WAS: a hard-coded 2026-07-29 literal, i.e. a test that quietly changes meaning
        # as the calendar moves. Anchored to now() instead, with microseconds preserved.
        mock_repair.return_value = {"state": "QUEUED"}
        iso_old = (_now() - datetime.timedelta(minutes=31, microseconds=123456)).isoformat()
        assert "." in iso_old.split("+")[0], "fixture must actually carry microseconds"

        mock_select.side_effect = [[MockTask.running(updated_at_iso=iso_old)], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_naive_iso_timestamp_skips_only_that_row(self, mock_print, mock_update,
                                                     mock_select, mock_repair):
        """A timezone-naive updated_at costs one row, not the whole cycle.

        `common_utils.is_older_than` promises to treat unusable timestamps as very old,
        but a NAIVE datetime parses fine and then raises TypeError when compared against
        the reaper's timezone-aware cutoff. Before runner.py:3542 grew a per-row handler
        that TypeError escaped to the function-level handler and abandoned every
        remaining orphan plus the entire RETRY promotion. Now it is contained: the bad
        row is logged by id and the good row beside it is still reclaimed.
        """
        mock_repair.return_value = {"state": "QUEUED"}
        naive = (datetime.datetime.now() - datetime.timedelta(minutes=31)).isoformat()
        assert "+" not in naive, "fixture must be naive"

        bad = MockTask.running(task_id="naive", updated_at_iso=naive)
        good = MockTask.running(task_id="good", updated_at_offset_min=31)
        mock_select.side_effect = [[bad, good], [], []]

        runner._reap_zombie_tasks()  # must not raise

        assert {c[0][1]["id"] for c in mock_update.call_args_list} == {"good"}
        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "task naive not reclaimed" in printed

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_malformed_iso_timestamp_treated_as_very_old(self, mock_update, mock_select, mock_repair):
        """An unparseable updated_at is treated as very old and reclaimed."""
        # WAS: no assertion, and a comment guessing the opposite ("compares as string <
        # cutoff, likely false"). common_utils.is_older_than returns True when the parse
        # fails -- an unusable timestamp is old by contract, not by string comparison.
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTask.running()
        task["updated_at"] = "not-a-valid-timestamp"

        mock_select.side_effect = [[task], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_empty_updated_at_treated_as_very_old(self, mock_update, mock_select, mock_repair):
        """An empty updated_at is treated as very old and reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTask.running()
        task["updated_at"] = ""

        mock_select.side_effect = [[task], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called


class TestZombieReaperNoteFieldTruncation:
    """Test 1000-byte note truncation on RETRY promotion."""

    @staticmethod
    def _retry(note, seconds_old=150):
        return {
            "id": "t1",
            "note": note,
            "updated_at": (_now() - datetime.timedelta(seconds=seconds_old)).isoformat(),
            "state": "RETRY",
        }

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_note_truncated_at_exactly_1000_bytes(self, mock_update, mock_select):
        """A note that would overflow is cut to 1000 BYTES, not 1000 characters."""
        # 990 x's + " | retry-promoter" = 1007 bytes, so truncation must actually bite.
        mock_select.side_effect = [[], [], [self._retry("x" * 990)]]

        runner._reap_zombie_tasks()

        note = mock_update.call_args[0][2]["note"]
        assert len(note.encode("utf-8")) == 1000
        assert note.startswith("x" * 990 + " | retry")

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_note_preserves_existing_content_before_truncation(self, mock_update, mock_select):
        """The prior note is kept and the marker appended, not the other way round."""
        mock_select.side_effect = [[], [], [self._retry("previous-action-log")]]

        runner._reap_zombie_tasks()

        assert mock_update.call_args[0][2]["note"] == "previous-action-log | retry-promoter"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_note_none_type_coerced_safely(self, mock_update, mock_select):
        """A NULL note yields the marker alone rather than the string 'None'."""
        mock_select.side_effect = [[], [], [self._retry(None)]]

        runner._reap_zombie_tasks()

        note = mock_update.call_args[0][2]["note"]
        assert "None" not in note
        assert note.strip() == "| retry-promoter"


class TestZombieReaperHeartbeatFiltering:
    """Test which heartbeats count as proof that a runner is alive."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_lane_hostname_heartbeat_does_not_keep_a_runner_alive(self, mock_update, mock_select, mock_repair):
        """A heartbeat whose hostname contains ' lane ' is a coder lane, not a runner."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [
                MockTask.heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan machine-learning lane 1"),
                MockTask.heartbeat(runner_id="Mac.lan-1", hostname="Mac.lan"),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        # Mac.lan-0's only heartbeat is a lane heartbeat, so it is not in live_runner_ids
        # and its claim is reclaimed; Mac.lan-1's plain heartbeat is what makes the set
        # non-empty in the first place.
        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_plain_hostname_heartbeat_does_keep_a_runner_alive(self, mock_update, mock_select):
        """Control for the test above: the same task survives a non-lane heartbeat."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [
                MockTask.heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan"),
                MockTask.heartbeat(runner_id="Mac.lan-1", hostname="Mac.lan"),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_scheduler_suffix_runner_id_excluded(self, mock_update, mock_select, mock_repair):
        """A '-scheduler' heartbeat does not vouch for the same-named worker runner."""
        # WAS: the task's own account was "Mac.lan-scheduler", which cannot match the
        # dead-runner account regex (it requires a numeric suffix), so the test could not
        # observe the filter at all. Point it at a real worker id instead.
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [
                MockTask.heartbeat(runner_id="Mac.lan-0-scheduler", hostname="Mac.lan"),
                MockTask.heartbeat(runner_id="Mac.lan-1", hostname="Mac.lan"),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_exclusion_patterns_are_exactly_as_written(self, mock_update, mock_select, mock_repair):
        """Pin the two exclusions precisely, including where they stop.

        The hostname test is a substring match on ' lane ' WITH both spaces, so a hostname
        merely ending in 'lane' is a normal runner and does keep its claim. Getting this
        wrong in either direction is a fleet-wide behaviour change, so both sides are
        asserted here rather than left to a comment.
        """
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [
                MockTask.running(task_id="lane-hb", account="Mac.lan-0", updated_at_offset_min=5),
                MockTask.running(task_id="trailing-lane-hb", account="Mac.lan-1", updated_at_offset_min=5),
                MockTask.running(task_id="sched-hb", account="Mac.lan-3", updated_at_offset_min=5),
                MockTask.running(task_id="plain-hb", account="Mac.lan-2", updated_at_offset_min=5),
            ],
            [
                MockTask.heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan task lane 2"),
                MockTask.heartbeat(runner_id="Mac.lan-1", hostname="Mac.lan queue-processor lane"),
                MockTask.heartbeat(runner_id="Mac.lan-3-scheduler", hostname="Mac.lan"),
                MockTask.heartbeat(runner_id="Mac.lan-2", hostname="Mac.lan"),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        reclaimed = {c[0][1]["id"] for c in mock_update.call_args_list}
        assert reclaimed == {"lane-hb", "sched-hb"}


class TestZombieReaperRunnerIdPatterns:
    """Test runner ID pattern matching for dead-runner detection."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_mac_lan_pattern_exact_match(self, mock_update, mock_select, mock_repair):
        """Account matching Mac.lan-N is eligible for the dead-runner claim."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-5", updated_at_offset_min=5)],
            [MockTask.heartbeat(runner_id="Mac.lan-1", hostname="Mac.lan", last_seen_offset_sec=30)],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_mandys_macbook_pattern_exact_match(self, mock_update, mock_select, mock_repair):
        """Account matching Mandys-MacBook-Pro.local-N is eligible."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mandys-MacBook-Pro.local-0", updated_at_offset_min=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_account_pattern_mismatch_skips_dead_runner_claim(self, mock_update, mock_select):
        """Near-miss account shapes get no dead-runner claim (and are too fresh to be stale)."""
        # WAS: three near-miss accounts, no assertion at all.
        mock_select.side_effect = [
            [
                MockTask.running(task_id="no-suffix", account="Mac.lan", updated_at_offset_min=5),
                MockTask.running(task_id="wrong-sep", account="MacLan-0", updated_at_offset_min=5),
                MockTask.running(task_id="unknown-host", account="localhost-0", updated_at_offset_min=5),
                MockTask.running(task_id="word-suffix", account="Mac.lan-worker", updated_at_offset_min=5),
            ],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_pattern_with_multiple_digits(self, mock_update, mock_select, mock_repair):
        """The numeric suffix is [0-9]+, so double- and triple-digit lanes match."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-123", updated_at_offset_min=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called


class TestZombieReaperHighVolume:
    """Test correctness at the configured query limits."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_handles_100_running_tasks_respecting_limit(self, mock_update, mock_select, mock_repair):
        """A full 100-row RUNNING page is processed in one cycle."""
        mock_repair.return_value = {"state": "QUEUED"}
        stale = (_now() - datetime.timedelta(minutes=31)).isoformat()
        tasks = [
            MockTask.running(task_id=f"t{i}", slug=f"task-{i}", account=f"Mac.lan-{i % 10}",
                             updated_at_iso=stale)
            for i in range(100)
        ]

        mock_select.side_effect = [tasks, [], []]

        runner._reap_zombie_tasks()

        # All 100 are past the stale threshold, so all 100 are reclaimed -- no silent
        # per-page cap beyond the query's own limit=100.
        assert mock_update.call_count == 100
        assert mock_select.call_args_list[0][0][1]["limit"] == "100"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_promotes_250_retry_tasks_respecting_limit(self, mock_update, mock_select):
        """A full 250-row RETRY page is promoted in one cycle."""
        updated = (_now() - datetime.timedelta(seconds=150)).isoformat()
        retry_tasks = [
            {"id": f"r{i}", "note": f"retry-{i}", "updated_at": updated, "state": "RETRY"}
            for i in range(250)
        ]

        mock_select.side_effect = [[], [], retry_tasks]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 250
        assert mock_select.call_args_list[2][0][1]["limit"] == "250"


class TestZombieReaperConcurrencyWindow:
    """Test what the reaper can and cannot observe about concurrent state changes."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_state_is_not_re_read_before_the_write(self, mock_update, mock_select, mock_repair):
        """The reap loop writes on the strength of its own snapshot; it never re-reads.

        Worth pinning because the sibling module runner/zombie_reaper.py deliberately does
        the opposite (it re-reads each row and skips anything no longer RUNNING). The two
        can afford different rules because this loop hands the task to agentic repair --
        recoverable if the worker came back -- while that one writes FAILED, which is not.
        """
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(task_id="t1", updated_at_offset_min=31)],
            [],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        # Exactly three selects: RUNNING, heartbeats, RETRY. No per-task re-read.
        assert [c[0][0] for c in mock_select.call_args_list] == [
            "tasks", "runner_heartbeats", "tasks"]

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_heartbeat_snapshot_is_taken_once_per_cycle(self, mock_update, mock_select, mock_repair):
        """Fleet liveness is sampled once and reused for every task in the batch."""
        # WAS: test_heartbeat_appears_mid_reap, which asserted nothing. The observable
        # consequence of "a heartbeat could appear mid-reap" is precisely that the reaper
        # would not notice -- because it queries heartbeats once, not once per task.
        mock_repair.return_value = {"state": "QUEUED"}
        tasks = [MockTask.running(task_id=f"t{i}", account=f"Mac.lan-{i}", updated_at_offset_min=5)
                 for i in range(5)]

        mock_select.side_effect = [tasks, [OTHER_LIVE_RUNNER()], []]

        runner._reap_zombie_tasks()

        hb_queries = [c for c in mock_select.call_args_list if c[0][0] == "runner_heartbeats"]
        assert len(hb_queries) == 1
        assert mock_update.call_count == 5


class TestZombieReaperRepairIntegration:
    """Test integration details with agentic_repair."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_repair_signal_includes_context_for_dead_runner(self, mock_update, mock_select, mock_repair):
        """Dead-runner reclaim carries the dead-runner signal."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_repair_signal_includes_context_for_stale(self, mock_update, mock_select, mock_repair):
        """Stale reclaim carries the stale signal even while the fleet is healthy."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTask.running(account="unknown", updated_at_offset_min=31)

        mock_select.side_effect = [
            [task],
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_repair_category_and_directive_are_path_independent(self, mock_update, mock_select, mock_repair):
        """Both reclaim paths share one category and one directive; only the signal differs."""
        # Merges the old test_repair_category_always_orphaned_running and
        # test_repair_directive_emphasizes_preservation, which each set up an identical
        # cycle to assert one kwarg. The claim they were both making is that these two
        # kwargs do NOT vary by path, which needs both paths in one cycle to be testable.
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [
                MockTask.running(task_id="dead", account="Mac.lan-0", updated_at_offset_min=5),
                MockTask.running(task_id="stale", account="not-a-runner", updated_at_offset_min=31),
            ],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert len(mock_repair.call_args_list) == 2
        for call_ in mock_repair.call_args_list:
            assert call_[1]["category"] == "orphaned-running"
            directive = call_[1]["directive"]
            assert "Resume the same task from existing branch/worktree/artifacts" in directive
            assert "worker died" in directive


class TestZombieReaperAccounting:
    """Test accurate counting and reporting of actions."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_count_dead_runner_and_stale_together_in_print(self, mock_print, mock_update,
                                                           mock_select, mock_repair):
        """One reclaim count covers both paths -- the print does not split them."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [
                MockTask.running(task_id="dead", account="Mac.lan-0", updated_at_offset_min=5),
                MockTask.running(task_id="stale", account="unknown", updated_at_offset_min=31),
            ],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[zombie-reaper] reclaimed 2 stale RUNNING tasks" in printed

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_failed_write_is_not_counted_as_reclaimed(self, mock_print, mock_update,
                                                      mock_select, mock_repair):
        """The reclaim count reports writes that landed, not rows that were attempted."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(task_id="t1", updated_at_offset_min=31),
             MockTask.running(task_id="t2", updated_at_offset_min=31)],
            [],
            [],
        ]
        mock_update.side_effect = [Exception("write rejected"), None]

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "reclaimed 1 stale RUNNING tasks" in printed
        assert "task t1 not reclaimed: write rejected" in printed

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_no_print_when_no_retries_promoted(self, mock_print, mock_update, mock_select):
        """A quiet cycle stays quiet: no reclaim line and no retry-promoter line."""
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "retry-promoter" not in printed
        assert "reclaimed" not in printed


class TestZombieReaperEnvVarEdgeCases:
    """Test environment variable handling edge cases."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_malformed_grace_period_env_var_aborts_the_cycle_loudly(self, mock_print, mock_update,
                                                                    mock_select):
        """A non-numeric ORCH_DEAD_RUNNER_RECLAIM_GRACE_S does NOT fall back to 180.

        Documented here because the docstrings imply a default and the value is read with
        a bare int(): a typo in the env var takes the whole reap cycle out until it is
        fixed. It fails loudly rather than silently -- the error line names the bad
        literal -- and it cannot wedge the scheduler, which is the property that matters.
        """
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "not-a-number"}):
            mock_select.side_effect = [[MockTask.running(updated_at_offset_min=31)], [], []]

            runner._reap_zombie_tasks()  # must not raise

        mock_update.assert_not_called()
        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[zombie-reaper] error:" in printed
        assert "not-a-number" in printed

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_malformed_ttl_env_var_aborts_the_cycle_loudly(self, mock_print, mock_update, mock_select):
        """Same contract for a non-numeric FLEET_TTL_S."""
        with patch.dict(os.environ, {"FLEET_TTL_S": "bad"}):
            mock_select.side_effect = [[MockTask.running(updated_at_offset_min=31)], [], []]

            runner._reap_zombie_tasks()  # must not raise

        mock_update.assert_not_called()
        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[zombie-reaper] error:" in printed

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_well_formed_grace_period_env_var_is_honoured(self, mock_update, mock_select, mock_repair):
        """Control: a numeric grace period widens the dead-runner window as documented."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTask.running(account="Mac.lan-0",
                                updated_at_iso=(_now() - datetime.timedelta(seconds=240)).isoformat())

        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "600"}):
            mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]
            runner._reap_zombie_tasks()
            mock_update.assert_not_called()   # 240s < 600s grace

        mock_select.reset_mock()
        runner._ZOMBIE_REAP_T = 0.0
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "180"}):
            mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]
            runner._reap_zombie_tasks()
            assert mock_update.called          # 240s > 180s grace


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
