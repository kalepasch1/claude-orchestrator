#!/usr/bin/env python3
"""
test_zombie_reaper_heartbeat.py — Test suite for zombie-reaper heartbeat expiration system

Tests for runner heartbeat monitoring, expiration detection, zombie process reaping,
and recovery mechanisms for orphaned running tasks.

Task: backlog-batch-illuminati-1d1b027
Failure Category: orphaned-running (expired runner heartbeat)
"""
import json
import pytest
import time
import threading
import os
from typing import Dict, List, Any
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timedelta, timezone

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestHeartbeatMonitoring:
    """Test runner heartbeat monitoring and expiration detection."""

    def test_heartbeat_fresh_status(self):
        """Heartbeat within TTL is marked as fresh."""
        from db import _fresh

        now = time.time()
        fresh_ts = now - 30  # 30 seconds ago
        assert _fresh(fresh_ts) is True

    def test_heartbeat_stale_status(self):
        """Heartbeat beyond TTL is marked as stale."""
        from db import _fresh

        now = time.time()
        stale_ts = now - 3600  # 1 hour ago
        assert _fresh(stale_ts) is False

    def test_heartbeat_ttl_boundary(self):
        """Heartbeat exactly at TTL threshold."""
        from db import HEARTBEAT_TTL_MINUTES, _fresh

        now = time.time()
        boundary_ts = now - (HEARTBEAT_TTL_MINUTES * 60)
        # Boundary may be either fresh or stale depending on implementation
        assert isinstance(_fresh(boundary_ts), bool)

    @patch("db.db")
    def test_heartbeat_record_structure(self, mock_db):
        """The published row carries exactly the live schema's required fields."""
        # WAS: asserted against a dict literal defined three lines above it, so it
        # could not fail and, worse, documented a schema the table never had
        # ("active" bool, epoch-float last_seen, model_loaded/memory_mb columns).
        # Assert against the row db.heartbeat() actually hands to db.insert instead.
        from db import heartbeat

        mock_db.insert.return_value = None
        heartbeat("pid-12345", "runner-1.internal", active=True)

        row = mock_db.insert.call_args[0][1]
        for required in ("runner_id", "hostname", "active_tasks", "last_seen"):
            assert required in row, f"{required} missing from published heartbeat row"
        assert row["runner_id"] == "pid-12345"
        assert row["hostname"] == "runner-1.internal"
        assert isinstance(row["active_tasks"], int)
        assert not isinstance(row["active_tasks"], bool)

    @patch("db.db")
    def test_heartbeat_upsert_creates_new(self, mock_db):
        """Heartbeat upsert creates new runner entry."""
        from db import heartbeat

        mock_db.insert.return_value = None

        heartbeat("pid-12345", "host1", active=True)

        mock_db.insert.assert_called()
        call_args = mock_db.insert.call_args
        assert "runner_heartbeats" in call_args[0]

    @patch("db.db")
    def test_heartbeat_upsert_updates_existing(self, mock_db):
        """Heartbeat upsert updates existing runner entry."""
        from db import heartbeat

        mock_db.insert.return_value = None

        # Call twice with same runner_id
        heartbeat("pid-12345", "host1", active=True)
        heartbeat("pid-12345", "host1", active=True)

        # Should have called insert twice (upsert)
        assert mock_db.insert.call_count == 2

    @patch("db.db")
    def test_heartbeat_inactive_runner(self, mock_db):
        """An idle runner is published as active_tasks=0, not as a boolean column."""
        # WAS: asserted row["active"] is False, which raised KeyError. There is no
        # "active" column: db.heartbeat() converts the bool argument to the live
        # schema's integer `active_tasks` (db.py:2635-2637). The old shape — a bool
        # "active" column — is precisely the one that made every insert fail for weeks.
        from db import heartbeat

        mock_db.insert.return_value = None

        heartbeat("pid-12345", "host1", active=False)

        mock_db.insert.assert_called()
        table, row = mock_db.insert.call_args[0][:2]
        assert table == "runner_heartbeats"
        assert "active" not in row
        assert row["active_tasks"] == 0
        assert row["runner_id"] == "pid-12345"
        assert row["hostname"] == "host1"

    @patch("db.db")
    def test_heartbeat_busy_runner_publishes_nonzero_active_tasks(self, mock_db):
        """The busy/idle distinction must survive the bool -> active_tasks mapping."""
        # New sibling of the test above: without it, a heartbeat that hard-coded
        # active_tasks=0 would still pass.
        from db import heartbeat

        mock_db.insert.return_value = None

        heartbeat("pid-12345", "host1", active=True)

        row = mock_db.insert.call_args[0][1]
        assert row["active_tasks"] == 1

    @patch("db.db")
    def test_heartbeat_omits_columns_the_table_does_not_have(self, mock_db):
        """model_loaded/memory_mb are accepted as arguments but never written."""
        # WAS: `assert "model_loaded" in row or "last_seen" in row` — an or-clause that
        # last_seen satisfied unconditionally, so it passed while asserting nothing.
        # The real contract (db.py:2628-2634) is that the row must match the live
        # schema exactly: runner_id, hostname, active_tasks, last_seen (+ optional
        # identity/visibility columns). Sending model_loaded/memory_mb made every
        # insert fail, so their absence is the property worth pinning.
        from db import heartbeat

        mock_db.insert.return_value = None

        heartbeat("pid-12345", "host1", active=True,
                  model_loaded="claude-opus-5", memory_mb=2048)

        row = mock_db.insert.call_args[0][1]
        assert "model_loaded" not in row
        assert "memory_mb" not in row
        # last_seen is an ISO-8601 timestamptz string, not an epoch float.
        assert isinstance(row["last_seen"], str)
        datetime.fromisoformat(row["last_seen"])


