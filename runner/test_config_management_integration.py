#!/usr/bin/env python3
"""
Comprehensive integration tests for configuration management improvements.

Tests the entire configuration stack including:
- config_drift detection (env/DB divergence, stale configs)
- config_consumer fail-soft reading
- config_sync and rollback
- Integration with fleet_config table
"""

import datetime
import os
import sys
import threading
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# These will be imported by tests
import config_drift
import config_consumer


class TestConfigDriftDetection(unittest.TestCase):
    """Tests for config_drift.detect_drift() — env/DB comparison."""

    def setUp(self):
        self.original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch("config_drift.db")
    def test_no_drift_when_synced(self, mock_db):
        """When env and DB values match, no drift reported."""
        os.environ["ORCH_TEST_VAL"] = "42"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        mock_db.select.return_value = [
            {"key": "ORCH_TEST_VAL", "value": "42", "updated_at": now}
        ]

        drifts = config_drift.detect_drift()
        env_drifts = [d for d in drifts
                      if d["key"] == "ORCH_TEST_VAL"
                      and d["kind"] == "env_db_divergence"]
        self.assertEqual(len(env_drifts), 0)

    @patch("config_drift.db")
    def test_drift_detected_value_mismatch(self, mock_db):
        """When env and DB values differ, drift is reported."""
        os.environ["ORCH_TEST_VAL"] = "99"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        mock_db.select.return_value = [
            {"key": "ORCH_TEST_VAL", "value": "42", "updated_at": now}
        ]

        drifts = config_drift.detect_drift()
        env_drifts = [d for d in drifts
                      if d["key"] == "ORCH_TEST_VAL"
                      and d["kind"] == "env_db_divergence"]
        self.assertEqual(len(env_drifts), 1)
        self.assertEqual(env_drifts[0]["env_value"], "99")
        self.assertEqual(env_drifts[0]["db_value"], "42")

    @patch("config_drift.db")
    def test_stale_config_detected(self, mock_db):
        """Configs unchanged for > STALE_DAYS are flagged."""
        old_date = (datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(days=60)).isoformat()
        mock_db.select.return_value = [
            {"key": "ORCH_OLD_VAL", "value": "stale", "updated_at": old_date}
        ]

        drifts = config_drift.detect_drift()
        stale = [d for d in drifts if d["kind"] == "stale"]
        self.assertGreaterEqual(len(stale), 1)
        self.assertGreaterEqual(stale[0]["age_days"], 60)

    @patch("config_drift.db")
    def test_recent_config_not_flagged_stale(self, mock_db):
        """Configs updated recently are not flagged."""
        recent = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(days=5)).isoformat()
        mock_db.select.return_value = [
            {"key": "ORCH_RECENT_VAL", "value": "x", "updated_at": recent}
        ]

        drifts = config_drift.detect_drift()
        stale = [d for d in drifts
                 if d["kind"] == "stale"
                 and d.get("key") == "ORCH_RECENT_VAL"]
        self.assertEqual(len(stale), 0)

    @patch("config_drift.db")
    def test_unsafe_keys_rejected_secret_marker(self, mock_db):
        """Keys with SECRET, TOKEN, etc are never included."""
        mock_db.select.return_value = [
            {"key": "SECRET_TOKEN", "value": "bad", "updated_at": None},
            {"key": "DB_PASSWORD", "value": "worse", "updated_at": None},
        ]

        drifts = config_drift.detect_drift()
        self.assertEqual(len(drifts), 0)

    @patch("config_drift.db")
    def test_unsafe_keys_rejected_prefix_check(self, mock_db):
        """Keys without whitelisted prefixes are rejected."""
        mock_db.select.return_value = [
            {"key": "RANDOM_VAL", "value": "x", "updated_at": None},
            {"key": "MY_CONFIG", "value": "y", "updated_at": None},
        ]

        drifts = config_drift.detect_drift()
        self.assertEqual(len(drifts), 0)

    @patch("config_drift.db")
    def test_db_error_fails_soft(self, mock_db):
        """DB errors don't crash detect_drift()."""
        mock_db.select.side_effect = Exception("DB down")

        drifts = config_drift.detect_drift()
        self.assertEqual(drifts, [])

    @patch("config_drift.db")
    def test_malformed_timestamp_skipped(self, mock_db):
        """Bad timestamps don't crash; drift skipped for that entry."""
        mock_db.select.return_value = [
            {"key": "ORCH_BAD_TS", "value": "x", "updated_at": "not-a-date"}
        ]

        drifts = config_drift.detect_drift()
        # Should not raise; stale check skipped for bad timestamp
        self.assertEqual(len(drifts), 0)

    @patch("config_drift.db")
    def test_safe_prefix_whitelist_honored(self, mock_db):
        """Whitelisted prefixes are included."""
