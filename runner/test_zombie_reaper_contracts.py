#!/usr/bin/env python3
"""
test_zombie_reaper_contracts.py - Contract tests for the zombie-reaper reap loop
(`runner._reap_zombie_tasks()`), for
dropbox-smarter-one-os-reconfiguration-partner-level-capability-for--contracts.

What "contract" means here, corrected. The reap loop has no partner-level awareness of
any kind: it reads four columns (id, slug, updated_at, account), and there is no
ORCH_PARTNER_CONTRACT_ENABLED or ORCH_DROPBOX_RECONFIG_ENABLED anywhere in the product --
the previous version of this docstring listed both as "environment variables tested".
The contract this file can actually hold the reaper to is the one it really offers to a
partner-level caller:

  - which rows it will and will not touch, under every configuration knob it has
  - that per-task metadata it does not understand is neither read nor destroyed
  - that the whole row travels intact to agentic_repair, so a downstream consumer that
    DOES understand contract metadata still sees it
  - that no single row, and no single failed write, can take the cycle down

Environment variables that genuinely participate:
  ORCH_DEAD_RUNNER_RECLAIM_GRACE_S (default: 180s)
  FLEET_TTL_S (default: 180s)
  ORCH_RETRY_PROMOTE_AFTER_S (default: 120s)

Not to be confused with runner/zombie_reaper.py (terminal disposal of already-expired
ids), which is covered by test_zombie_reaper_terminate.py.
"""
import sys
import os
import time
import datetime
from unittest.mock import patch
import pytest

# Appended, never inserted at 0 -- runner/runner.py at sys.path[0] shadows the runner/
# PACKAGE for the rest of the session (see the repo-root conftest.py).
_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
if _RUNNER_DIR not in sys.path:
    sys.path.append(_RUNNER_DIR)

import importlib.util  # noqa: E402

# Loaded by path and NOT registered in sys.modules. Publishing it as "runner" (what this
# file used to do) made every @patch("runner.db.select") here inert: the repo-root
# conftest rebinds sys.modules["runner"] to the runner PACKAGE at collectstart, so
# mock.patch resolved "runner.db" to the package submodule -- a second copy of db.py that
# the reaper never calls.
_spec = importlib.util.spec_from_file_location(
    "_zombie_reaper_contracts_runner_under_test", os.path.join(_RUNNER_DIR, "runner.py"))
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


class MockTask:
    """Factory for creating mock task dicts with contract metadata."""

    @staticmethod
    def running(task_id="t1", slug="task-1", account="Mac.lan-0", updated_at_offset_min=0,
                updated_at_iso=None, contract_id=None, partner_level=None):
        """Create a RUNNING task dict with optional contract metadata."""
        if updated_at_iso is None:
            updated_at_iso = (_now() - datetime.timedelta(minutes=updated_at_offset_min)).isoformat()

        task = {
            "id": task_id,
            "slug": slug,
            "state": "RUNNING",
            "account": account,
            "updated_at": updated_at_iso,
        }
        if contract_id:
            task["contract_id"] = contract_id
        if partner_level:
            task["partner_level"] = partner_level
        return task

    @staticmethod
    def retry(task_id="t2", slug="task-2", updated_at_offset_sec=0, note="", contract_id=None):
        """Create a RETRY task dict."""
        task = {
            "id": task_id,
            "slug": slug,
            "state": "RETRY",
            "updated_at": (_now() - datetime.timedelta(seconds=updated_at_offset_sec)).isoformat(),
            "note": note or "initial note",
        }
        if contract_id:
            task["contract_id"] = contract_id
        return task

    @staticmethod
    def heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan", last_seen_offset_sec=0,
                  last_seen_iso=None):
        """Create a runner_heartbeats dict."""
        if last_seen_iso is None:
            last_seen_iso = (_now() - datetime.timedelta(seconds=last_seen_offset_sec)).isoformat()
        return {"runner_id": runner_id, "hostname": hostname, "last_seen": last_seen_iso}


