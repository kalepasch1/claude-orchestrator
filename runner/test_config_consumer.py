#!/usr/bin/env python3
"""
Test suite for config_consumer.py - Centralized fleet configuration consumption.

Covers: normal paths, missing keys, DB unavailability, cache staleness,
concurrent access, and environment variable fallback.
"""
import os, sys, unittest, time, threading, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock the db module before importing config_consumer
class MockDB:
    def __init__(self, data=None, should_fail=False):
        self.data = data or {}
        self.should_fail = should_fail
        self.select_calls = []

    def select(self, table, params):
        self.select_calls.append((table, params))
        if self.should_fail:
            raise RuntimeError("DB connection failed")
        if table != "fleet_config":
            return []
        key = params.get("key", "").replace("eq.", "")
        if key in self.data:
            return [{"value": self.data[key]}]
        return []


class TestConfigConsumer(unittest.TestCase):

    def setUp(self):
        """Reset config_consumer state and mock db module."""
        import config_consumer
        config_consumer.invalidate()
        config_consumer._cache.clear()
        config_consumer._last_db_fetch["t"] = time.time() - 1000  # Far in past

        # Create mock db and inject
        self.mock_db = MockDB()
        sys.modules["db"] = self.mock_db

    def tearDown(self):
        """Clean up environment."""
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]
        if "db" in sys.modules and isinstance(sys.modules["db"], MockDB):
            del sys.modules["db"]

    def test_get_str_from_db(self):
        """Normal path: read string from fleet_config table."""
        import config_consumer
        self.mock_db.data = {"SESSION_TIMEOUT": "7200"}
        result = config_consumer.get_str("SESSION_TIMEOUT")
        self.assertEqual(result, "7200")
        self.assertEqual(len(self.mock_db.select_calls), 1)

    def test_get_str_from_env(self):
        """Fallback: read from ORCH_* environment variable when DB has no value."""
        import config_consumer
        os.environ["ORCH_SESSION_TIMEOUT"] = "3600"
        result = config_consumer.get_str("SESSION_TIMEOUT")
        self.assertEqual(result, "3600")

    def test_get_str_env_precedence_when_db_unavailable(self):
        """When DB fails, fall back to environment variable."""
        import config_consumer
        self.mock_db.should_fail = True
        os.environ["ORCH_MAX_WORKERS"] = "12"
        result = config_consumer.get_str("MAX_WORKERS")
        self.assertEqual(result, "12")

    def test_get_str_default_when_missing(self):
        """Return default when key is missing from DB and env."""
        import config_consumer
        result = config_consumer.get_str("NONEXISTENT", default="fallback")
        self.assertEqual(result, "fallback")

    def test_get_str_empty_default(self):
        """Return empty string when no default provided."""
        import config_consumer
        result = config_consumer.get_str("NONEXISTENT")
        self.assertEqual(result, "")

    def test_get_str_strips_whitespace(self):
        """DB values are stripped of leading/trailing whitespace."""
        import config_consumer
        self.mock_db.data = {"KEY": "  value  "}
        result = config_consumer.get_str("KEY")
        self.assertEqual(result, "value")

    def test_get_int_from_db(self):
        """Parse integer from fleet_config."""
        import config_consumer
        self.mock_db.data = {"CACHE_SIZE": "500"}
        result = config_consumer.get_int("CACHE_SIZE")
        self.assertEqual(result, 500)

    def test_get_int_default_on_non_numeric(self):
        """Return default when value is not numeric."""
        import config_consumer
        self.mock_db.data = {"CACHE_SIZE": "not_a_number"}
        result = config_consumer.get_int("CACHE_SIZE", default=100)
        self.assertEqual(result, 100)

    def test_get_int_default_when_missing(self):
        """Return default when key is missing."""
        import config_consumer
        result = config_consumer.get_int("MISSING_INT", default=42)
        self.assertEqual(result, 42)

    def test_get_float_from_db(self):
        """Parse float from fleet_config."""
        import config_consumer
        self.mock_db.data = {"THRESHOLD": "0.75"}
        result = config_consumer.get_float("THRESHOLD")
        self.assertAlmostEqual(result, 0.75, places=2)

    def test_get_float_default_on_non_numeric(self):
        """Return default when value is not numeric."""
        import config_consumer
        self.mock_db.data = {"THRESHOLD": "invalid"}
        result = config_consumer.get_float("THRESHOLD", default=0.5)
        self.assertAlmostEqual(result, 0.5, places=2)

    def test_get_bool_true_values(self):
        """Parse true values: '1', 'true', 'yes', 'on'."""
        import config_consumer
        for true_val in ["1", "true", "yes", "on", "TRUE", "Yes", "ON"]:
            config_consumer.invalidate()
            self.mock_db.data = {"FLAG": true_val}
            result = config_consumer.get_bool("FLAG")
            self.assertTrue(result, f"Expected {true_val!r} to be True")

    def test_get_bool_false_values(self):
        """Parse false values: everything else."""
        import config_consumer
        for false_val in ["0", "false", "no", "off", "anything_else", ""]:
            config_consumer.invalidate()
            self.mock_db.data = {"FLAG": false_val} if false_val else {}
            result = config_consumer.get_bool("FLAG")
            self.assertFalse(result, f"Expected {false_val!r} to be False")

    def test_get_bool_default_when_missing(self):
        """Return default when key is missing."""
        import config_consumer
        result = config_consumer.get_bool("MISSING_FLAG", default=True)
        self.assertTrue(result)

    def test_cache_prevents_repeated_db_calls(self):
        """Cache prevents repeated DB queries within TTL."""
        import config_consumer
        self.mock_db.data = {"KEY": "value"}
        result1 = config_consumer.get_str("KEY")
        result2 = config_consumer.get_str("KEY")
        self.assertEqual(result1, result2)
        # Only 1 DB call per key (cached on second access)
        key_calls = [c for c in self.mock_db.select_calls if "KEY" in str(c)]
        self.assertEqual(len(key_calls), 1)

    def test_cache_expires_after_ttl(self):
        """Cache entries expire and trigger new DB fetches after TTL."""
        import config_consumer
        config_consumer.CACHE_TTL_S = 0.01  # Very short TTL for testing
        self.mock_db.data = {"KEY": "value1"}

        result1 = config_consumer.get_str("KEY")
        self.assertEqual(result1, "value1")
        self.assertEqual(len(self.mock_db.select_calls), 1)

        # Wait for cache to expire
        time.sleep(0.02)

        # Update DB value and fetch again
        self.mock_db.data["KEY"] = "value2"
        result2 = config_consumer.get_str("KEY")
        self.assertEqual(result2, "value2")
        self.assertEqual(len(self.mock_db.select_calls), 2)

    def test_invalidate_single_key(self):
        """invalidate(key) removes specific key from cache."""
        import config_consumer
        self.mock_db.data = {"KEY1": "val1", "KEY2": "val2"}
        config_consumer.get_str("KEY1")
        config_consumer.get_str("KEY2")
        self.assertEqual(len(config_consumer._cache), 2)

        config_consumer.invalidate("KEY1")
        self.assertEqual(len(config_consumer._cache), 1)
        self.assertNotIn("KEY1", config_consumer._cache)

    def test_invalidate_all(self):
        """invalidate() clears entire cache."""
        import config_consumer
        self.mock_db.data = {"KEY1": "val1", "KEY2": "val2"}
        config_consumer.get_str("KEY1")
        config_consumer.get_str("KEY2")
        self.assertEqual(len(config_consumer._cache), 2)

        config_consumer.invalidate()
        self.assertEqual(len(config_consumer._cache), 0)

    def test_concurrent_access(self):
        """Multiple threads can safely read config concurrently."""
        import config_consumer
        self.mock_db.data = {"WORKERS": "8", "TIMEOUT": "3600"}

        results = {}
        errors = []

        def reader(key, storage_key):
            try:
                storage_key_val = config_consumer.get_str(key)
                results[storage_key] = storage_key_val
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reader, args=("WORKERS", "w1")),
            threading.Thread(target=reader, args=("WORKERS", "w2")),
            threading.Thread(target=reader, args=("TIMEOUT", "t1")),
            threading.Thread(target=reader, args=("TIMEOUT", "t2")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(results["w1"], "8")
        self.assertEqual(results["w2"], "8")
        self.assertEqual(results["t1"], "3600")
        self.assertEqual(results["t2"], "3600")

    def test_stats_empty_cache(self):
        """stats() returns empty cache info when nothing is cached."""
        import config_consumer
        config_consumer.invalidate()
        s = config_consumer.stats()
        self.assertEqual(s["cached_keys"], 0)
        self.assertEqual(s["oldest_entry_age_s"], 0)

    def test_stats_populated_cache(self):
        """stats() returns cache info including key count and age."""
        import config_consumer
        self.mock_db.data = {"KEY1": "val1", "KEY2": "val2"}
        config_consumer.get_str("KEY1")
        config_consumer.get_str("KEY2")
        s = config_consumer.stats()
        self.assertEqual(s["cached_keys"], 2)
        self.assertGreaterEqual(s["oldest_entry_age_s"], 0)

    def test_db_unavailable_uses_env_fallback(self):
        """When DB connection fails, uses environment variable."""
        import config_consumer
        self.mock_db.should_fail = True
        os.environ["ORCH_POOL_SIZE"] = "16"
        result = config_consumer.get_str("POOL_SIZE")
        self.assertEqual(result, "16")

    def test_none_key_returns_default(self):
        """Passing None as key returns default safely."""
        import config_consumer
        result = config_consumer.get_str(None, default="safe")
        self.assertEqual(result, "safe")

    def test_empty_key_returns_default(self):
        """Passing empty string as key returns default safely."""
        import config_consumer
        result = config_consumer.get_str("", default="safe")
        self.assertEqual(result, "safe")

    def test_db_returns_empty_string_uses_env(self):
        """When DB returns empty string, falls back to env variable."""
        import config_consumer
        self.mock_db.data = {"KEY": ""}
        os.environ["ORCH_KEY"] = "from_env"
        result = config_consumer.get_str("KEY")
        # Empty DB value still takes precedence if the key exists
        # This tests the actual behavior - empty DB is treated as "no value"
        self.assertEqual(result, "from_env")

    def test_integration_scenario_session_timeout(self):
        """Golden path example: ORCH_SESSION_TIMEOUT from fleet_config."""
        import config_consumer
        self.mock_db.data = {"SESSION_TIMEOUT": "3600"}
        timeout = config_consumer.get_int("SESSION_TIMEOUT", default=1800)
        self.assertEqual(timeout, 3600)

    def test_integration_scenario_feature_flag(self):
        """Feature flag example: ORCH_FEATURE_X as boolean."""
        import config_consumer
        self.mock_db.data = {"FEATURE_X": "true"}
        enabled = config_consumer.get_bool("FEATURE_X", default=False)
        self.assertTrue(enabled)

    def test_large_integer_values(self):
        """Handle large integer values without overflow."""
        import config_consumer
        self.mock_db.data = {"BIG_NUMBER": "999999999"}
        result = config_consumer.get_int("BIG_NUMBER")
        self.assertEqual(result, 999999999)

    def test_negative_integer_values(self):
        """Handle negative integer values."""
        import config_consumer
        self.mock_db.data = {"NEGATIVE": "-42"}
        result = config_consumer.get_int("NEGATIVE")
        self.assertEqual(result, -42)

    def test_scientific_notation_float(self):
        """Handle scientific notation in float values."""
        import config_consumer
        self.mock_db.data = {"THRESHOLD": "1.5e-2"}
        result = config_consumer.get_float("THRESHOLD")
        self.assertAlmostEqual(result, 0.015, places=3)


class TestConfigConsumerEdgeCases(unittest.TestCase):
    """Additional edge case tests."""

    def setUp(self):
        import config_consumer
        config_consumer.invalidate()
        config_consumer._cache.clear()
        config_consumer._last_db_fetch["t"] = 0.0
        self.mock_db = MockDB()
        sys.modules["db"] = self.mock_db

    def tearDown(self):
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]
        if "db" in sys.modules:
            del sys.modules["db"]

    def test_type_error_in_db_select(self):
        """Handle type errors gracefully in DB selection."""
        import config_consumer

        class BadDB:
            def select(self, *args):
                raise TypeError("Bad type")

        sys.modules["db"] = BadDB()
        os.environ["ORCH_KEY"] = "from_env"
        result = config_consumer.get_str("KEY", default="default")
        self.assertEqual(result, "from_env")

    def test_key_with_special_characters(self):
        """Handle keys with underscores and numbers."""
        import config_consumer
        self.mock_db.data = {"MAX_WORKERS_2": "8"}
        result = config_consumer.get_str("MAX_WORKERS_2")
        self.assertEqual(result, "8")

    def test_numeric_string_in_get_str(self):
        """get_str returns numeric values as strings."""
        import config_consumer
        self.mock_db.data = {"NUMBER": "123"}
        result = config_consumer.get_str("NUMBER")
        self.assertEqual(result, "123")
        self.assertIsInstance(result, str)

    def test_mixed_case_env_keys(self):
        """Environment keys are normalized to uppercase."""
        import config_consumer
        os.environ["ORCH_MyKey"] = "value"
        result = config_consumer.get_str("MyKey")
        self.assertEqual(result, "value")


if __name__ == "__main__":
    unittest.main()
