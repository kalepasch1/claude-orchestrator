"""Tests for runner.priority_queue — pinned express-lane task scheduling."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'runner'))

import pytest
from unittest.mock import patch, MagicMock

import priority_queue


class TestPriorityQueueClassification:
    """Test task classification (pinned vs normal)."""

    def test_classify_normal_task_when_disabled(self):
        """When ORCH_PRIORITY_QUEUE_ENABLED=false, all tasks are normal."""
        with patch.dict(os.environ, {"ORCH_PRIORITY_QUEUE_ENABLED": "false"}):
            pq = priority_queue.acquire()
            pq.invalidate()

            result = pq.classify_task({"slug": "recovery-001", "branch": "main"})
            assert result["is_pinned"] is False
            assert result["reason"] == "normal queue"

    def test_classify_pinned_task_by_slug_prefix(self):
        """Pinned prefix in slug makes task pinned."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery,breach-remediation"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            result = pq.classify_task({"slug": "recovery-fix-001", "branch": "main"})
            assert result["is_pinned"] is True
            assert result["reason"] == "matches pinned prefix"

    def test_classify_pinned_task_by_branch_prefix(self):
        """Pinned prefix in branch makes task pinned."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            result = pq.classify_task({"slug": "normal-task", "branch": "recovery-branch-2026-08-05"})
            assert result["is_pinned"] is True

    def test_classify_case_insensitive(self):
        """Prefix matching is case-insensitive."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "RECOVERY"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            result = pq.classify_task({"slug": "recovery-001", "branch": "main"})
            assert result["is_pinned"] is True

            result = pq.classify_task({"slug": "Recovery-Fix", "branch": "main"})
            assert result["is_pinned"] is True

    def test_classify_multiple_prefixes(self):
        """Multiple pinned prefixes are all matched."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery,breach-remediation,incident"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            assert pq.classify_task({"slug": "recovery-001", "branch": "main"})["is_pinned"]
            assert pq.classify_task({"slug": "breach-remediation-2026-08-05", "branch": "main"})["is_pinned"]
            assert pq.classify_task({"slug": "incident-response", "branch": "main"})["is_pinned"]
            assert not pq.classify_task({"slug": "normal-task", "branch": "main"})["is_pinned"]

    def test_classify_partial_prefix_requires_start(self):
        """Prefix match must be at the START of slug/branch."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            # This should NOT match (recovery is in the middle)
            result = pq.classify_task({"slug": "auto-recovery-001", "branch": "main"})
            assert result["is_pinned"] is False

    def test_classify_missing_fields_handled_gracefully(self):
        """Missing slug/branch fields don't crash classification."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            result = pq.classify_task({})
            assert result["is_pinned"] is False

            result = pq.classify_task({"slug": None})
            assert result["is_pinned"] is False

            result = pq.classify_task({"slug": ""})
            assert result["is_pinned"] is False

    def test_classify_empty_prefix_list_disables_pinning(self):
        """Empty ORCH_PINNED_TASK_PREFIXES means no tasks are pinned."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": ""
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            result = pq.classify_task({"slug": "recovery-001", "branch": "main"})
            assert result["is_pinned"] is False


class TestPriorityQueueDispatch:
    """Test task dispatch to queue lanes."""

    def test_dispatch_pinned_task_express_lane(self):
        """Pinned tasks get express lane (0 ms wait)."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            result = pq.dispatch({"slug": "recovery-001", "branch": "main"})
            assert result["lane"] == "express"
            assert result["pinned"] is True
            assert result["wait_ms"] == 0

    def test_dispatch_normal_task_normal_lane(self):
        """Normal tasks get normal lane (scheduler decides wait)."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            result = pq.dispatch({"slug": "normal-task", "branch": "main"})
            assert result["lane"] == "normal"
            assert result["pinned"] is False
            assert result["wait_ms"] is None

    def test_dispatch_increments_pinned_counter(self):
        """Dispatch increments total_pinned counter."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            stats_before = pq.stats()["total_pinned"]
            pq.dispatch({"slug": "recovery-001", "branch": "main"})
            pq.dispatch({"slug": "recovery-002", "branch": "main"})
            stats_after = pq.stats()["total_pinned"]

            assert stats_after == stats_before + 2

    def test_dispatch_disabled_ignores_prefixes(self):
        """When disabled, all tasks go normal even if they match prefixes."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "false",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            result = pq.dispatch({"slug": "recovery-001", "branch": "main"})
            assert result["lane"] == "normal"
            assert result["pinned"] is False