class TestHeartbeatPruning:
    """Test pruning of stale heartbeat records."""

    @patch("db._last_heartbeat_prune", 0.0)
    @patch("db._req")
    def test_prune_stale_heartbeats_deletes_old(self, mock_req):
        """Prune removes heartbeats older than TTL."""
        import db
        from db import _prune_stale_heartbeats, HEARTBEAT_TTL_MINUTES

        mock_req.return_value = None

        # Reset the module-level timer to force prune to run
        db._last_heartbeat_prune = 0.0

        _prune_stale_heartbeats()

        # Should have called DELETE on first run
        mock_req.assert_called()
        call_args = mock_req.call_args
        assert call_args[0][0] == "DELETE"
        assert "runner_heartbeats" in call_args[0][1]

    @patch("db._req")
    def test_prune_stale_respects_interval(self, mock_req):
        """Prune only runs after HEARTBEAT_PRUNE_INTERVAL."""
        from db import _prune_stale_heartbeats, _last_heartbeat_prune
        import db as db_module

        mock_req.return_value = None

        # Call prune twice in quick succession
        _prune_stale_heartbeats()
        call_count_1 = mock_req.call_count

        _prune_stale_heartbeats()
        call_count_2 = mock_req.call_count

        # Second call should not increment if within interval
        assert call_count_2 >= call_count_1

    def test_heartbeat_prune_interval_constant(self):
        """HEARTBEAT_PRUNE_INTERVAL is defined."""
        from db import HEARTBEAT_PRUNE_INTERVAL_S

        assert HEARTBEAT_PRUNE_INTERVAL_S > 0
        assert isinstance(HEARTBEAT_PRUNE_INTERVAL_S, (int, float))


class TestZombieProcessDetection:
    """Test detection and classification of zombie runner processes."""

    def test_detect_expired_heartbeat(self):
        """Detect runner with expired heartbeat."""
        from db import _fresh

        # Heartbeat from 2 hours ago
        expired_ts = time.time() - 7200
        assert _fresh(expired_ts) is False

    def test_detect_recent_heartbeat(self):
        """Detect runner with recent heartbeat."""
        from db import _fresh

        # Heartbeat from 30 seconds ago
        recent_ts = time.time() - 30
        assert _fresh(recent_ts) is True

    @patch("db.select")
    def test_query_stale_runners(self, mock_select):
        """Query for runners with stale heartbeats."""
        from db import HEARTBEAT_TTL_MINUTES

        stale_cutoff = time.time() - (HEARTBEAT_TTL_MINUTES * 60)

        mock_select.return_value = [
            {
                "runner_id": "pid-old-1",
                "hostname": "host1",
                "last_seen": stale_cutoff - 100,
                "active": True,
            },
            {
                "runner_id": "pid-old-2",
                "hostname": "host2",
                "last_seen": stale_cutoff - 200,
                "active": True,
            },
        ]

        result = mock_select()

        assert len(result) == 2
        assert all(r["last_seen"] < stale_cutoff for r in result)

    def test_zombie_classification_rules(self):
        """Zombie process classification logic."""
        # A zombie is:
        # 1. Has runner_id (PID)
        # 2. active=True in heartbeats table
        # 3. last_seen > HEARTBEAT_TTL_MINUTES

        def is_zombie(runner_record: Dict) -> bool:
            from db import HEARTBEAT_TTL_MINUTES, _fresh
            return (
                runner_record.get("active") is True
                and not _fresh(runner_record.get("last_seen", 0))
            )

        # Zombie case
        assert is_zombie({
            "runner_id": "pid-123",
            "active": True,
            "last_seen": time.time() - 7200,
        }) is True

        # Not zombie: inactive
        assert is_zombie({
            "runner_id": "pid-123",
            "active": False,
            "last_seen": time.time() - 7200,
        }) is False

        # Not zombie: recent heartbeat
        assert is_zombie({
            "runner_id": "pid-123",
            "active": True,
            "last_seen": time.time() - 30,
        }) is False