def OTHER_LIVE_RUNNER():
    """A heartbeat for an unrelated healthy runner.

    The dead-runner path is gated on `bool(live_runner_ids)`, so a test about one runner
    being dead has to leave another one alive; an empty heartbeat result means "no fleet
    visibility" and deliberately reclaims nothing.
    """
    return MockTask.heartbeat(runner_id="Mac.lan-99", hostname="Mac.lan", last_seen_offset_sec=5)


class TestHeartbeatMonitoringBasics:
    """Test basic heartbeat monitoring and TTL enforcement."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_task_with_live_heartbeat_not_reclaimed(self, mock_update, mock_select, mock_repair):
        """Task with a live runner heartbeat is not reclaimed."""
        # Duplicate of test_zombie_reaper.py::test_skips_task_with_live_runner_heartbeat.
        # Kept as the negative control this file's dead-runner tests are read against;
        # proposed single owner is test_zombie_reaper.py (see report).
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],
            [],
        ]

        runner._reap_zombie_tasks()

        assert not mock_update.called

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_task_with_dead_runner_heartbeat_reclaimed(self, mock_update, mock_select, mock_repair):
        """Task whose runner is missing from a readable fleet table is reclaimed."""
        # WAS: an empty heartbeat list, which the reaper reads as "no fleet visibility"
        # and deliberately does not act on.
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.called

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_heartbeat_expiry_is_enforced_by_the_query_not_in_python(self, mock_update, mock_select):
        """FLEET_TTL_S sets a `last_seen: gte.<cutoff>` predicate; nothing re-checks age.

        This is the load-bearing detail behind every heartbeat test in the cluster: rows
        that come back are trusted as live, unconditionally. Handing the reaper a
        two-hour-old heartbeat row therefore proves nothing about expiry -- only the
        cutoff it asks the database for does.
        """
        with patch.dict(os.environ, {"FLEET_TTL_S": "600"}):
            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()

        query = mock_select.call_args_list[1][0][1]
        cutoff = query["last_seen"].removeprefix("gte.")
        assert query["last_seen"].startswith("gte.")
        within_ttl = (_now() - datetime.timedelta(seconds=300)).isoformat()
        beyond_ttl = (_now() - datetime.timedelta(seconds=900)).isoformat()
        assert within_ttl > cutoff
        assert beyond_ttl < cutoff

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_stale_row_returned_by_the_query_is_still_trusted(self, mock_update, mock_select):
        """Corollary: an over-age row that the query somehow returns keeps its runner alive."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=7200)],
            [],
        ]

        runner._reap_zombie_tasks()

        mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_scheduler_heartbeat_excluded_from_live_runner_ids(self, mock_update, mock_select, mock_repair):
        """A '-scheduler' heartbeat does not vouch for the worker runner of the same name."""
        # WAS: the task's account was "Mac.lan-scheduler", which cannot match the
        # dead-runner regex at all, so the filter under test was unreachable.
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [MockTask.heartbeat(runner_id="Mac.lan-0-scheduler", hostname="Mac.lan"),
             OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_lane_heartbeat_excluded_from_live_runner_ids(self, mock_update, mock_select, mock_repair):
        """A ' lane ' hostname is a coder lane, not a runner, and does not keep a claim alive."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [MockTask.heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan task lane 1",
                                last_seen_offset_sec=30),
             OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called


class TestDeadRunnerDetection:
    """Test detection and handling of dead runners."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_dead_runner_claim_requires_pattern_match(self, mock_update, mock_select, mock_repair):
        """Only runner-shaped accounts take the dead-runner path; the rest wait for staleness."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [
                MockTask.running(task_id="runner-shaped", account="Mac.lan-0", updated_at_offset_min=5),
                MockTask.running(task_id="freeform", account="unknown-account", updated_at_offset_min=5),
                MockTask.running(task_id="host-shaped", account="localhost-0", updated_at_offset_min=5),
            ],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert {c[0][1]["id"] for c in mock_update.call_args_list} == {"runner-shaped"}

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_dead_runner_grace_period_enforced(self, mock_update, mock_select, mock_repair):
        """A dead runner's claim is left alone until ORCH_DEAD_RUNNER_RECLAIM_GRACE_S passes."""
        mock_repair.return_value = {"state": "QUEUED"}
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "600"}):
            recent = (_now() - datetime.timedelta(seconds=300)).isoformat()
            mock_select.side_effect = [
                [MockTask.running(account="Mac.lan-0", updated_at_iso=recent)],
                [OTHER_LIVE_RUNNER()],
                [],
            ]

            runner._reap_zombie_tasks()

            mock_update.assert_not_called()

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_mandys_macbook_pattern_matched(self, mock_update, mock_select, mock_repair):
        """Account matching Mandys-MacBook-Pro.local-N is eligible for the dead-runner claim."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mandys-MacBook-Pro.local-0", updated_at_offset_min=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called


class TestStaleTaskDetection:
    """Test detection of stale RUNNING tasks."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_stale_task_reclaimed_at_30min_threshold(self, mock_update, mock_select, mock_repair):
        """RUNNING task >30min without update is reclaimed regardless of account shape."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="unknown", updated_at_offset_min=31)], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_fresh_task_not_reclaimed(self, mock_update, mock_select):
        """RUNNING task <30min old with no runner identity is left alone."""
        mock_select.side_effect = [
            [MockTask.running(account="unknown", updated_at_offset_min=5)], [], []]

        runner._reap_zombie_tasks()

        assert not mock_update.called


class TestRetryPromotion:
    """Test promotion of elapsed RETRY tasks back to QUEUED."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_task_promoted_after_ttl(self, mock_update, mock_select):
        """An elapsed RETRY row is written back to QUEUED with a fresh updated_at."""
        mock_select.side_effect = [[], [], [MockTask.retry(updated_at_offset_sec=150)]]

        runner._reap_zombie_tasks()

        assert mock_update.called
        body = mock_update.call_args[0][2]
        assert body["state"] == "QUEUED"
        assert body["updated_at"] == "now()"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_note_appended_with_promoter_marker(self, mock_update, mock_select):
        """Promotion appends ' | retry-promoter' and keeps the prior note."""
        mock_select.side_effect = [
            [], [], [MockTask.retry(note="original note", updated_at_offset_sec=150)]]

        runner._reap_zombie_tasks()

        assert mock_update.call_args[0][2]["note"] == "original note | retry-promoter"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_note_truncated_at_1000_bytes(self, mock_update, mock_select):
        """An oversized note is truncated to the 1000-byte column bound."""
        mock_select.side_effect = [
            [], [], [MockTask.retry(note="x" * 1000, updated_at_offset_sec=150)]]

        runner._reap_zombie_tasks()

        note = mock_update.call_args[0][2]["note"]
        assert len(note.encode("utf-8")) == 1000
        assert note.startswith("x" * 990)


