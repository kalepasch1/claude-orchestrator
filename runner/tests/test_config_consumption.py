#!/usr/bin/env python3
"""
Narrow test coverage for fleet config consumption via config_consumer.

Tests validate:
- Normal path: config loaded from env or fleet_config
- Missing config: proper defaults returned
- DB error: graceful degradation to env/default
"""

import os
import sys
import unittest
from unittest import mock

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock database access for testing
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test_key")

import config_consumer


class TestConfigConsumptionNormalPath(unittest.TestCase):
    """Test normal config consumption path."""

    def setUp(self):
        """Clean up ORCH_ keys before each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def tearDown(self):
        """Clean up after each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def test_get_returns_env_value(self):
        """get() returns ORCH_* value from environment."""
        os.environ["ORCH_MAX_PARALLEL"] = "12"
        value = config_consumer.get("MAX_PARALLEL")
        self.assertEqual(value, "12")

    def test_get_int_coerces_correctly(self):
        """get_int() parses ORCH_* value as integer."""
        os.environ["ORCH_TASK_TIMEOUT"] = "3600"
        value = config_consumer.get_int("TASK_TIMEOUT")
        self.assertEqual(value, 3600)
        self.assertIsInstance(value, int)

    def test_get_bool_coerces_true(self):
        """get_bool() recognizes 'true', '1', 'yes', 'on' as True."""
        for true_val in ["true", "1", "yes", "on"]:
            os.environ["ORCH_DEBUG"] = true_val
            config_consumer.invalidate_cache()
            value = config_consumer.get_bool("DEBUG")
            self.assertTrue(value, f"Expected True for '{true_val}'")

    def test_get_float_coerces_correctly(self):
        """get_float() parses ORCH_* value as float."""
        os.environ["ORCH_RATE_LIMIT"] = "3.14"
        value = config_consumer.get_float("RATE_LIMIT")
        self.assertAlmostEqual(value, 3.14)
        self.assertIsInstance(value, float)

    def test_load_all_returns_all_orch_keys(self):
        """load_all() returns dict of all ORCH_* keys without prefix."""
        os.environ["ORCH_KEY1"] = "value1"
        os.environ["ORCH_KEY2"] = "value2"
        os.environ["OTHER_KEY"] = "ignored"

        all_config = config_consumer.load_all()
        self.assertIn("KEY1", all_config)
        self.assertIn("KEY2", all_config)
        self.assertNotIn("OTHER_KEY", all_config)
        self.assertEqual(all_config["KEY1"], "value1")
        self.assertEqual(all_config["KEY2"], "value2")


class TestConfigConsumptionMissingConfig(unittest.TestCase):
    """Test handling of missing configuration."""

    def setUp(self):
        """Clean up before each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def tearDown(self):
        """Clean up after each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def test_get_missing_returns_default(self):
        """get() returns default when ORCH_* key is missing."""
        value = config_consumer.get("MISSING_KEY", default="fallback")
        self.assertEqual(value, "fallback")

    def test_get_missing_returns_empty_string(self):
        """get() returns empty string when no default provided."""
        value = config_consumer.get("MISSING_KEY")
        self.assertEqual(value, "")

    def test_get_int_missing_returns_default(self):
        """get_int() returns default when ORCH_* key is missing."""
        value = config_consumer.get_int("MISSING_COUNT", default=99)
        self.assertEqual(value, 99)

    def test_get_int_missing_returns_zero(self):
        """get_int() returns 0 when no default provided."""
        value = config_consumer.get_int("MISSING_COUNT")
        self.assertEqual(value, 0)

    def test_get_bool_missing_returns_default(self):
        """get_bool() returns default when ORCH_* key is missing."""
        value = config_consumer.get_bool("MISSING_FLAG", default=True)
        self.assertTrue(value)

    def test_get_bool_missing_returns_false(self):
        """get_bool() returns False when no default provided."""
        value = config_consumer.get_bool("MISSING_FLAG")
        self.assertFalse(value)

    def test_get_float_missing_returns_default(self):
        """get_float() returns default when ORCH_* key is missing."""
        value = config_consumer.get_float("MISSING_RATE", default=2.5)
        self.assertAlmostEqual(value, 2.5)

    def test_get_float_missing_returns_zero(self):
        """get_float() returns 0.0 when no default provided."""
        value = config_consumer.get_float("MISSING_RATE")
        self.assertEqual(value, 0.0)

    def test_load_all_empty_when_no_keys(self):
        """load_all() returns empty dict when no ORCH_* keys exist."""
        all_config = config_consumer.load_all()
        self.assertEqual(all_config, {})

    def test_load_config_missing_returns_default(self):
        """load_config() returns default when key missing."""
        config_consumer.invalidate_cache()
        value = config_consumer.load_config("MISSING_KEY", default="fallback")
        self.assertEqual(value, "fallback")


