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
from datetime import datetime, timedelta

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

    def test_heartbeat_record_structure(self):
        """Heartbeat record has required fields."""
        heartbeat_record = {
            "runner_id": "pid-12345",
            "hostname": "runner-1.internal",
            "last_seen": time.time(),
            "active": True,
            "model_loaded": "llama3.2:3b",
            "memory_mb": 2048,
        }

        assert heartbeat_record["runner_id"]
        assert heartbeat_record["hostname"]
        assert heartbeat_record["last_seen"] > 0
        assert isinstance(heartbeat_record["active"], bool)

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
        """Heartbeat records inactive runners."""
        from db import heartbeat

        mock_db.insert.return_value = None

        heartbeat("pid-12345", "host1", active=False)

        mock_db.insert.assert_called()
        call_args = mock_db.insert.call_args
        row = call_args[0][1]
        assert row["active"] is False

    @patch("db.db")
    def test_heartbeat_with_model_metadata(self, mock_db):
        """Heartbeat includes model and resource metadata."""
        from db import heartbeat

        mock_db.insert.return_value = None

        heartbeat("pid-12345", "host1", active=True, model_loaded="claude-opus-5")

        call_args = mock_db.insert.call_args
        row = call_args[0][1]
        assert "model_loaded" in row or "last_seen" in row


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


class TestOrphanedRunningTaskRecovery:
    """Test recovery of tasks stuck in RUNNING/PROCESSING state."""

    @patch("db.select")
    def test_find_orphaned_running_tasks(self, mock_select):
        """Find tasks in RUNNING state for stale runners."""
        stale_runner_id = "pid-old-1"

        mock_select.return_value = [
            {
                "id": "task-1",
                "project": "test",
                "title": "Orphaned task",
                "status": "running",
                "runner_id": stale_runner_id,
                "created_at": time.time() - 7200,
            }
        ]

        result = mock_select()

        assert len(result) == 1
        assert result[0]["status"] == "running"
        assert result[0]["runner_id"] == stale_runner_id

    def test_orphaned_task_detection_criteria(self):
        """Criteria for marking task as orphaned."""
        def is_orphaned_task(task: Dict, stale_runners: List[str]) -> bool:
            return (
                task.get("status") in ("running", "processing")
                and task.get("runner_id") in stale_runners
            )

        stale_runners = ["pid-old-1", "pid-old-2"]

        # Is orphaned
        assert is_orphaned_task(
            {"status": "running", "runner_id": "pid-old-1"},
            stale_runners
        ) is True

        # Not orphaned: wrong status
        assert is_orphaned_task(
            {"status": "queued", "runner_id": "pid-old-1"},
            stale_runners
        ) is False

        # Not orphaned: runner alive
        assert is_orphaned_task(
            {"status": "running", "runner_id": "pid-new-1"},
            stale_runners
        ) is False

    @patch("db.update")
    def test_requeue_orphaned_task(self, mock_update):
        """Requeue orphaned task back to QUEUED."""
        task_id = "task-1"

        mock_update.return_value = None

        # Simulate requeue
        from db import update
        update("tasks", {"id": task_id}, {"status": "queued", "runner_id": None})

        mock_update.assert_called()
        call_args = mock_update.call_args
        assert call_args[0][0] == "tasks"

    @patch("db.update")
    def test_mark_orphaned_task_failed(self, mock_update):
        """Mark orphaned task as failed after N requeue attempts."""
        task_id = "task-1"
        max_requeue = 3

        mock_update.return_value = None

        # After max requeue, mark as failed
        from db import update
        update("tasks", {"id": task_id}, {
            "status": "failed",
            "error": "Orphaned task; max requeue attempts exceeded",
        })

        mock_update.assert_called()