class TestCoworkDispatchSkipping:
    """Test that cowork-dispatched tasks are skipped."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_cowork_account_skipped(self, mock_update, mock_select):
        """Task with a cowork-* account is skipped (separate execution context)."""
        mock_select.side_effect = [
            [MockTask.running(account="cowork-production", updated_at_offset_min=31)], [], []]

        runner._reap_zombie_tasks()

        assert not mock_update.called

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_cowork_prefix_variants_skipped(self, mock_update, mock_select):
        """The skip is a bare prefix test, so every cowork-* variant is covered."""
        mock_select.side_effect = [
            [
                MockTask.running(task_id="c1", account="cowork-", updated_at_offset_min=31),
                MockTask.running(task_id="c2", account="cowork-production", updated_at_offset_min=31),
                MockTask.running(task_id="c3", account="cowork-staging", updated_at_offset_min=31),
            ],
            [],
            [],
        ]

        runner._reap_zombie_tasks()

        assert not mock_update.called


class TestRepairIntegration:
    """Test integration with agentic_repair for reclaimed tasks."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_repair_signal_for_dead_runner(self, mock_update, mock_select, mock_repair):
        """Dead-runner reclaim carries the 'expired runner heartbeat' signal."""
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
    def test_repair_signal_for_stale_task(self, mock_update, mock_select, mock_repair):
        """Stale reclaim carries the 'stale RUNNING >30min' signal."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="unknown", updated_at_offset_min=31)],
            [MockTask.heartbeat(last_seen_offset_sec=30)],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.call_args[0][1] == "zombie-reaper: stale RUNNING >30min"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_repair_category_is_orphaned_running(self, mock_update, mock_select, mock_repair):
        """All reap-loop reclaims are categorised 'orphaned-running'."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.call_args[1]["category"] == "orphaned-running"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_repair_patch_return_value_is_written_verbatim(self, mock_update, mock_select, mock_repair):
        """Whatever repair_patch returns is the update body; the reaper adds nothing.

        WAS: test_repair_directive_preserved, a third copy of the same directive-string
        assertion already owned by test_zombie_reaper_advanced.py. Replaced with the
        untested half of the same integration: the reaper contributes no fields of its
        own to the write, so the recovery contract is entirely agentic_repair's.
        """
        mock_repair.return_value = {"state": "QUEUED", "prompt": "resume me", "attempts": 3}
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.call_args[0][2] == {"state": "QUEUED", "prompt": "resume me", "attempts": 3}