def _minutes_ago(minutes):
    """tz-aware ISO-8601 timestamp, the shape `updated_at` really carries."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


class TestOrphanedRunningTaskRecovery:
    """Test recovery of tasks stuck in RUNNING state.

    Every test here used to assert on canned data it had just handed to a Mock
    (`mock_select.return_value = [...]; result = mock_select()`), or on a locally
    defined is_orphaned_task() helper — so the class tested the mock, and the columns
    it asserted on ("status", "runner_id", "error") are not columns this schema has.
    The importable implementation of this recovery is
    queue_janitor.release_orphaned_running(), which is what these now drive. (The other
    half lives in runner._reap_zombie_tasks, but `import runner` resolves to the
    runner/ package and executing runner.py would start the world — see the note in
    test_compliance_periodic_jobs.py.)
    """

    def _run(self, rows):
        """Run the janitor's orphan sweep over `rows`; return (fixed, updates)."""
        import queue_janitor

        updates = []

        def fake_select(table, params=None):
            if table == "tasks":
                assert params == {"select": "*", "state": "eq.RUNNING"}, params
                return list(rows)
            return []

        with patch.object(queue_janitor.db, "select", side_effect=fake_select), \
                patch.object(queue_janitor.db, "update",
                             side_effect=lambda t, m, p: updates.append((m["id"], p))):
            fixed = queue_janitor.release_orphaned_running()
        return fixed, updates

    def test_find_orphaned_running_tasks(self):
        """Only RUNNING tasks past the orphan threshold are acted on."""
        import queue_janitor

        stale = queue_janitor.ORPHAN_RUNNING_MIN + 10
        fresh = max(0.0, queue_janitor.ORPHAN_RUNNING_MIN - 5)
        fixed, updates = self._run([
            {"id": "task-1", "slug": "orphaned", "account": "Mac.lan-4171",
             "updated_at": _minutes_ago(stale), "transient_retries": 0,
             "attempt": 1, "remediation_count": 0},
            {"id": "task-2", "slug": "still-running", "account": "Mac.lan-4172",
             "updated_at": _minutes_ago(fresh), "transient_retries": 0},
        ])

        assert fixed == 1
        assert [task_id for task_id, _ in updates] == ["task-1"]

    def test_orphaned_task_detection_criteria(self):
        """Cowork claims and unreadable timestamps are never treated as orphans."""
        import queue_janitor

        stale = queue_janitor.ORPHAN_RUNNING_MIN + 60
        fixed, updates = self._run([
            {"id": "cowork", "slug": "c", "account": "cowork-session-9",
             "updated_at": _minutes_ago(stale), "transient_retries": 0},
            {"id": "unparseable", "slug": "u", "account": "Mac.lan-1",
             "updated_at": "not-a-timestamp", "transient_retries": 0},
            {"id": "orphan", "slug": "o", "account": "Mac.lan-2",
             "updated_at": _minutes_ago(stale), "transient_retries": 0,
             "attempt": 1, "remediation_count": 0},
        ])

        # A Cowork task runs outside this host, so its claim is not evidence of death.
        assert [task_id for task_id, _ in updates] == ["orphan"]
        assert fixed == 1

    def test_requeue_orphaned_task(self):
        """The dead claim is released and the task goes back to QUEUED."""
        import queue_janitor

        rows = [{"id": "task-1", "slug": "s", "account": "Mac.lan-4171",
                 "note": "prior note", "attempt": 1, "remediation_count": 1,
                 "updated_at": _minutes_ago(queue_janitor.ORPHAN_RUNNING_MIN + 30),
                 "transient_retries": 0}]
        fixed, updates = self._run(rows)

        assert fixed == 1
        task_id, patch_out = updates[0]
        assert task_id == "task-1"
        assert patch_out["state"] == "QUEUED"
        assert patch_out["account"] is None          # the lane is freed
        assert patch_out["remediation_count"] == 2
        assert patch_out["attempt"] == 2
        assert patch_out["note"] == "agentic-repair:orphaned-running"
        # The janitor's own cap counter must ADVANCE, or a task ping-pongs forever.
        # (It currently advances by two per sweep: release_orphaned_running() passes a
        # pre-incremented copy and _repair_task increments again. Asserting "strictly
        # greater" states the invariant without blessing the step size.)
        assert patch_out["transient_retries"] > rows[0]["transient_retries"]

    def test_mark_orphaned_task_failed(self):
        """A task repair cannot converge on is parked, not requeued forever."""
        # WAS: called db.update() itself with {"status": "failed", "error": ...} and
        # asserted the mock had been called — it exercised nothing but Mock. The real
        # terminal path is agentic_repair's GLOBAL_REPAIR_CEILING, reached through the
        # same janitor sweep, and the terminal state is QUARANTINED.
        import agentic_repair
        import queue_janitor

        fixed, updates = self._run([
            {"id": "task-1", "slug": "s", "account": "Mac.lan-4171", "note": "n",
             "attempt": 2, "transient_retries": 5,
             "remediation_count": agentic_repair.GLOBAL_REPAIR_CEILING + 1,
             "updated_at": _minutes_ago(queue_janitor.ORPHAN_RUNNING_MIN + 30)},
        ])

        assert fixed == 1
        _task_id, patch_out = updates[0]
        assert patch_out["state"] == "QUARANTINED"
        assert agentic_repair.is_terminal(patch_out)
        # A terminal patch must not be post-processed by the janitor: stomping the note
        # or the counters re-opens the unbounded requeue loop the ceiling just closed.
        assert "transient_retries" not in patch_out
        assert patch_out["note"].startswith(agentic_repair.TERMINAL_NOTE_PREFIX)


class _FakeTaskStore:
    """Minimal stand-in for runner/db.py's select/update surface.

    zombie_reaper.ZombieReaper documents exactly this two-method contract
    ("store is any object exposing select(table, params) and update(table, match,
    patch)"), so the tests below drive the real module instead of a simulation.
    """

    def __init__(self, rows, fail_on=()):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.fail_on = set(fail_on)
        self.updates = []

    def select(self, table, params):
        assert table == "tasks"
        task_id = params["id"].split("eq.", 1)[1]
        if task_id in self.fail_on:
            raise OSError(f"store unavailable for {task_id}")
        row = self.rows.get(task_id)
        return [dict(row)] if row else []

    def update(self, table, match, patch):
        assert table == "tasks"
        task_id = match["id"]
        if task_id in self.fail_on:
            raise OSError(f"store unavailable for {task_id}")
        self.rows[task_id].update(patch)
        self.updates.append((task_id, dict(patch)))
        return None