class TestPriorityQueueStats:
    """Test statistics collection."""

    def test_stats_enabled_flag(self):
        """Stats include enabled flag."""
        with patch.dict(os.environ, {"ORCH_PRIORITY_QUEUE_ENABLED": "true"}):
            pq = priority_queue.acquire()
            pq.invalidate()

            stats = pq.stats()
            assert stats["enabled"] is True

        with patch.dict(os.environ, {"ORCH_PRIORITY_QUEUE_ENABLED": "false"}):
            pq = priority_queue.acquire()
            pq.invalidate()

            stats = pq.stats()
            assert stats["enabled"] is False

    def test_stats_pinned_prefixes(self):
        """Stats include pinned prefixes."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery,breach-remediation"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            stats = pq.stats()
            assert "recovery" in stats["pinned_prefixes"]
            assert "breach-remediation" in stats["pinned_prefixes"]

    def test_stats_total_pinned_count(self):
        """Stats include total_pinned counter."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            pq.dispatch({"slug": "recovery-001", "branch": "main"})
            pq.dispatch({"slug": "recovery-002", "branch": "main"})

            stats = pq.stats()
            assert stats["total_pinned"] >= 2

    def test_stats_wait_time_averages(self):
        """Stats include average wait times for pinned and normal tasks."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            task_pinned = {"slug": "recovery-001", "branch": "main"}
            task_normal = {"slug": "normal-001", "branch": "main"}

            pq.record_wait_time(task_pinned, 50)
            pq.record_wait_time(task_pinned, 60)
            pq.record_wait_time(task_normal, 500)
            pq.record_wait_time(task_normal, 600)

            stats = pq.stats()
            assert stats["avg_pinned_wait_ms"] == 55.0
            assert stats["avg_normal_wait_ms"] == 550.0

    def test_stats_sample_counts(self):
        """Stats include sample counts."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            task_pinned = {"slug": "recovery-001", "branch": "main"}
            task_normal = {"slug": "normal-001", "branch": "main"}

            pq.record_wait_time(task_pinned, 50)
            pq.record_wait_time(task_pinned, 60)
            pq.record_wait_time(task_normal, 500)

            stats = pq.stats()
            assert stats["sample_count_pinned"] == 2
            assert stats["sample_count_normal"] == 1

    def test_stats_no_samples_returns_none(self):
        """When no wait time samples recorded, averages are None."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            stats = pq.stats()
            assert stats["avg_pinned_wait_ms"] is None
            assert stats["avg_normal_wait_ms"] is None


class TestPriorityQueueRecordWaitTime:
    """Test wait time recording."""

    def test_record_wait_time_valid_value(self):
        """Valid wait times are recorded."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            task = {"slug": "recovery-001", "branch": "main"}
            pq.record_wait_time(task, 100)

            stats = pq.stats()
            assert stats["avg_pinned_wait_ms"] == 100.0

    def test_record_wait_time_ignores_negative(self):
        """Negative wait times are ignored."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            task = {"slug": "recovery-001", "branch": "main"}
            pq.record_wait_time(task, -10)

            stats = pq.stats()
            assert stats["avg_pinned_wait_ms"] is None

    def test_record_wait_time_ignores_invalid_type(self):
        """Non-numeric wait times are ignored."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            task = {"slug": "recovery-001", "branch": "main"}
            pq.record_wait_time(task, "not a number")
            pq.record_wait_time(task, None)

            stats = pq.stats()
            assert stats["avg_pinned_wait_ms"] is None

    def test_record_wait_time_caps_samples(self):
        """Sample list caps at _max_samples to prevent memory leak."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()
            pq._max_samples = 10  # Set low for testing

            task = {"slug": "recovery-001", "branch": "main"}
            # Record 20 samples
            for i in range(20):
                pq.record_wait_time(task, i)

            stats = pq.stats()
            # Should only keep the most recent 10
            assert stats["sample_count_pinned"] == 10


class TestPriorityQueueThreadSafety:
    """Test thread-safety guarantees."""

    def test_concurrent_dispatch(self):
        """Multiple threads can dispatch concurrently without corruption."""
        import threading

        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            def dispatch_many():
                for i in range(100):
                    pq.dispatch({"slug": f"recovery-{i}", "branch": "main"})

            threads = [threading.Thread(target=dispatch_many) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            stats = pq.stats()
            assert stats["total_pinned"] == 500

    def test_concurrent_stats_read(self):
        """Multiple threads can read stats concurrently."""
        import threading

        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            results = []

            def read_stats():
                for _ in range(10):
                    results.append(pq.stats())

            threads = [threading.Thread(target=read_stats) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All reads should succeed
            assert len(results) == 50


class TestPriorityQueueConfigReloading:
    """Test config reload behavior."""

    def test_config_reload_ttl(self):
        """Config is not reloaded more than once per TTL."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()
            pq._config_ttl = 1  # 1 second TTL

            # First call loads config
            pq.stats()
            first_load_time = pq._last_config_load

            # Second call shortly after should NOT reload
            time.sleep(0.1)
            pq.stats()
            assert pq._last_config_load == first_load_time

            # After TTL expires, should reload
            time.sleep(1.1)
            pq.stats()
            assert pq._last_config_load > first_load_time

    def test_config_invalidation(self):
        """invalidate() forces config reload on next call."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()
            pq._config_ttl = 3600  # Long TTL

            pq.stats()
            first_load = pq._last_config_load

            time.sleep(0.1)
            pq.invalidate()
            pq.stats()
            assert pq._last_config_load > first_load


class TestPriorityQueueModuleLevel:
    """Test module-level convenience functions."""

    def test_module_classify_task(self):
        """classify_task() function delegates to singleton."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            priority_queue.acquire().invalidate()

            result = priority_queue.classify_task({"slug": "recovery-001", "branch": "main"})
            assert result["is_pinned"] is True

    def test_module_dispatch(self):
        """dispatch() function delegates to singleton."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            priority_queue.acquire().invalidate()

            result = priority_queue.dispatch({"slug": "recovery-001", "branch": "main"})
            assert result["pinned"] is True

    def test_module_stats(self):
        """stats() function delegates to singleton."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            priority_queue.acquire().invalidate()

            stats = priority_queue.stats()
            assert "enabled" in stats
            assert "total_pinned" in stats