class TestHighVolume:
    """Test high-volume scenarios and database limits."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_handles_100_running_tasks_limit(self, mock_update, mock_select, mock_repair):
        """A full 100-row RUNNING page is fully processed."""
        mock_repair.return_value = {"state": "QUEUED"}
        stale = (_now() - datetime.timedelta(minutes=31)).isoformat()
        mock_select.side_effect = [
            [MockTask.running(task_id=f"t{i}", account=f"Mac.lan-{i % 5}", updated_at_iso=stale)
             for i in range(100)],
            [],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 100

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_handles_250_retry_tasks_limit(self, mock_update, mock_select):
        """A full 250-row RETRY page is fully promoted."""
        mock_select.side_effect = [
            [],
            [],
            [MockTask.retry(task_id=f"r{i}", updated_at_offset_sec=150) for i in range(250)],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 250


class TestTimestampHandling:
    """Test robust timestamp parsing and comparison."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_iso_format_with_microseconds(self, mock_update, mock_select, mock_repair):
        """Microsecond precision does not disturb the dead-runner comparison."""
        # Distinct from the same-named test in test_zombie_reaper_advanced.py, which
        # covers the stale path; this one covers the dead-runner path's grace comparison.
        mock_repair.return_value = {"state": "QUEUED"}
        iso_old = (_now() - datetime.timedelta(seconds=400, microseconds=123456)).isoformat()
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_iso=iso_old)],
            [OTHER_LIVE_RUNNER()],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.call_args[0][1] == "zombie-reaper: expired runner heartbeat"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_empty_updated_at_treated_as_old(self, mock_update, mock_select, mock_repair):
        """An empty updated_at is very old by contract, so the row is reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTask.running()
        task["updated_at"] = ""
        mock_select.side_effect = [[task], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_malformed_timestamp_gracefully_degraded(self, mock_update, mock_select, mock_repair):
        """An unparseable updated_at is very old by contract, so the row is reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTask.running()
        task["updated_at"] = "not-a-timestamp"
        mock_select.side_effect = [[task], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called


class TestErrorHandling:
    """Test error resilience and recovery."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_db_error_caught_and_logged(self, mock_print, mock_update, mock_select):
        """A dead database is logged and swallowed; nothing is written."""
        # WAS: `assert error_logged or not mock_update.called` -- an OR that any outcome
        # satisfies. Both halves are now asserted.
        mock_select.side_effect = Exception("DB connection failed")

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[zombie-reaper] error: DB connection failed" in printed
        assert not mock_update.called

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_heartbeat_query_error_doesnt_wedge_reaper(self, mock_update, mock_select, mock_repair):
        """A failed heartbeat query degrades to stale-only reclamation, it does not abort."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(task_id="fresh", account="Mac.lan-0", updated_at_offset_min=5),
             MockTask.running(task_id="stale", account="Mac.lan-1", updated_at_offset_min=31)],
            Exception("Heartbeat query failed"),
            [],
        ]

        runner._reap_zombie_tasks()  # must not raise

        # With no live_runner_ids the dead-runner path is off by design, so only the
        # genuinely stale row is touched.
        assert {c[0][1]["id"] for c in mock_update.call_args_list} == {"stale"}