class TestZombieReaperExecution:
    """Test zombie reaper process execution and cleanup."""

    def test_zombie_reaper_cycle(self):
        """Full zombie reaper cycle: expired RUNNING ids are written to FAILED."""
        # WAS: defined a local run_zombie_reaper_cycle() that returned
        # {"detected": len(zombies), "reaped": len(zombies)} and asserted on its own
        # arithmetic — it could not fail and never touched zombie_reaper.py. Drive the
        # real entry point (zombie_reaper.terminate_expired) against the injectable
        # store the module documents.
        import zombie_reaper

        store = _FakeTaskStore([
            {"id": "task-1", "state": "RUNNING", "note": ""},
            {"id": "task-2", "state": "RUNNING", "note": ""},
            {"id": "task-3", "state": "RUNNING", "note": ""},
        ])

        result = zombie_reaper.terminate_expired(
            ["task-1", "task-2", "task-3"], store=store, dry_run=False)

        assert result["terminated"] == ["task-1", "task-2", "task-3"]
        assert result["skipped"] == [] and result["missing"] == [] and result["errored"] == []
        assert all(r["state"] == zombie_reaper.FAILED_STATE for r in store.rows.values())

    def test_zombie_reaper_logging(self):
        """Every reap is recorded — in the log and in the task's own note."""
        # WAS: appended dicts to a local list via a local log_reap() and asserted the
        # list had two entries. Assert the module's real record-keeping instead: a
        # warning naming each task id, and a note that APPENDS the reason rather than
        # overwriting the prior note (zombie_reaper._note).
        import zombie_reaper

        store = _FakeTaskStore([
            {"id": "pid-123", "state": "RUNNING", "note": "attempt 1 failed"},
            {"id": "pid-456", "state": "RUNNING", "note": ""},
        ])

        with patch.object(zombie_reaper, "_log", MagicMock()) as mock_log:
            zombie_reaper.terminate_expired(
                ["pid-123", "pid-456"], reason="heartbeat_expired",
                store=store, dry_run=False)

        logged = " ".join(str(c) for c in mock_log.warning.call_args_list)
        assert "pid-123" in logged and "pid-456" in logged
        assert "heartbeat_expired" in logged
        assert store.rows["pid-123"]["note"] == "attempt 1 failed | heartbeat_expired"
        assert store.rows["pid-456"]["note"] == "heartbeat_expired"

    def test_zombie_reaper_error_resilience(self):
        """One bad id must not abandon the rest of the batch."""
        # WAS: a local try_reap_zombie() that appended to local lists — it tested
        # Python's try/except, not the reaper. The real guarantee (module docstring:
        # "It never raises") is that a store failure on one id is reported under
        # "errored" while the surrounding ids are still terminated.
        import zombie_reaper

        store = _FakeTaskStore(
            [{"id": "pid-1", "state": "RUNNING", "note": ""},
             {"id": "bad-pid", "state": "RUNNING", "note": ""},
             {"id": "pid-2", "state": "RUNNING", "note": ""}],
            fail_on=["bad-pid"],
        )

        result = zombie_reaper.terminate_expired(
            ["pid-1", "bad-pid", "pid-2"], store=store, dry_run=False)

        assert result["terminated"] == ["pid-1", "pid-2"]
        assert result["errored"] == ["bad-pid"]
        assert store.rows["bad-pid"]["state"] == "RUNNING"

    def test_zombie_reaper_does_not_terminate_a_task_that_recovered(self):
        """A task whose worker came back is skipped, not failed."""
        # SUBSTITUTION: this was test_zombie_reaper_with_task_recovery, which called a
        # locally defined reap_zombie_and_recover() and asserted it returned the counts
        # it had just been handed. zombie_reaper does no requeueing at all — it is
        # "terminal disposal" and detection/repair live in the reap loop (module
        # docstring). The nearest real behaviour, and the one that protects recovered
        # work, is the state guard: a task no longer in RUNNING is reported under
        # "skipped" and left untouched, and a vanished task under "missing".
        import zombie_reaper

        store = _FakeTaskStore([
            {"id": "t1", "state": "DONE", "note": "finished after the reap query"},
            {"id": "t2", "state": "RUNNING", "note": ""},
        ])

        result = zombie_reaper.terminate_expired(
            ["t1", "t2", "t3-deleted"], store=store, dry_run=False)

        assert result["skipped"] == ["t1"]
        assert result["terminated"] == ["t2"]
        assert result["missing"] == ["t3-deleted"]
        assert store.rows["t1"]["state"] == "DONE"
        assert store.rows["t1"]["note"] == "finished after the reap query"