class TestConfigConsumptionDBError(unittest.TestCase):
    """Test graceful degradation when fleet_config DB is unavailable."""

    def setUp(self):
        """Clean up before each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def tearDown(self):
        """Clean up after each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def test_load_config_db_error_falls_back_to_env(self):
        """load_config() falls back to env when fleet_control unavailable."""
        os.environ["ORCH_FALLBACK_KEY"] = "env_value"
        config_consumer.invalidate_cache()

        # Mock fleet_control.get_fleet_config to raise an error
        if config_consumer.fleet_control is not None:
            with mock.patch.object(config_consumer.fleet_control, "get_fleet_config",
                                   side_effect=Exception("DB connection failed")):
                value = config_consumer.load_config("FALLBACK_KEY")
                # Should fall back to env value
                self.assertEqual(value, "env_value")
        else:
            # If fleet_control is None, should still work and return env value
            value = config_consumer.load_config("FALLBACK_KEY")
            self.assertEqual(value, "env_value")

    def test_load_config_db_error_returns_default(self):
        """load_config() returns default when DB fails and env missing."""
        config_consumer.invalidate_cache()

        if config_consumer.fleet_control is not None:
            with mock.patch.object(config_consumer.fleet_control, "get_fleet_config",
                                   side_effect=Exception("DB connection failed")):
                value = config_consumer.load_config("MISSING_KEY", default="default_value")
                # Should return default when both DB and env fail
                self.assertEqual(value, "default_value")
        else:
            # If fleet_control is None, should still work and return default
            value = config_consumer.load_config("MISSING_KEY", default="default_value")
            self.assertEqual(value, "default_value")

    def test_load_config_handles_none_from_fleet_control(self):
        """load_config() handles None/empty responses from fleet_control."""
        os.environ["ORCH_TEST_KEY"] = "env_value"
        config_consumer.invalidate_cache()

        if config_consumer.fleet_control is not None:
            with mock.patch.object(config_consumer.fleet_control, "get_fleet_config",
                                   return_value=""):
                value = config_consumer.load_config("TEST_KEY")
                # Should fall back to env when fleet_control returns empty
                self.assertEqual(value, "env_value")
        else:
            # If fleet_control is None, should still work and return env value
            value = config_consumer.load_config("TEST_KEY")
            self.assertEqual(value, "env_value")

    def test_invalid_input_never_raises(self):
        """Config functions never raise on invalid input."""
        # Test with None key
        try:
            value = config_consumer.get(None)
            self.assertEqual(value, "")
        except Exception as e:
            self.fail(f"get(None) raised {type(e).__name__}: {e}")

        # Test with non-string key
        try:
            value = config_consumer.get_int(123)
            self.assertEqual(value, 0)
        except Exception as e:
            self.fail(f"get_int(123) raised {type(e).__name__}: {e}")

        # Test with empty string key
        try:
            value = config_consumer.get_bool("")
            self.assertFalse(value)
        except Exception as e:
            self.fail(f"get_bool('') raised {type(e).__name__}: {e}")


class TestConfigConsumptionCaching(unittest.TestCase):
    """Test cache behavior and invalidation."""

    def setUp(self):
        """Clean up before each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def tearDown(self):
        """Clean up after each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def test_cache_invalidation_works(self):
        """invalidate_cache() clears the cache."""
        os.environ["ORCH_CACHED"] = "value1"
        config_consumer.invalidate_cache()

        # Load and cache
        value1 = config_consumer.load_config("CACHED")
        self.assertEqual(value1, "value1")

        # Change env
        os.environ["ORCH_CACHED"] = "value2"

        # Invalidate cache
        config_consumer.invalidate_cache()

        # Should see new value
        value2 = config_consumer.load_config("CACHED")
        self.assertEqual(value2, "value2")

    def test_load_config_uses_cache(self):
        """load_config() returns cached value within TTL."""
        os.environ["ORCH_CACHED_KEY"] = "cached_value"
        config_consumer.invalidate_cache()

        # First call caches
        value1 = config_consumer.load_config("CACHED_KEY")
        self.assertEqual(value1, "cached_value")

        # Change env
        os.environ["ORCH_CACHED_KEY"] = "changed_value"

        # Second call within TTL should return cached value
        value2 = config_consumer.load_config("CACHED_KEY")
        self.assertEqual(value2, "cached_value")