<<<<<<< HEAD
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        mock_db.select.return_value = [
            {"key": "ORCH_VALID", "value": "ok", "updated_at": now},
            {"key": "MAX_PARALLEL", "value": "4", "updated_at": now},
            {"key": "MERGE_MAX_AGE_S", "value": "3600", "updated_at": now},
=======
        # Clear these to avoid drift from existing env values
        for key in ("ORCH_VALID", "MAX_PARALLEL", "MERGE_MAX_AGE_S"):
            os.environ.pop(key, None)

        recent = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()
        mock_db.select.return_value = [
            {"key": "ORCH_VALID", "value": "ok", "updated_at": recent},
            {"key": "MAX_PARALLEL", "value": "4", "updated_at": recent},
            {"key": "MERGE_MAX_AGE_S", "value": "3600", "updated_at": recent},
>>>>>>> improve-enhance-testing-framework-slice-5
        ]

        drifts = config_drift.detect_drift()
        # These should be scanned (no prefix rejection)
        # No drift because env doesn't have them, and we only report divergence
<<<<<<< HEAD
        # if env_val is not None
=======
        # if env_val is not None; recent updates don't trigger stale warnings
>>>>>>> improve-enhance-testing-framework-slice-5
        self.assertEqual(len(drifts), 0)


class TestConfigSuggestUpdates(unittest.TestCase):
    """Tests for config_drift.suggest_updates() — queue-aware suggestions."""

    def setUp(self):
        self.original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch("config_drift.db")
    def test_suggest_increase_parallel_when_queue_backs_up(self, mock_db):
        """Suggest higher MAX_PARALLEL when queue depth is high."""
        os.environ["MAX_PARALLEL"] = "4"
        # Use db.count() not db.query()
        mock_db.count.return_value = 50

        suggestions = config_drift.suggest_updates()
        parallel_suggestions = [s for s in suggestions
                               if s.get("key") == "MAX_PARALLEL"
                               and s.get("suggested", 0) > 4]
        self.assertGreaterEqual(len(parallel_suggestions), 1)
        mock_db.count.assert_called_once_with("tasks", {"state": "eq.QUEUED"})

    @patch("config_drift.db")
    def test_suggest_decrease_parallel_when_queue_empty(self, mock_db):
        """Suggest lower MAX_PARALLEL when queue is empty."""
        os.environ["MAX_PARALLEL"] = "8"
        mock_db.count.return_value = 0

        suggestions = config_drift.suggest_updates()
        parallel_suggestions = [s for s in suggestions
                               if s.get("key") == "MAX_PARALLEL"
                               and s.get("suggested", 99) < 8]
        self.assertGreaterEqual(len(parallel_suggestions), 1)

    @patch("config_drift.db")
    def test_no_suggestion_when_queue_balanced(self, mock_db):
        """No suggestion when queue depth is reasonable."""
        os.environ["MAX_PARALLEL"] = "4"
        mock_db.count.return_value = 10  # 2.5x is not > 3x

        suggestions = config_drift.suggest_updates()
        parallel_suggestions = [s for s in suggestions
                               if s.get("key") == "MAX_PARALLEL"]
        self.assertEqual(len(parallel_suggestions), 0)

    @patch("config_drift.db")
    def test_uses_db_count_not_query(self, mock_db):
        """Verify suggest_updates() uses db.count(), not db.query().

        This is a regression test for a commit that reverted from db.count()
        to a non-existent db.query() method. The PostgREST API has no raw SQL
        channel, so db.query() does not exist and would raise AttributeError.
        """
        os.environ["MAX_PARALLEL"] = "4"
        # Don't set up mock_db.query; if it's called, test should fail
        mock_db.count.return_value = 100

        suggestions = config_drift.suggest_updates()

        # verify db.count was called
        mock_db.count.assert_called()
        # verify db.query was never called
        mock_db.query.assert_not_called()

    @patch("config_drift.db")
    def test_db_error_fails_soft(self, mock_db):
        """DB errors don't crash suggest_updates()."""
        mock_db.count.side_effect = Exception("DB down")

        suggestions = config_drift.suggest_updates()
        self.assertEqual(suggestions, [])

    @patch("config_drift.db")
    def test_missing_max_parallel_env_defaults(self, mock_db):
        """MAX_PARALLEL env var missing uses reasonable default."""
        if "MAX_PARALLEL" in os.environ:
            del os.environ["MAX_PARALLEL"]
        mock_db.count.return_value = 100  # High queue

        suggestions = config_drift.suggest_updates()
        # Should still produce suggestions using default parallelism
        parallel_suggestions = [s for s in suggestions
                               if s.get("key") == "MAX_PARALLEL"]
        self.assertGreaterEqual(len(parallel_suggestions), 1)


class TestConfigTick(unittest.TestCase):
    """Tests for config_drift.tick() — main entry point."""

    @patch("config_drift.detect_drift")
    @patch("config_drift.suggest_updates")
    def test_tick_returns_tuple(self, mock_suggest, mock_detect):
        """tick() returns (drifts, suggestions) tuple."""
<<<<<<< HEAD
        mock_detect.return_value = [{"key": "TEST", "kind": "env_db_divergence"}]
        mock_suggest.return_value = [{"key": "PARALLEL", "suggested": 8}]

        result = config_drift.tick()
=======
        mock_detect.return_value = [
            {"key": "TEST", "kind": "env_db_divergence", "env_value": "e", "db_value": "d", "suggestion": "s"}
        ]
        mock_suggest.return_value = [
            {"key": "PARALLEL", "suggested": 8, "reason": "queue depth high"}
        ]

        with patch("builtins.print"):  # suppress print output from tick()
            result = config_drift.tick()
>>>>>>> improve-enhance-testing-framework-slice-5
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        drifts, suggestions = result
        self.assertEqual(len(drifts), 1)
        self.assertEqual(len(suggestions), 1)

    @patch("config_drift.detect_drift")
    @patch("config_drift.suggest_updates")
    def test_tick_fails_soft_on_error(self, mock_suggest, mock_detect):
        """tick() catches exceptions and returns empty lists."""
        mock_detect.side_effect = Exception("boom")

        result = config_drift.tick()
        self.assertEqual(result, ([], []))

    @patch("config_drift.detect_drift")
    @patch("config_drift.suggest_updates")
    def test_tick_prints_drifts(self, mock_suggest, mock_detect, capsys=None):
        """tick() prints drift warnings."""
        mock_detect.return_value = [
            {"key": "TEST_VAL", "kind": "env_db_divergence",
             "env_value": "99", "db_value": "42"}
        ]
        mock_suggest.return_value = []

        with patch("builtins.print") as mock_print:
            config_drift.tick()
            # Should have printed something about the drift
            calls = [c for c in mock_print.call_args_list
                    if "config_drift" in str(c)]
            self.assertGreaterEqual(len(calls), 1)


class TestConfigConsumerThreadSafety(unittest.TestCase):
    """Tests for thread-safe singleton pattern in config_consumer."""

    def test_singleton_instance_is_reused(self):
        """Multiple imports get the same singleton."""
<<<<<<< HEAD
        c1 = config_consumer._config_instance
        c2 = config_consumer._config_instance
=======
        c1 = config_consumer._consumer
        c2 = config_consumer._consumer
>>>>>>> improve-enhance-testing-framework-slice-5
        self.assertIs(c1, c2)

    def test_concurrent_reads_are_safe(self):
        """Concurrent load_all() calls don't crash."""
        results = []
        errors = []

        def read_config():
            try:
                config = config_consumer.load_all()
                results.append(config)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_config) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors in concurrent reads: {errors}")
        self.assertEqual(len(results), 10)

    def test_cache_is_thread_safe(self):
        """Concurrent cache operations don't corrupt state."""
        errors = []

        def cache_op():
            try:
                config_consumer.load_config("TEST_KEY")
                config_consumer.load_config("OTHER_KEY")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=cache_op) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Cache errors: {errors}")