class TestHeartbeatRecoveryMechanisms:
    """Test recovery when heartbeat system degrades."""

    @patch("db.insert")
    def test_heartbeat_write_resilience(self, mock_insert):
        """Heartbeat write failures don't crash runner."""
        from db import heartbeat

        mock_insert.side_effect = Exception("DB connection failed")

        try:
            heartbeat("pid-123", "host1", active=True)
        except Exception:
            pass  # Should be caught and logged

    @patch("db.select")
    def test_heartbeat_query_resilience(self, mock_select):
        """Heartbeat queries handle DB errors gracefully."""
        mock_select.side_effect = Exception("Query failed")

        def query_heartbeats():
            try:
                return mock_select()
            except Exception:
                return []  # Fail-soft

        result = query_heartbeats()
        assert result == []

    def test_heartbeat_fallback_to_process_check(self):
        """If heartbeat missing, check process alive."""
        import os
        import signal

        def is_process_alive(pid: int) -> bool:
            try:
                os.kill(pid, 0)  # Send no-op signal
                return True
            except (OSError, ProcessLookupError):
                return False

        # Current process should be alive
        assert is_process_alive(os.getpid()) is True

        # Fake PID should be dead (assuming invalid)
        assert is_process_alive(999999) is False

    def test_heartbeat_circuit_breaker(self):
        """Heartbeat writes skip on repeated failures."""
        failures = [0]
        max_failures = 3
        circuit_open = [False]

        def heartbeat_with_circuit_breaker(runner_id: str):
            if circuit_open[0]:
                return False

            try:
                # Simulate failure
                if failures[0] < max_failures:
                    failures[0] += 1
                    raise Exception("Failed")
                return True
            except Exception:
                if failures[0] >= max_failures:
                    circuit_open[0] = True
                return False

        # First 3 calls fail and open circuit
        for _ in range(max_failures):
            heartbeat_with_circuit_breaker("pid-123")

        # Circuit is now open
        assert circuit_open[0] is True


class TestBacklogBatchWithZombieRecovery:
    """Test backlog batch processor integration with zombie recovery."""

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    def test_batch_processor_respects_zombie_stale_runners(self, mock_rg, mock_db):
        """Batch processor skips tasks for stale runners."""
        from backlog_batch_processor import BacklogBatchProcessor

        mock_rg.can_claim.return_value = True
        mock_db.select.return_value = []  # No fresh tasks

        proc = BacklogBatchProcessor()
        result = proc.process_batch()

        assert result["processed"] == 0

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    def test_batch_processor_recovery_workflow(self, mock_rg, mock_db):
        """Batch processor can recover orphaned tasks."""
        from backlog_batch_processor import BacklogBatchProcessor

        mock_rg.can_claim.return_value = True

        # Simulate orphaned task
        orphaned_task = {
            "id": "orphan-1",
            "project": "test",
            "title": "Recovered task",
            "slug": "recovered",
            "status": "queued",
            "runner_id": None,  # Runner was reaped
        }
        mock_db.select.return_value = [orphaned_task]
        mock_db.update.return_value = None

        proc = BacklogBatchProcessor()
        result = proc.process_batch()

        # Should attempt to process recovered task
        assert "processed" in result


class TestRunnerHeartbeatIntegration:
    """Integration tests for runner heartbeat system."""

    @patch("db.db")
    def test_runner_heartbeat_loop(self, mock_db):
        """Runner sends heartbeats in loop."""
        mock_db.insert.return_value = None

        from db import heartbeat

        heartbeats_sent = 0
        for i in range(3):
            heartbeat("pid-12345", "host1", active=True)
            heartbeats_sent += 1

        assert heartbeats_sent == 3
        assert mock_db.insert.call_count == 3

    @patch("db.select")
    def test_fleet_view_healthy_runners(self, mock_select):
        """Fleet view shows only healthy runners."""
        from db import _fresh

        mock_select.return_value = [
            {
                "runner_id": "pid-1",
                "hostname": "host1",
                "last_seen": time.time() - 30,
                "active": True,
            },
            {
                "runner_id": "pid-2",
                "hostname": "host2",
                "last_seen": time.time() - 7200,  # Stale
                "active": True,
            },
        ]

        all_runners = mock_select()
        healthy = [r for r in all_runners if _fresh(r["last_seen"])]

        assert len(healthy) == 1
        assert healthy[0]["runner_id"] == "pid-1"

    @patch("db.select")
    @patch("db.update")
    def test_zombie_detection_and_requeue_workflow(self, mock_update, mock_select):
        """Full workflow: detect zombie, requeue orphaned tasks."""
        stale_runner = {
            "runner_id": "pid-dead",
            "hostname": "host1",
            "last_seen": time.time() - 7200,
            "active": True,
        }

        orphaned_task = {
            "id": "task-orphan",
            "status": "running",
            "runner_id": "pid-dead",
        }

        # First query finds stale runner
        # Second query finds orphaned task
        mock_select.side_effect = [
            [stale_runner],
            [orphaned_task],
        ]

        mock_update.return_value = None

        # Simulate requeue
        mock_update("tasks", {"id": "task-orphan"}, {"status": "queued"})

        assert mock_update.called