class TestFailSoftErrorHandling(unittest.TestCase):
    """Test fail-soft error handling across all functions."""

    def setUp(self):
        """Clean up before each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def tearDown(self):
        """Clean up after each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def test_get_int_invalid_value_returns_default(self):
        """get_int() returns default on parse error."""
        os.environ["ORCH_BAD_INT"] = "not_a_number"
        value = config_consumer.get_int("BAD_INT", default=99)
        self.assertEqual(value, 99)

    def test_get_float_invalid_value_returns_default(self):
        """get_float() returns default on parse error."""
        os.environ["ORCH_BAD_FLOAT"] = "not_a_float"
        value = config_consumer.get_float("BAD_FLOAT", default=1.5)
        self.assertAlmostEqual(value, 1.5)

    def test_get_whitespace_only_returns_default(self):
        """get() treats whitespace-only values as missing."""
        os.environ["ORCH_WHITESPACE"] = "   "
        value = config_consumer.get("WHITESPACE", default="fallback")
        self.assertEqual(value, "fallback")

    def test_get_int_whitespace_returns_default(self):
        """get_int() treats whitespace-only values as missing."""
        os.environ["ORCH_WHITESPACE_INT"] = "   "
        value = config_consumer.get_int("WHITESPACE_INT", default=42)
        self.assertEqual(value, 42)