class TestRaceConditions:
    """Test handling of concurrent/transient state changes."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_task_completed_before_update_handled(self, mock_update, mock_select, mock_repair):
        """The reaper writes from its own snapshot and does not re-read state first."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_update.return_value = None
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=31)], [], []]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_update.call_args[0][1] == {"id": "t1"}


class TestReaperThrottling:
    """Test that the reap loop runs at most every 300 seconds."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reaper_respects_300s_throttle(self, mock_update, mock_select, mock_repair):
        """A cycle 100s after the last one is skipped entirely -- no queries, no writes."""
        runner._ZOMBIE_REAP_T = time.time() - 100
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=31)], [], []]

        runner._reap_zombie_tasks()

        assert mock_select.call_count == 0
        assert not mock_update.called


class TestContractMetadataHandling:
    """Test how per-task partner/contract metadata survives a reclaim."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reaper_never_requests_contract_columns(self, mock_update, mock_select):
        """The RUNNING query asks for four columns, so contract metadata never arrives.

        WAS: test_task_with_valid_contract_reclaimed, which fabricated contract columns
        the production query does not select and then asserted the reclaim happened
        anyway. The honest contract is upstream of that: the reaper cannot make a
        partner-level decision because it never reads partner-level data.
        """
        mock_select.side_effect = [[], [], []]

        runner._reap_zombie_tasks()

        columns = set(mock_select.call_args_list[0][0][1]["select"].split(","))
        assert columns == {"id", "slug", "updated_at", "account"}
        assert not columns & {"contract_id", "partner_level"}

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_task_metadata_reaches_repair_untouched(self, mock_update, mock_select, mock_repair):
        """Whatever columns a row does carry are handed to the repairer verbatim.

        WAS: `if mock_update.called: assert call_args is not None`, which asserts nothing
        under any circumstances. The real, checkable guarantee is that the reaper passes
        the row object through rather than projecting it -- so a caller that DOES enrich
        the query keeps its metadata all the way into agentic repair.
        """
        mock_repair.return_value = {"state": "QUEUED"}
        task = MockTask.running(account="Mac.lan-0", updated_at_offset_min=31,
                                contract_id="contract-abc-456", partner_level="enterprise")
        mock_select.side_effect = [[task], [], []]

        runner._reap_zombie_tasks()

        passed = mock_repair.call_args[0][0]
        assert passed is task
        assert passed["contract_id"] == "contract-abc-456"
        assert passed["partner_level"] == "enterprise"
        # ...and nothing partner-shaped leaks into the write itself.
        assert set(mock_update.call_args[0][2]) == {"state"}


class TestPrintOutputAndAccounting:
    """Test output reporting and counting."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_reclaim_count_printed(self, mock_print, mock_update, mock_select, mock_repair):
        """The reclaim line reports the number of rows actually written."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = [
            [MockTask.running(task_id="t1", account="Mac.lan-0", updated_at_offset_min=31),
             MockTask.running(task_id="t2", account="Mac.lan-1", updated_at_offset_min=31)],
            [],
            [],
        ]

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[zombie-reaper] reclaimed 2 stale RUNNING tasks" in printed

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    @patch("builtins.print")
    def test_retry_promotion_count_printed(self, mock_print, mock_update, mock_select):
        """The retry-promoter line reports the number of rows actually promoted."""
        mock_select.side_effect = [
            [], [],
            [MockTask.retry(task_id=f"r{i}", updated_at_offset_sec=150) for i in range(5)]]

        runner._reap_zombie_tasks()

        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        assert "[retry-promoter] returned 5 elapsed RETRY tasks to QUEUED" in printed