class TestHeartbeatMetrics:
    """Test heartbeat monitoring metrics and observability."""

    def test_heartbeat_stats_current(self):
        """Heartbeat stats show current state."""
        stats = {
            "total_runners": 5,
            "healthy_runners": 4,
            "stale_runners": 1,
            "last_update": time.time(),
        }

        assert stats["healthy_runners"] < stats["total_runners"]
        assert stats["stale_runners"] == 1

    def test_zombie_count_metrics(self):
        """Zombie reaper reports count metrics."""
        metrics = {
            "zombies_detected": 3,
            "zombies_reaped": 3,
            "tasks_recovered": 5,
            "errors": 0,
            "cycle_duration_sec": 1.2,
        }

        assert metrics["zombies_detected"] == metrics["zombies_reaped"]
        assert metrics["errors"] == 0

    def test_orphaned_task_backlog(self):
        """Track count of orphaned tasks in backlog."""
        backlog = {
            "total_orphaned": 10,
            "requeued_this_cycle": 5,
            "failed_permanently": 2,
            "still_orphaned": 3,
        }

        assert (
            backlog["requeued_this_cycle"]
            + backlog["failed_permanently"]
            + backlog["still_orphaned"]
            == backlog["total_orphaned"]
        )


class TestHeartbeatEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_runner_id_collision(self):
        """Handle PID reuse (runner_id collision)."""
        # Old runner PID 123 dies
        # New runner gets PID 123
        # Should upsert, not create duplicate

        old_entry = {
            "runner_id": "pid-123",
            "last_seen": time.time() - 7200,  # Stale
        }

        new_entry = {
            "runner_id": "pid-123",
            "last_seen": time.time(),  # Fresh
        }

        # Upsert should update, not create new row
        assert old_entry["runner_id"] == new_entry["runner_id"]

    def test_heartbeat_clock_skew(self):
        """Handle system clock going backwards."""
        future_ts = time.time() + 3600

        def is_reasonable_timestamp(ts: float) -> bool:
            now = time.time()
            return abs(ts - now) < 86400  # Within 1 day

        assert is_reasonable_timestamp(time.time()) is True
        assert is_reasonable_timestamp(future_ts) is True
        assert is_reasonable_timestamp(time.time() - 999999999) is False

    def test_orphaned_task_with_no_runner_id(self):
        """Handle orphaned task with NULL runner_id."""
        task = {
            "id": "t1",
            "status": "running",
            "runner_id": None,
        }

        # Should not crash; should requeue
        assert task["runner_id"] is None

    def test_heartbeat_record_with_missing_fields(self):
        """Handle heartbeat records missing optional fields."""
        from db import _fresh

        incomplete = {
            "runner_id": "pid-123",
            # "last_seen" missing
        }

        # Should not crash
        try:
            result = _fresh(incomplete.get("last_seen", 0))
            assert isinstance(result, bool)
        except Exception:
            pass  # Acceptable if defensively rejected


class TestHeartbeatPerformance:
    """Test heartbeat system under load."""

    def test_heartbeat_throughput(self):
        """Heartbeat can handle many runners."""
        runner_count = 100
        heartbeat_times = []

        for i in range(runner_count):
            start = time.time()
            # Simulate heartbeat
            _ = {
                "runner_id": f"pid-{i}",
                "timestamp": time.time(),
            }
            heartbeat_times.append(time.time() - start)

        avg_time = sum(heartbeat_times) / len(heartbeat_times)
        assert avg_time < 0.01  # Should be fast

    def test_stale_heartbeat_query_index(self):
        """Stale heartbeat queries use index."""
        # Query should use index on last_seen column
        # No way to verify in unit test, but verify structure
        query_spec = {
            "table": "runner_heartbeats",
            "where": "last_seen < now",
            "index": "idx_runner_heartbeats_last_seen",
        }

        assert query_spec["index"]  # Index should be present


class TestLogicalRunnersHeartbeats:
    """Test heartbeat handling with logical runners (lanes)."""

    @patch("os.environ.get")
    @patch("db.db")
    def test_logical_runners_lanes_enabled(self, mock_db, mock_env):
        """Logical runners create multiple lane heartbeats."""
        from db import heartbeat

        def env_side_effect(key, default=None):
            if key == "ORCH_LOGICAL_RUNNERS":
                return "true"
            if key == "ORCH_RUNNER_FLEET_TARGET":
                return "4"
            return default

        mock_env.side_effect = env_side_effect
        mock_db.insert.return_value = None

        heartbeat("pid-123", "host1", active=True)

        # Should have inserted main runner + lanes
        assert mock_db.insert.call_count >= 1

    @patch("db.db")
    def test_heartbeat_compatibility_fallback(self, mock_db):
        """Heartbeat falls back to schema without new fields."""
        from db import heartbeat

        # First call fails with full row
        # Second call succeeds with compatible row
        mock_db.insert.side_effect = [Exception("Column not found"), None]

        heartbeat("pid-123", "host1", active=True, model_loaded="claude")

        # Should have tried twice
        assert mock_db.insert.call_count == 2

    @patch("db.db")
    def test_heartbeat_with_contract_metadata(self, mock_db):
        """Heartbeat includes runtime contract metadata if available."""
        from db import heartbeat

        mock_db.insert.return_value = None

        # Simulate successful heartbeat with metadata
        heartbeat("pid-123", "host1", active=True)

        # Verify insert was called
        mock_db.insert.assert_called()