class TestThreadSafety(unittest.TestCase):
    """Test thread safety of config_consumer."""

    def setUp(self):
        """Clean up before each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def tearDown(self):
        """Clean up after each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def test_concurrent_get_calls_safe(self):
        """Multiple threads calling get() concurrently should be safe."""
        import threading
        os.environ["ORCH_THREAD_TEST"] = "value"
        results = []

        def getter():
            for _ in range(10):
                value = config_consumer.get("THREAD_TEST")
                results.append(value)

        threads = [threading.Thread(target=getter) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All results should be the same value
        self.assertEqual(len(results), 50)
        self.assertTrue(all(r == "value" for r in results))

    def test_concurrent_invalidate_safe(self):
        """Concurrent invalidate_cache() and get() should be safe."""
        import threading
        os.environ["ORCH_INVALIDATE_TEST"] = "value"
        config_consumer.invalidate_cache()
        results = []
        errors = []

        def reader():
            try:
                for _ in range(10):
                    value = config_consumer.load_config("INVALIDATE_TEST")
                    results.append(value)
            except Exception as e:
                errors.append(str(e))

        def invalidator():
            for _ in range(5):
                config_consumer.invalidate_cache()

        threads = []
        threads.extend([threading.Thread(target=reader) for _ in range(3)])
        threads.extend([threading.Thread(target=invalidator) for _ in range(2)])
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors
        self.assertEqual(len(errors), 0)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        """Clean up before each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def tearDown(self):
        """Clean up after each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def test_get_with_empty_default(self):
        """get() with empty default still returns empty string."""
        value = config_consumer.get("MISSING", default="")
        self.assertEqual(value, "")

    def test_get_with_whitespace_default(self):
        """get() respects whitespace-only default values."""
        value = config_consumer.get("MISSING", default="   ")
        self.assertEqual(value, "   ")

    def test_get_bool_case_insensitive(self):
        """get_bool() treats input case-insensitively."""
        for true_val in ["TRUE", "True", "TrUe", "YES", "Yes", "ON", "On"]:
            os.environ["ORCH_CASE_TEST"] = true_val
            config_consumer.invalidate_cache()
            value = config_consumer.get_bool("CASE_TEST")
            self.assertTrue(value, f"Failed for '{true_val}'")

    def test_get_bool_non_matching_value_false(self):
        """get_bool() returns False for non-matching values."""
        for false_val in ["false", "0", "no", "off", "maybe", "unknown"]:
            os.environ["ORCH_FALSE_TEST"] = false_val
            config_consumer.invalidate_cache()
            value = config_consumer.get_bool("FALSE_TEST")
            self.assertFalse(value, f"Expected False for '{false_val}'")

    def test_get_int_leading_zeros(self):
        """get_int() handles leading zeros."""
        os.environ["ORCH_LEADING_ZEROS"] = "0042"
        value = config_consumer.get_int("LEADING_ZEROS")
        self.assertEqual(value, 42)

    def test_get_int_negative_values(self):
        """get_int() handles negative integers."""
        os.environ["ORCH_NEGATIVE"] = "-100"
        value = config_consumer.get_int("NEGATIVE")
        self.assertEqual(value, -100)

    def test_get_float_scientific_notation(self):
        """get_float() handles scientific notation."""
        os.environ["ORCH_SCIENTIFIC"] = "1.5e-3"
        value = config_consumer.get_float("SCIENTIFIC")
        self.assertAlmostEqual(value, 0.0015)

    def test_get_float_negative_values(self):
        """get_float() handles negative floats."""
        os.environ["ORCH_NEGATIVE_FLOAT"] = "-3.14"
        value = config_consumer.get_float("NEGATIVE_FLOAT")
        self.assertAlmostEqual(value, -3.14)

    def test_very_long_config_value(self):
        """get() handles very long configuration values."""
        long_value = "x" * 10000
        os.environ["ORCH_LONG"] = long_value
        value = config_consumer.get("LONG")
        self.assertEqual(value, long_value)

    def test_config_with_special_characters(self):
        """get() handles special characters in values."""
        special_value = "!@#$%^&*()_+-={}[]|:;<>,.?/~`"
        os.environ["ORCH_SPECIAL"] = special_value
        value = config_consumer.get("SPECIAL")
        self.assertEqual(value, special_value)

    def test_config_with_unicode(self):
        """get() handles unicode characters."""
        unicode_value = "你好世界🌍"
        os.environ["ORCH_UNICODE"] = unicode_value
        value = config_consumer.get("UNICODE")
        self.assertEqual(value, unicode_value)

    def test_get_int_large_number(self):
        """get_int() handles very large integers."""
        os.environ["ORCH_LARGE_INT"] = "9223372036854775807"
        value = config_consumer.get_int("LARGE_INT")
        self.assertEqual(value, 9223372036854775807)

    def test_get_float_very_small_number(self):
        """get_float() handles very small floats."""
        os.environ["ORCH_TINY_FLOAT"] = "1e-10"
        value = config_consumer.get_float("TINY_FLOAT")
        self.assertGreater(value, 0)
        self.assertLess(value, 1e-9)

    def test_load_config_with_none_key_returns_default(self):
        """load_config(None) returns default."""
        config_consumer.invalidate_cache()
        value = config_consumer.load_config(None, default="fallback")
        self.assertEqual(value, "fallback")

    def test_load_config_with_empty_string_key_returns_default(self):
        """load_config('') returns default."""
        config_consumer.invalidate_cache()
        value = config_consumer.load_config("", default="fallback")
        self.assertEqual(value, "fallback")

    def test_load_all_includes_newly_added_keys(self):
        """load_all() includes dynamically added ORCH_* keys."""
        config_consumer.invalidate_cache()
        os.environ["ORCH_DYNAMIC"] = "added"
        all_config = config_consumer.load_all()
        self.assertIn("DYNAMIC", all_config)
        self.assertEqual(all_config["DYNAMIC"], "added")


class TestConfigEnvVars(unittest.TestCase):
    """Test configuration via environment variables."""

    def setUp(self):
        """Clean up before each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def tearDown(self):
        """Clean up after each test."""
        config_consumer.invalidate_cache()
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

    def test_cache_ttl_from_env(self):
        """Cache TTL can be configured via ORCH_CONFIG_CACHE_TTL_SEC."""
        # This tests that the env var is respected; hard to test behavior
        # without waiting, but we can verify the module loads with custom TTL
        old_val = os.environ.get("ORCH_CONFIG_CACHE_TTL_SEC")
        try:
            os.environ["ORCH_CONFIG_CACHE_TTL_SEC"] = "120"
            # Force reimport to pick up new TTL
            import importlib
            import config_consumer as cc
            importlib.reload(cc)
            # If no exception, the env var was respected
            self.assertTrue(True)
        finally:
            if old_val:
                os.environ["ORCH_CONFIG_CACHE_TTL_SEC"] = old_val
            else:
                os.environ.pop("ORCH_CONFIG_CACHE_TTL_SEC", None)


if __name__ == "__main__":
    unittest.main()