class TestEnvironmentConfiguration:
    """Test environment variable configuration options."""

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_dead_runner_grace_period_env_parsed(self, mock_update, mock_select):
        """ORCH_DEAD_RUNNER_RECLAIM_GRACE_S widens the window a dead runner's claim gets."""
        # WAS: ran a cycle and asserted nothing. Assert the boundary it moves, from both
        # sides, in one test.
        task = MockTask.running(account="Mac.lan-0",
                                updated_at_iso=(_now() - datetime.timedelta(seconds=300)).isoformat())

        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "600"}):
            mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]
            runner._reap_zombie_tasks()
            mock_update.assert_not_called()

        runner._ZOMBIE_REAP_T = 0.0
        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "60"}):
            mock_select.side_effect = [[task], [OTHER_LIVE_RUNNER()], []]
            with patch.object(runner.agentic_repair, "repair_patch", return_value={"state": "QUEUED"}):
                runner._reap_zombie_tasks()
            assert mock_update.called

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_fleet_ttl_env_parsed(self, mock_update, mock_select):
        """FLEET_TTL_S is the only input to the heartbeat cutoff."""
        with patch.dict(os.environ, {"FLEET_TTL_S": "300"}):
            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()
            cutoff_300 = mock_select.call_args_list[1][0][1]["last_seen"].removeprefix("gte.")

        runner._ZOMBIE_REAP_T = 0.0
        mock_select.reset_mock()
        with patch.dict(os.environ, {"FLEET_TTL_S": "3600"}):
            mock_select.side_effect = [[], [], []]
            runner._reap_zombie_tasks()
            cutoff_3600 = mock_select.call_args_list[1][0][1]["last_seen"].removeprefix("gte.")

        assert cutoff_3600 < cutoff_300, "a longer TTL must reach further back in time"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_promote_after_env_parsed(self, mock_update, mock_select):
        """ORCH_RETRY_PROMOTE_AFTER_S sets the RETRY query's age predicate."""
        with patch.dict(os.environ, {"ORCH_RETRY_PROMOTE_AFTER_S": "300"}):
            mock_select.side_effect = [[], [], [MockTask.retry(updated_at_offset_sec=301)]]
            runner._reap_zombie_tasks()

            cutoff = mock_select.call_args_list[2][0][1]["updated_at"].removeprefix("lt.")
            assert (_now() - datetime.timedelta(seconds=301)).isoformat() < cutoff
            assert (_now() - datetime.timedelta(seconds=250)).isoformat() > cutoff
            assert mock_update.called


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_mixed_dead_and_stale_tasks_both_reclaimed(self, mock_update, mock_select, mock_repair):
        """Dead-runner and stale rows are reclaimed in the same pass, each with its own signal."""
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

        assert mock_update.call_count == 2
        signals = {c[0][0]["id"]: c[0][1] for c in mock_repair.call_args_list}
        assert signals == {
            "dead": "zombie-reaper: expired runner heartbeat",
            "stale": "zombie-reaper: stale RUNNING >30min",
        }

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_full_cycle_running_retry_and_heartbeats(self, mock_update, mock_select):
        """A healthy fleet with one elapsed RETRY produces exactly one write."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=5)],
            [MockTask.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],
            [MockTask.retry(updated_at_offset_sec=150)],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 1
        assert mock_update.call_args[0][2]["state"] == "QUEUED"
        assert mock_update.call_args[0][1] == {"id": "t2"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