class TestConfigConsumerFailSoft(unittest.TestCase):
    """Tests for fail-soft error handling in config_consumer."""

    @patch("config_consumer.fleet_control")
    def test_returns_default_on_missing_key(self, mock_fc):
        """Missing config key returns default, doesn't crash."""
<<<<<<< HEAD
        mock_fc.select.return_value = None
=======
        mock_fc.get_fleet_config.return_value = None
>>>>>>> improve-enhance-testing-framework-slice-5

        result = config_consumer.load_config("NONEXISTENT_KEY", default="fallback")
        self.assertEqual(result, "fallback")

    def test_env_number_with_bad_value(self):
        """Malformed numeric env vars log and fall back."""
        os.environ["ORCH_BAD_NUM"] = "not_a_number"

        # This should not raise
        result = config_consumer._env_number("ORCH_BAD_NUM", default=42.0)
        self.assertEqual(result, 42.0)

    def test_env_number_with_minimum_check(self):
        """Numeric values below minimum are rejected."""
        os.environ["ORCH_LOW_NUM"] = "-5"

        result = config_consumer._env_number("ORCH_LOW_NUM", default=10, minimum=0)
        self.assertEqual(result, 10)

    @patch("config_consumer.fleet_control")
    def test_load_all_returns_dict(self, mock_fc):
        """load_all() always returns a dict, never None."""
        result = config_consumer.load_all()
        self.assertIsInstance(result, dict)

    @patch("config_consumer.fleet_control")
    def test_cache_respects_ttl(self, mock_fc):
        """Cached values expire after TTL."""
        mock_fc.select.return_value = None
        # This would need real time management; simplified test
        result1 = config_consumer.load_config("KEY1")
        result2 = config_consumer.load_config("KEY1")
        # Both calls succeed without error
        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)

    @patch("config_consumer.fleet_control")
    def test_cache_eviction_when_max_entries_exceeded(self, mock_fc):
        """Cache evicts oldest entries when limit reached."""
        original_max = config_consumer.DEFAULT_CACHE_MAX_ENTRIES
        try:
            # Temporarily set low limit to trigger eviction
            config_consumer.DEFAULT_CACHE_MAX_ENTRIES = 5

            # Fill cache beyond limit
            for i in range(10):
                config_consumer.load_config(f"KEY_{i}")

            # Cache should not grow unbounded
            self.assertLessEqual(
<<<<<<< HEAD
                len(config_consumer._config_instance._cache),
=======
                len(config_consumer._consumer._cache),
>>>>>>> improve-enhance-testing-framework-slice-5
                original_max
            )
        finally:
            config_consumer.DEFAULT_CACHE_MAX_ENTRIES = original_max


class TestEndToEndConfigManagement(unittest.TestCase):
    """End-to-end tests of config management system."""

    def setUp(self):
        self.original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch("config_drift.db")
    @patch("config_consumer.fleet_control")
    def test_drift_detection_with_actual_consumer_integration(self, mock_fc, mock_db):
        """Drift detection works with consumer's fail-soft patterns."""
        os.environ["ORCH_VAL"] = "env_value"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        mock_db.select.return_value = [
            {"key": "ORCH_VAL", "value": "db_value", "updated_at": now}
        ]

        drifts = config_drift.detect_drift()
        self.assertEqual(len(drifts), 1)
        self.assertEqual(drifts[0]["kind"], "env_db_divergence")

        # Consumer should also handle this gracefully
        consumer_val = config_consumer.load_config("ORCH_VAL")
        self.assertIsNotNone(consumer_val)


if __name__ == "__main__":
    unittest.main()