class TestConcurrentHeartbeatWrites:
    """Test thread-safe heartbeat writes under concurrency."""

    @patch("db.db")
    def test_concurrent_heartbeats_no_race(self, mock_db):
        """Multiple threads can write heartbeats concurrently."""
        from db import heartbeat
        import threading

        mock_db.insert.return_value = None

        results = []

        def write_heartbeat(runner_id):
            try:
                heartbeat(runner_id, f"host-{runner_id}", active=True)
                results.append(True)
            except Exception as e:
                results.append(e)

        threads = [
            threading.Thread(target=write_heartbeat, args=(f"pid-{i}",))
            for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        assert all(results)


class TestHeartbeatFailoverScenarios:
    """Test heartbeat system under failure conditions."""

    def test_heartbeat_db_unavailable_recovery(self):
        """System recovers when DB becomes available again."""
        from db import is_db_down, _increment_db_failure_count, _reset_db_failure_count

        # Set threshold to 3
        assert is_db_down() is False

        # Simulate failures
        _increment_db_failure_count()
        _increment_db_failure_count()
        _increment_db_failure_count()

        # Now DB should be marked down
        assert is_db_down() is True

        # Recovery
        _reset_db_failure_count()
        assert is_db_down() is False

    def test_heartbeat_network_timeout_resilience(self):
        """Heartbeat write tolerates network timeouts."""
        from db import heartbeat

        def timeout_then_succeed():
            raise TimeoutError("Network timeout")

        # Even if write fails, heartbeat() should not raise
        # (fail-soft design)
        try:
            # In real code, a timeout would be caught and swallowed
            pass
        except TimeoutError:
            pass

    def test_heartbeat_malformed_response_resilience(self):
        """Heartbeat handles malformed DB responses gracefully."""
        def parse_response(resp):
            try:
                return json.loads(resp)
            except (json.JSONDecodeError, ValueError):
                return {}  # Fail-soft

        # Valid response
        assert parse_response('{"id": 1}') == {"id": 1}

        # Malformed response
        assert parse_response("not json") == {}


class TestHeartbeatTableManagement:
    """Test runner_heartbeats table lifecycle."""

    @staticmethod
    def _declared_columns():
        """Columns the migrations actually declare on runner_heartbeats."""
        import re

        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        migrations = os.path.join(repo_root, "supabase", "migrations")
        columns = set()
        for name in sorted(os.listdir(migrations)):
            if not name.endswith(".sql"):
                continue
            with open(os.path.join(migrations, name), encoding="utf-8") as fh:
                sql = fh.read()
            create = re.search(
                r"create table if not exists (?:public\.)?runner_heartbeats\s*\((.*?)\);",
                sql, re.S | re.I)
            if create:
                for line in create.group(1).splitlines():
                    line = line.strip().strip(",")
                    if line and not line.lower().startswith(("primary key", "constraint")):
                        columns.add(line.split()[0])
            for alter in re.finditer(
                    r"alter table(?: if exists)? (?:public\.)?runner_heartbeats(.*?);",
                    sql, re.S | re.I):
                columns.update(re.findall(r"add column if not exists (\w+)",
                                          alter.group(1), re.I))
        return columns

    @patch("db.db")
    def test_heartbeat_table_schema_columns(self, mock_db):
        """Every column db.heartbeat() publishes is one the migrations declare."""
        # WAS: built a dict of six field names and asserted its keys were a superset of
        # the same six names written out again — a tautology, and it named columns that
        # do not exist ("active", "model_loaded", "memory_mb"). Sending exactly those
        # is what made every insert fail for weeks (db.py:2628-2634). Compare the real
        # published row against the real DDL instead.
        from db import heartbeat

        declared = self._declared_columns()
        assert {"runner_id", "hostname", "active_tasks", "last_seen"} <= declared, declared
        assert "active" not in declared and "model_loaded" not in declared

        mock_db.insert.return_value = None
        heartbeat("pid-123", "host1", active=True, model_loaded="x", memory_mb=2048)

        published = set(mock_db.insert.call_args[0][1])
        assert published <= declared, f"undeclared columns published: {published - declared}"
        assert {"runner_id", "hostname", "active_tasks", "last_seen"} <= published

    @patch("db.db")
    def test_runner_id_is_primary_key(self, mock_db):
        """Liveness is upserted on runner_id, so a runner never duplicates its row."""
        # WAS: put a dict in a dict keyed by runner_id, replaced it, and asserted the
        # dict still had one entry — it demonstrated Python dict assignment, not upsert.
        # runner_id is the table's primary key (init_orchestrator.sql: "runner_id text
        # primary key"), and the upsert=True flag on the insert is what relies on it.
        from db import heartbeat

        mock_db.insert.return_value = None
        heartbeat("pid-123", "host1", active=True)
        heartbeat("pid-123", "host1", active=False)

        assert mock_db.insert.call_count == 2
        for call_obj in mock_db.insert.call_args_list:
            assert call_obj[0][0] == "runner_heartbeats"
            assert call_obj[1].get("upsert") is True, "insert must upsert on the PK"
            assert call_obj[0][1]["runner_id"] == "pid-123"
        # Second write reflects the newer state on the same key.
        assert mock_db.insert.call_args_list[-1][0][1]["active_tasks"] == 0

    @patch("db._req")
    def test_prune_query_uses_timestamp_index(self, mock_req):
        """Prune query is indexed for performance."""
        import db as db_module
        db_module._last_heartbeat_prune = 0.0

        from db import _prune_stale_heartbeats

        mock_req.return_value = None

        _prune_stale_heartbeats()

        # Query should use < (less-than) for index
        call_args = mock_req.call_args
        assert call_args[0][0] == "DELETE"
        assert "params" in call_args[1]


class TestHealthCheckIntegration:
    """Test heartbeat's role in fleet health checks."""

    def test_health_check_requires_recent_heartbeat(self):
        """Health check fails if heartbeat is stale."""
        from db import _fresh, HEARTBEAT_TTL_MINUTES

        now = time.time()

        # Recent heartbeat = healthy
        assert _fresh(now - 60) is True

        # Stale heartbeat = unhealthy
        assert _fresh(now - (HEARTBEAT_TTL_MINUTES * 60 + 100)) is False

    def test_health_endpoint_aggregates_runner_status(self):
        """Health endpoint reports fleet status from heartbeats."""
        runners = [
            {"runner_id": "pid-1", "last_seen": time.time() - 30, "active": True},
            {"runner_id": "pid-2", "last_seen": time.time() - 7200, "active": True},
            {"runner_id": "pid-3", "last_seen": time.time() - 45, "active": True},
        ]

        from db import _fresh

        healthy_count = sum(1 for r in runners if _fresh(r["last_seen"]))
        stale_count = len(runners) - healthy_count

        assert healthy_count == 2
        assert stale_count == 1

        health_status = {
            "total_runners": len(runners),
            "healthy": healthy_count,
            "unhealthy": stale_count,
        }

        assert health_status["healthy"] + health_status["unhealthy"] == health_status["total_runners"]


class TestZombieReaperTaskRecovery:
    """Test zombie reaper's task recovery workflow in detail.

    Every test in this class used to build a task dict, mutate it in place, and then
    assert on the mutation it had just performed — no product code was involved, and
    the fields they asserted on ("status", "runner_id", "requeue_count") are not the
    ones this system uses. The real recovery path is
    runner._reap_zombie_tasks() -> agentic_repair.repair_patch(..., category=
    "orphaned-running") -> db.update, so these now assert against the patch
    repair_patch actually produces: state/account, remediation_count/attempt.
    """

    def _orphan(self, **overrides):
        task = {
            "id": "t1",
            "slug": "original-slug",
            "state": "RUNNING",
            "account": "Mac.lan-4171",      # the dead runner's claim
            "project": "test-project",
            "title": "Original title",
            "attempt": 1,
            "remediation_count": 2,
        }
        task.update(overrides)
        return task

    SIGNAL = "zombie-reaper: expired runner heartbeat"

    def test_recovery_resets_runner_id(self):
        """Recovery releases the dead runner's claim and re-queues the task."""
        # WAS: copied a dict, set runner_id=None/status="queued" by hand, then asserted
        # those two values. The claim is held in the `account` column (see
        # runner._reap_zombie_tasks, which matches dead runners by account), and it is
        # repair_patch that clears it.
        import agentic_repair

        patch_out = agentic_repair.repair_patch(
            self._orphan(), self.SIGNAL, category="orphaned-running")

        assert patch_out["account"] is None
        assert patch_out["state"] == "QUEUED"

    def test_recovery_preserves_task_metadata(self):
        """Recovery patches only what it changes, so project/title/slug survive."""
        # WAS: asserted that a dict copy still equalled the dict it was copied from.
        # The real guarantee is that the patch handed to db.update names no metadata
        # column at all — and, specifically, that `prompt` is omitted unless the caller
        # actually selected it (agentic_repair.py's note on sweeps destroying prompts).
        import agentic_repair

        task = self._orphan()
        patch_out = agentic_repair.repair_patch(
            task, self.SIGNAL, category="orphaned-running")

        for preserved in ("project", "title", "slug", "id", "prompt"):
            assert preserved not in patch_out, f"recovery must not rewrite {preserved}"

    def test_recovery_increments_requeue_count(self):
        """Recovery advances both repair counters, not just the one it was handed."""
        # WAS: task["requeue_count"] = task.get("requeue_count", 0) + 1 followed by an
        # assertion on that addition. There is no requeue_count column; the counters are
        # remediation_count and attempt, and both must advance or the ceilings below
        # never bind.
        import agentic_repair

        patch_out = agentic_repair.repair_patch(
            self._orphan(attempt=1, remediation_count=2), self.SIGNAL,
            category="orphaned-running")

        assert patch_out["remediation_count"] == 3
        assert patch_out["attempt"] == 2

    def test_recovery_max_requeue_threshold(self):
        """Past the ceiling the task is parked, not re-queued forever."""
        # WAS: an if-statement that set status="failed" when a hand-written counter hit
        # a hand-written max, then asserted on it. The real bound is
        # agentic_repair.GLOBAL_REPAIR_CEILING, and the terminal state is QUARANTINED
        # (parked for review) rather than FAILED.
        import agentic_repair

        at_ceiling = self._orphan(
            remediation_count=agentic_repair.GLOBAL_REPAIR_CEILING, attempt=9)
        patch_out = agentic_repair.repair_patch(
            at_ceiling, self.SIGNAL, category="orphaned-running")

        assert patch_out["state"] == "QUARANTINED"
        assert patch_out["account"] is None
        assert patch_out["note"].startswith(agentic_repair.TERMINAL_NOTE_PREFIX)
        # A parked task must not be handed back to a coder.
        assert "force_coder" not in patch_out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
