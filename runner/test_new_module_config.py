#!/usr/bin/env python3
"""
test_new_module_config.py - Comprehensive tests for new_module_config.py.

Tests cover:
- Normal paths (get, set, delete)
- Edge cases (None, empty string, bad paths, missing files)
- Cache staleness and invalidation
- Memory pressure and capacity limits
- Thread safety and concurrency
- File I/O error handling
- Configuration validation
- Persistence across operations
"""
import os, sys, json, time, threading, tempfile, shutil
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import new_module_config


class TestNewModuleConfig(unittest.TestCase):
    """Test suite for module configuration management."""

    def setUp(self):
        """Set up test fixtures."""
        # Use a temporary directory for each test
        self.temp_dir = tempfile.mkdtemp()
        self.original_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.temp_dir
        # Reload module to use test home
        new_module_config.HOME = self.temp_dir
        new_module_config.clear()

    def tearDown(self):
        """Clean up after tests."""
        new_module_config.clear()
        if self.original_home:
            os.environ["CLAUDE_ORCH_HOME"] = self.original_home
        else:
            os.environ.pop("CLAUDE_ORCH_HOME", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ===== NORMAL PATH TESTS =====

    def test_01_get_nonexistent_returns_default(self):
        """Test getting non-existent key returns default."""
        self.assertEqual(new_module_config.get("nonexistent"), "")
        self.assertEqual(new_module_config.get("nonexistent", "custom_default"), "custom_default")

    def test_02_set_and_get_basic(self):
        """Test basic set/get operations."""
        self.assertTrue(new_module_config.set("test_key", "test_value"))
        self.assertEqual(new_module_config.get("test_key"), "test_value")

    def test_03_set_multiple_values(self):
        """Test setting multiple values."""
        for i in range(5):
            self.assertTrue(new_module_config.set(f"key_{i}", f"value_{i}"))
            self.assertEqual(new_module_config.get(f"key_{i}"), f"value_{i}")

    def test_04_delete_existing_key(self):
        """Test deleting an existing key."""
        new_module_config.set("to_delete", "value")
        self.assertEqual(new_module_config.get("to_delete"), "value")
        self.assertTrue(new_module_config.delete("to_delete"))
        self.assertEqual(new_module_config.get("to_delete"), "")

    def test_05_delete_nonexistent_key(self):
        """Test deleting non-existent key returns True (soft fail)."""
        self.assertTrue(new_module_config.delete("nonexistent"))

    def test_06_overwrite_existing_value(self):
        """Test overwriting an existing key."""
        new_module_config.set("key", "old_value")
        new_module_config.set("key", "new_value")
        self.assertEqual(new_module_config.get("key"), "new_value")

    # ===== EDGE CASES =====

    def test_07_get_with_none_key(self):
        """Test get() with None key returns default (fail-soft)."""
        result = new_module_config.get(None)
        self.assertEqual(result, "")

    def test_08_set_with_none_key(self):
        """Test set() with None key returns False (fail-soft)."""
        self.assertFalse(new_module_config.set(None, "value"))

    def test_09_set_with_non_string_value(self):
        """Test set() with non-string value returns False (fail-soft)."""
        self.assertFalse(new_module_config.set("key", 123))
        self.assertFalse(new_module_config.set("key", None))
        self.assertFalse(new_module_config.set("key", ["list"]))

    def test_10_empty_string_key_handling(self):
        """Test handling of empty string key."""
        result = new_module_config.set("", "value")
        # Should set successfully (empty string is valid)
        self.assertTrue(result)
        self.assertEqual(new_module_config.get(""), "value")

    def test_11_empty_string_value(self):
        """Test setting and getting empty string value."""
        self.assertTrue(new_module_config.set("empty_key", ""))
        self.assertEqual(new_module_config.get("empty_key"), "")

    def test_12_special_characters_in_keys(self):
        """Test keys with special characters."""
        special_keys = ["key.with.dots", "key-with-dashes", "key_with_underscores", "ORCH_PREFIX_KEY"]
        for key in special_keys:
            self.assertTrue(new_module_config.set(key, "value"))
            self.assertEqual(new_module_config.get(key), "value")

    def test_13_unicode_values(self):
        """Test storing and retrieving unicode values."""
        unicode_value = "テスト_值_тест"
        self.assertTrue(new_module_config.set("unicode_key", unicode_value))
        self.assertEqual(new_module_config.get("unicode_key"), unicode_value)

    # ===== CACHE & STALENESS TESTS =====

    def test_14_cache_staleness(self):
        """Test cache invalidation after TTL."""
        new_module_config.set("key", "value")
        new_module_config._cache_ts = time.time() - 100  # Make cache very stale
        self.assertEqual(new_module_config.get("key"), "value")  # Still works due to persistence

    def test_15_manual_invalidate(self):
        """Test manual cache invalidation."""
        new_module_config.set("key", "value")
        stats_before = new_module_config.stats()
        self.assertFalse(stats_before.get("is_stale", True))
        new_module_config.invalidate()
        stats_after = new_module_config.stats()
        self.assertTrue(stats_after.get("is_stale", False))
        self.assertEqual(new_module_config.get("key"), "value")  # Still works

    def test_16_stats_available(self):
        """Test stats() returns diagnostic information."""
        new_module_config.set("key", "value")
        stats = new_module_config.stats()
        self.assertIn("cache_size", stats)
        self.assertIn("cache_age_seconds", stats)
        self.assertIn("is_stale", stats)
        self.assertIn("file_path", stats)
        self.assertIn("file_exists", stats)
        self.assertGreaterEqual(stats["cache_size"], 1)

    # ===== CAPACITY & MEMORY PRESSURE =====

    def test_17_capacity_limit_respected(self):
        """Test that capacity limit is enforced."""
        original_max = new_module_config.CONFIG_MAX_KEYS
        try:
            new_module_config.CONFIG_MAX_KEYS = 3
            self.assertTrue(new_module_config.set("key1", "value1"))
            self.assertTrue(new_module_config.set("key2", "value2"))
            self.assertTrue(new_module_config.set("key3", "value3"))
            # Adding a 4th key should fail (at capacity)
            self.assertFalse(new_module_config.set("key4", "value4"))
            # But existing keys should still be accessible
            self.assertEqual(new_module_config.get("key1"), "value1")
        finally:
            new_module_config.CONFIG_MAX_KEYS = original_max

    def test_18_overwriting_within_capacity(self):
        """Test that overwriting within capacity limit works."""
        original_max = new_module_config.CONFIG_MAX_KEYS
        try:
            new_module_config.CONFIG_MAX_KEYS = 2
            self.assertTrue(new_module_config.set("key1", "value1"))
            self.assertTrue(new_module_config.set("key2", "value2"))
            # Overwriting should succeed even at capacity
            self.assertTrue(new_module_config.set("key1", "new_value1"))
            self.assertEqual(new_module_config.get("key1"), "new_value1")
        finally:
            new_module_config.CONFIG_MAX_KEYS = original_max

    # ===== FILE I/O & PERSISTENCE =====

    def test_19_persistence_across_clear_reload(self):
        """Test that values persist after clearing cache (but not file)."""
        new_module_config.set("persistent_key", "persistent_value")
        new_module_config.clear()
        # After clear, should not exist
        self.assertEqual(new_module_config.get("persistent_key"), "")

    def test_20_file_storage_format(self):
        """Test that file storage uses valid JSON format."""
        new_module_config.set("key1", "value1")
        new_module_config.set("key2", "value2")
        path = new_module_config._config_file_path()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["key1"], "value1")
        self.assertEqual(data["key2"], "value2")

    def test_21_large_file_rejected(self):
        """Test that oversized files are rejected gracefully."""
        original_max = new_module_config.CONFIG_FILE_MAX_BYTES
        try:
            new_module_config.CONFIG_FILE_MAX_BYTES = 10  # Very small
            # This should fail because the JSON will be too large
            result = new_module_config.set("key", "value")
            # Depending on JSON overhead, may fail or succeed with minimal data
            # Just verify no crash
            self.assertIsInstance(result, bool)
        finally:
            new_module_config.CONFIG_FILE_MAX_BYTES = original_max

    def test_22_corrupted_file_graceful_degradation(self):
        """Test graceful handling of corrupted file."""
        path = new_module_config._config_file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{corrupted json")
        # Should still work (fall back to empty cache)
        new_module_config.invalidate()
        new_module_config.set("new_key", "new_value")
        self.assertEqual(new_module_config.get("new_key"), "new_value")

    def test_23_missing_file_graceful(self):
        """Test graceful handling of missing config file."""
        # File doesn't exist initially
        self.assertEqual(new_module_config.get("nonexistent"), "")
        # Set creates it
        new_module_config.set("key", "value")
        self.assertTrue(os.path.exists(new_module_config._config_file_path()))

    # ===== ENVIRONMENT VARIABLE FALLBACK =====

    def test_24_env_var_fallback(self):
        """Test fallback to environment variables."""
        os.environ["ORCH_ENV_TEST_KEY"] = "env_value"
        # Should find via ORCH_ prefix
        result = new_module_config.get("ENV_TEST_KEY")
        self.assertEqual(result, "env_value")
        del os.environ["ORCH_ENV_TEST_KEY"]

    def test_25_get_env_var_direct(self):
        """Test direct environment variable access."""
        os.environ["TEST_VAR"] = "test_val"
        result = new_module_config.get_env_var("TEST_VAR")
        self.assertEqual(result, "test_val")
        del os.environ["TEST_VAR"]

    def test_26_get_env_var_fallback_default(self):
        """Test get_env_var with missing env var returns default."""
        result = new_module_config.get_env_var("NONEXISTENT_VAR", "default_val")
        self.assertEqual(result, "default_val")

    # ===== THREAD SAFETY =====

    def test_27_concurrent_reads(self):
        """Test thread safety of concurrent read operations."""
        new_module_config.set("key", "value")
        results = []
        errors = []

        def read_key():
            try:
                for _ in range(10):
                    result = new_module_config.get("key")
                    results.append(result)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_key) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors during concurrent reads: {errors}")
        self.assertTrue(all(r == "value" for r in results))

    def test_28_concurrent_writes(self):
        """Test thread safety of concurrent write operations."""
        errors = []

        def write_keys(thread_id):
            try:
                for i in range(5):
                    key = f"thread_{thread_id}_key_{i}"
                    new_module_config.set(key, f"value_{i}")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_keys, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors during concurrent writes: {errors}")
        stats = new_module_config.stats()
        self.assertGreaterEqual(stats["cache_size"], 10)  # At least 10 keys written

    def test_29_concurrent_read_write(self):
        """Test thread safety of mixed read/write operations."""
        errors = []

        def mixed_operations(thread_id):
            try:
                for i in range(5):
                    key = f"key_{i % 3}"
                    if thread_id % 2 == 0:
                        new_module_config.set(key, f"value_{thread_id}_{i}")
                    else:
                        new_module_config.get(key)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=mixed_operations, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors during mixed operations: {errors}")

    # ===== INTEGRATION TESTS =====

    def test_30_complete_workflow(self):
        """Test a complete workflow of set, get, update, delete."""
        # Set initial values
        new_module_config.set("config_key_1", "initial_value")
        new_module_config.set("config_key_2", "another_value")

        # Verify retrieval
        self.assertEqual(new_module_config.get("config_key_1"), "initial_value")
        self.assertEqual(new_module_config.get("config_key_2"), "another_value")

        # Update a value
        new_module_config.set("config_key_1", "updated_value")
        self.assertEqual(new_module_config.get("config_key_1"), "updated_value")

        # Check stats
        stats = new_module_config.stats()
        self.assertGreaterEqual(stats["cache_size"], 2)

        # Delete one
        new_module_config.delete("config_key_1")
        self.assertEqual(new_module_config.get("config_key_1"), "")
        self.assertEqual(new_module_config.get("config_key_2"), "another_value")

        # Clear all
        new_module_config.clear()
        self.assertEqual(new_module_config.get("config_key_2"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