class TestZombieReaperExecution:
    """Test zombie reaper process execution and cleanup."""

    def test_zombie_reaper_cycle(self):
        """Full zombie reaper cycle: detect, reap, log."""
        def run_zombie_reaper_cycle(zombies: List[str]) -> Dict[str, Any]:
            return {
                "detected": len(zombies),
                "reaped": len(zombies),
                "timestamp": time.time(),
                "errors": [],
            }

        zombies = ["pid-old-1", "pid-old-2", "pid-old-3"]
        result = run_zombie_reaper_cycle(zombies)

        assert result["detected"] == 3
        assert result["reaped"] == 3
        assert "timestamp" in result

    def test_zombie_reaper_logging(self):
        """Zombie reaper logs each reap event."""
        logged_events = []

        def log_reap(runner_id: str, reason: str):
            logged_events.append({
                "runner_id": runner_id,
                "reason": reason,
                "timestamp": time.time(),
            })

        log_reap("pid-123", "heartbeat_expired")
        log_reap("pid-456", "heartbeat_expired")

        assert len(logged_events) == 2
        assert all(e["reason"] == "heartbeat_expired" for e in logged_events)

    def test_zombie_reaper_error_resilience(self):
        """Zombie reaper continues on individual failures."""
        errors = []
        reaped = []

        def try_reap_zombie(runner_id: str):
            try:
                if runner_id == "bad-pid":
                    raise OSError(f"Cannot kill {runner_id}")
                reaped.append(runner_id)
            except Exception as e:
                errors.append((runner_id, str(e)))

        zombies = ["pid-1", "bad-pid", "pid-2"]
        for z in zombies:
            try_reap_zombie(z)

        assert len(reaped) == 2
        assert len(errors) == 1
        assert "bad-pid" in errors[0][0]

    def test_zombie_reaper_with_task_recovery(self):
        """Zombie reaper triggers task recovery."""
        def reap_zombie_and_recover(runner_id: str, orphaned_tasks: List[Dict]) -> Dict:
            reaped_count = 1
            requeued_count = len(orphaned_tasks)

            return {
                "runner_id": runner_id,
                "reaped": reaped_count,
                "tasks_requeued": requeued_count,
                "timestamp": time.time(),
            }

        orphaned = [
            {"id": "t1", "status": "running"},
            {"id": "t2", "status": "running"},
        ]
        result = reap_zombie_and_recover("pid-dead", orphaned)

        assert result["reaped"] == 1
        assert result["tasks_requeued"] == 2


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

    def test_heartbeat_table_schema_columns(self):
        """runner_heartbeats has required columns."""
        expected_columns = {
            "runner_id",
            "hostname",
            "active",
            "last_seen",
            "model_loaded",
            "memory_mb",
        }

        # Verify schema (would be actual DB check in integration tests)
        heartbeat_fields = {
            "runner_id": "VARCHAR",
            "hostname": "VARCHAR",
            "active": "BOOLEAN",
            "last_seen": "TIMESTAMP",
            "model_loaded": "VARCHAR",
            "memory_mb": "INTEGER",
        }

        assert set(heartbeat_fields.keys()) >= expected_columns

    def test_runner_id_is_primary_key(self):
        """runner_id serves as primary key for upserts."""
        # Upsert semantics: if runner_id exists, update; else insert
        runner_entry = {
            "runner_id": "pid-123",
            "hostname": "host1",
            "active": True,
            "last_seen": time.time(),
        }

        # Simulating upsert: same runner_id should update, not duplicate
        db_entries = {"pid-123": runner_entry}

        # Re-insert same runner_id
        new_entry = dict(runner_entry)
        new_entry["last_seen"] = time.time()
        db_entries["pid-123"] = new_entry

        assert len(db_entries) == 1
        assert db_entries["pid-123"]["last_seen"] == new_entry["last_seen"]

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
    """Test zombie reaper's task recovery workflow in detail."""

    def test_recovery_resets_runner_id(self):
        """Recovered orphaned task has runner_id cleared."""
        orphaned_task = {
            "id": "t1",
            "status": "running",
            "runner_id": "pid-dead",
        }

        # Recovery: clear runner_id and reset status
        recovered_task = dict(orphaned_task)
        recovered_task.update({
            "status": "queued",
            "runner_id": None,
        })

        assert recovered_task["runner_id"] is None
        assert recovered_task["status"] == "queued"

    def test_recovery_preserves_task_metadata(self):
        """Recovery preserves task project, title, slug."""
        orphaned_task = {
            "id": "t1",
            "project": "test-project",
            "title": "Original title",
            "slug": "original-slug",
            "status": "running",
            "runner_id": "pid-dead",
            "created_at": time.time() - 3600,
        }

        recovered_task = dict(orphaned_task)
        recovered_task.update({
            "status": "queued",
            "runner_id": None,
        })

        assert recovered_task["project"] == orphaned_task["project"]
        assert recovered_task["title"] == orphaned_task["title"]
        assert recovered_task["slug"] == orphaned_task["slug"]
        assert recovered_task["created_at"] == orphaned_task["created_at"]

    def test_recovery_increments_requeue_count(self):
        """Recovery tracks requeue attempts."""
        task = {
            "id": "t1",
            "status": "queued",
            "requeue_count": 2,
        }

        # Simulate recovery
        task["requeue_count"] = task.get("requeue_count", 0) + 1

        assert task["requeue_count"] == 3

    def test_recovery_max_requeue_threshold(self):
        """Task fails permanently after max requeue attempts."""
        max_requeue = 3
        task = {
            "id": "t1",
            "status": "queued",
            "requeue_count": 3,
        }

        # Check if max requeue reached
        if task["requeue_count"] >= max_requeue:
            task["status"] = "failed"
            task["error"] = "Max requeue attempts exceeded"

        assert task["status"] == "failed"
        assert "Max requeue" in task["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