class TestPriorityQueueEdgeCases:
    """Test edge cases and error conditions."""

    def test_whitespace_in_prefixes(self):
        """Whitespace around prefixes is stripped."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "  recovery , breach-remediation  , incident  "
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            # All three should be recognized
            assert pq.classify_task({"slug": "recovery-001", "branch": "main"})["is_pinned"]
            assert pq.classify_task({"slug": "breach-remediation-001", "branch": "main"})["is_pinned"]
            assert pq.classify_task({"slug": "incident-001", "branch": "main"})["is_pinned"]

    def test_malformed_config_fallback(self):
        """Malformed config doesn't crash; falls back gracefully."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "invalid-bool",
            "ORCH_PINNED_TASK_PREFIXES": ""
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            # Should not crash, just treat as disabled
            result = pq.dispatch({"slug": "recovery-001", "branch": "main"})
            assert result["lane"] == "normal"

    def test_config_not_set_defaults_to_disabled(self):
        """Missing config keys default to disabled/empty."""
        # Clear environment
        env_vars = {"ORCH_PRIORITY_QUEUE_ENABLED": "", "ORCH_PINNED_TASK_PREFIXES": ""}
        with patch.dict(os.environ, env_vars, clear=False):
            # Remove the keys if they exist
            for key in list(os.environ.keys()):
                if key in ("ORCH_PRIORITY_QUEUE_ENABLED", "ORCH_PINNED_TASK_PREFIXES"):
                    del os.environ[key]

            pq = priority_queue.acquire()
            pq.invalidate()

            stats = pq.stats()
            assert stats["enabled"] is False
            assert len(stats["pinned_prefixes"]) == 0

    def test_float_wait_time_conversion(self):
        """Float wait times are converted to int."""
        with patch.dict(os.environ, {
            "ORCH_PRIORITY_QUEUE_ENABLED": "true",
            "ORCH_PINNED_TASK_PREFIXES": "recovery"
        }):
            pq = priority_queue.acquire()
            pq.invalidate()

            task = {"slug": "recovery-001", "branch": "main"}
            pq.record_wait_time(task, 123.456)

            stats = pq.stats()
            # Should be recorded as 123, not 123.456
            assert stats["avg_pinned_wait_ms"] == 123.0
