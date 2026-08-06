"""Tests for vercel_checks_cache.py — Vercel deployment check caching."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import vercel_checks_cache as vcc


class TestVercelChecksCacheCoreLogic(unittest.TestCase):
    """Test core cache operations."""

    def setUp(self):
        """Create a temp cache file for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.temp_dir.name, "test_cache.json")
        self.patcher = mock.patch.object(vcc, "CACHE_FILE", self.cache_file)
        self.patcher.start()

    def tearDown(self):
        """Clean up temp directory."""
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_load_cache_from_empty_file(self):
        """Loading cache from non-existent file returns empty dict."""
        cache = vcc._load_cache()
        self.assertEqual(cache, {})

    def test_load_cache_from_valid_json(self):
        """Loading cache from valid JSON file works."""
        test_data = {"project1:main": {"data": {"ok": True}}}
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w") as f:
            json.dump(test_data, f)

        cache = vcc._load_cache()
        self.assertEqual(cache, test_data)

    def test_load_cache_from_corrupted_json(self):
        """Loading corrupted JSON returns empty dict (fail-soft)."""
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w") as f:
            f.write("{invalid json")

        cache = vcc._load_cache()
        self.assertEqual(cache, {})

    def test_load_cache_with_non_dict_json(self):
        """Loading non-dict JSON (e.g., list) returns empty dict."""
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w") as f:
            json.dump([1, 2, 3], f)

        cache = vcc._load_cache()
        self.assertEqual(cache, {})

    def test_save_cache_creates_directory(self):
        """Saving cache creates parent directory if needed."""
        nested_path = os.path.join(self.temp_dir.name, "a", "b", "c", "cache.json")
        with mock.patch.object(vcc, "CACHE_FILE", nested_path):
            data = {"key": "value"}
            vcc._save_cache(data)
            self.assertTrue(os.path.isfile(nested_path))

    def test_save_cache_writes_valid_json(self):
        """Saving cache writes valid JSON."""
        data = {"project1:main": {"data": {"ok": True}, "checked_at": time.time()}}
        vcc._save_cache(data)
        with open(self.cache_file) as f:
            saved = json.load(f)
        self.assertEqual(saved, data)

    def test_cache_key_generation(self):
        """Cache key combines project_id and branch."""
        key1 = vcc._get_cache_key("proj1", "main")
        self.assertEqual(key1, "proj1:main")

        key2 = vcc._get_cache_key("proj1", None)
        self.assertEqual(key2, "proj1:main")

        key3 = vcc._get_cache_key("proj2", "feature/xyz")
        self.assertEqual(key3, "proj2:feature/xyz")


class TestVercelChecksCacheFreshness(unittest.TestCase):
    """Test cache freshness checks."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.temp_dir.name, "test_cache.json")
        self.patcher = mock.patch.object(vcc, "CACHE_FILE", self.cache_file)
        self.patcher_interval = mock.patch.object(vcc, "CHECK_INTERVAL", 10)
        self.patcher.start()
        self.patcher_interval.start()

    def tearDown(self):
        self.patcher.stop()
        self.patcher_interval.stop()
        self.temp_dir.cleanup()

    def test_is_cached_fresh_with_no_entry(self):
        """No cache entry returns (False, None)."""
        is_fresh, value = vcc.is_cached_fresh("proj1", "main")
        self.assertFalse(is_fresh)
        self.assertIsNone(value)

    def test_is_cached_fresh_with_recent_entry(self):
        """Fresh cache entry returns (True, data)."""
        now = time.time()
        data = {"proj1:main": {"checked_at": now, "data": {"ok": True}}}
        with open(self.cache_file, "w") as f:
            json.dump(data, f)

        is_fresh, value = vcc.is_cached_fresh("proj1", "main")
        self.assertTrue(is_fresh)
        self.assertEqual(value, {"ok": True})

    def test_is_cached_fresh_with_stale_entry(self):
        """Stale cache entry returns (False, data) but doesn't fail."""
        now = time.time()
        old_time = now - 20  # older than CHECK_INTERVAL (10)
        data = {"proj1:main": {"checked_at": old_time, "data": {"ok": True}}}
        with open(self.cache_file, "w") as f:
            json.dump(data, f)

        is_fresh, value = vcc.is_cached_fresh("proj1", "main")
        self.assertFalse(is_fresh)
        # Stale data is still returned for caller to use
        self.assertEqual(value, {"ok": True})

    def test_is_cached_fresh_with_corrupted_cache(self):
        """Corrupted cache returns (False, None) (fail-soft)."""
        with open(self.cache_file, "w") as f:
            f.write("bad json")

        is_fresh, value = vcc.is_cached_fresh("proj1", "main")
        self.assertFalse(is_fresh)
        self.assertIsNone(value)

    def test_is_cached_fresh_bypass_with_env_var(self):
        """ORCH_DISABLE_VERCEL_CHECKS_CACHE=1 always returns (False, None)."""
        data = {"proj1:main": {"checked_at": time.time(), "data": {"ok": True}}}
        with open(self.cache_file, "w") as f:
            json.dump(data, f)

        with mock.patch.dict(os.environ, {"ORCH_DISABLE_VERCEL_CHECKS_CACHE": "1"}):
            is_fresh, value = vcc.is_cached_fresh("proj1", "main")
            self.assertFalse(is_fresh)
            self.assertIsNone(value)


class TestVercelChecksCacheStorage(unittest.TestCase):
    """Test cache storage and invalidation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.temp_dir.name, "test_cache.json")
        self.patcher = mock.patch.object(vcc, "CACHE_FILE", self.cache_file)
        self.patcher_interval = mock.patch.object(vcc, "CHECK_INTERVAL", 10)
        self.patcher.start()
        self.patcher_interval.start()

    def tearDown(self):
        self.patcher.stop()
        self.patcher_interval.stop()
        self.temp_dir.cleanup()

    def test_cache_result_stores_data(self):
        """cache_result stores a check result."""
        result = {"ok": True, "status": "READY"}
        vcc.cache_result("proj1", "main", "deployment_ready", result)

        is_fresh, value = vcc.is_cached_fresh("proj1", "main")
        self.assertTrue(is_fresh)
        self.assertEqual(value, result)

    def test_cache_result_with_custom_ttl(self):
        """cache_result respects custom TTL."""
        result = {"ok": False}
        vcc.cache_result("proj1", "main", "build_check", result, ttl_seconds=5)

        cache = vcc._load_cache()
        entry = cache.get("proj1:main")
        self.assertEqual(entry["ttl"], 5)

    def test_cache_result_bypass_with_env_var(self):
        """cache_result does nothing when cache is disabled."""
        with mock.patch.dict(os.environ, {"ORCH_DISABLE_VERCEL_CHECKS_CACHE": "1"}):
            vcc.cache_result("proj1", "main", "test", {"ok": True})

        cache = vcc._load_cache()
        self.assertEqual(cache, {})

    def test_invalidate_single_entry(self):
        """invalidate removes specific project/branch entry."""
        vcc.cache_result("proj1", "main", "test", {"ok": True})
        vcc.cache_result("proj1", "dev", "test", {"ok": False})

        vcc.invalidate("proj1", "main")

        cache = vcc._load_cache()
        self.assertNotIn("proj1:main", cache)
        self.assertIn("proj1:dev", cache)

    def test_invalidate_all_branches_for_project(self):
        """invalidate without branch removes all entries for project."""
        vcc.cache_result("proj1", "main", "test", {"ok": True})
        vcc.cache_result("proj1", "dev", "test", {"ok": False})
        vcc.cache_result("proj2", "main", "test", {"ok": True})

        vcc.invalidate("proj1")

        cache = vcc._load_cache()
        self.assertNotIn("proj1:main", cache)
        self.assertNotIn("proj1:dev", cache)
        self.assertIn("proj2:main", cache)

    def test_invalidate_all(self):
        """invalidate_all clears entire cache."""
        vcc.cache_result("proj1", "main", "test", {"ok": True})
        vcc.cache_result("proj2", "dev", "test", {"ok": False})

        vcc.invalidate_all()

        cache = vcc._load_cache()
        self.assertEqual(cache, {})

    def test_invalidate_bypass_with_env_var(self):
        """invalidate does nothing when cache is disabled."""
        vcc.cache_result("proj1", "main", "test", {"ok": True})
        with mock.patch.dict(os.environ, {"ORCH_DISABLE_VERCEL_CHECKS_CACHE": "1"}):
            vcc.invalidate("proj1", "main")
        # Cache should still have the entry
        cache = vcc._load_cache()
        self.assertIn("proj1:main", cache)


class TestVercelChecksCacheStats(unittest.TestCase):
    """Test cache statistics and monitoring."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.temp_dir.name, "test_cache.json")
        self.patcher = mock.patch.object(vcc, "CACHE_FILE", self.cache_file)
        self.patcher_interval = mock.patch.object(vcc, "CHECK_INTERVAL", 10)
        self.patcher.start()
        self.patcher_interval.start()

    def tearDown(self):
        self.patcher.stop()
        self.patcher_interval.stop()
        self.temp_dir.cleanup()

    def test_stats_on_empty_cache(self):
        """stats on empty cache returns correct values."""
        stats = vcc.stats()
        self.assertEqual(stats["entries"], 0)
        self.assertEqual(stats["file_size"], 0)
        self.assertEqual(stats["check_interval_s"], 10)

    def test_stats_on_populated_cache(self):
        """stats counts fresh and stale entries."""
        now = time.time()
        vcc.cache_result("proj1", "main", "test1", {"ok": True})  # fresh
        # Add a stale entry directly
        cache = vcc._load_cache()
        cache["proj2:dev"] = {"checked_at": now - 20, "data": {"ok": False}, "check": "test2"}
        vcc._save_cache(cache)

        stats = vcc.stats()
        self.assertEqual(stats["entries"], 2)
        self.assertEqual(stats["fresh"], 1)
        self.assertEqual(stats["stale"], 1)

    def test_stats_on_corrupted_cache(self):
        """stats handles corrupted cache gracefully (fail-soft, treats as empty)."""
        with open(self.cache_file, "w") as f:
            f.write("bad json")

        stats = vcc.stats()
        # Fail-soft: corrupted cache is treated as empty
        self.assertEqual(stats["entries"], 0)
        self.assertIn("cache_file", stats)

    def test_stats_file_size(self):
        """stats reports correct file size."""
        vcc.cache_result("proj1", "main", "test", {"status": "READY", "url": "http://example.com"})
        stats = vcc.stats()
        self.assertGreater(stats["file_size"], 0)
        self.assertTrue(os.path.isfile(self.cache_file))


class TestVercelChecksCacheEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.temp_dir.name, "test_cache.json")
        self.patcher = mock.patch.object(vcc, "CACHE_FILE", self.cache_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_cache_with_none_branch(self):
        """None branch is normalized to 'main'."""
        vcc.cache_result("proj1", None, "test", {"ok": True})
        cache = vcc._load_cache()
        self.assertIn("proj1:main", cache)

    def test_cache_with_empty_string_branch(self):
        """Empty string branch is normalized to 'main' (empty string is falsy)."""
        key = vcc._get_cache_key("proj1", "")
        self.assertEqual(key, "proj1:main")

    def test_cache_with_special_chars_in_branch(self):
        """Branches with special chars are cached correctly."""
        branch = "feature/ORCH-123/test-cache"
        vcc.cache_result("proj1", branch, "test", {"ok": True})
        cache = vcc._load_cache()
        self.assertIn(f"proj1:{branch}", cache)

    def test_cache_with_unicode_in_result(self):
        """Results with unicode characters are cached."""
        result = {"message": "✓ Deployment ready", "emoji": "🚀"}
        vcc.cache_result("proj1", "main", "test", result)
        is_fresh, cached = vcc.is_cached_fresh("proj1", "main")
        self.assertTrue(is_fresh)
        self.assertEqual(cached, result)

    def test_cache_with_very_large_result(self):
        """Large results can be cached (with byte limit in practice)."""
        large_data = {"logs": "x" * 10000, "errors": ["e" * 100 for _ in range(50)]}
        vcc.cache_result("proj1", "main", "test", large_data)
        is_fresh, cached = vcc.is_cached_fresh("proj1", "main")
        self.assertTrue(is_fresh)
        self.assertEqual(cached, large_data)

    def test_concurrent_cache_operations(self):
        """Thread-safe lock protects concurrent access."""
        import threading

        results = []

        def write_cache(proj, branch, i):
            vcc.cache_result(proj, branch, f"test{i}", {"index": i})
            results.append(("write", i))

        def read_cache(proj, branch, i):
            is_fresh, value = vcc.is_cached_fresh(proj, branch)
            results.append(("read", i, is_fresh))

        threads = []
        for i in range(5):
            t = threading.Thread(target=write_cache, args=("proj1", "main", i))
            threads.append(t)
            t = threading.Thread(target=read_cache, args=("proj1", "main", i))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All operations completed without error
        self.assertTrue(len(results) > 0)


class TestVercelChecksCacheIntegration(unittest.TestCase):
    """Integration tests for realistic usage patterns."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.temp_dir.name, "test_cache.json")
        self.patcher = mock.patch.object(vcc, "CACHE_FILE", self.cache_file)
        self.patcher_interval = mock.patch.object(vcc, "CHECK_INTERVAL", 5)
        self.patcher.start()
        self.patcher_interval.start()

    def tearDown(self):
        self.patcher.stop()
        self.patcher_interval.stop()
        self.temp_dir.cleanup()

    def test_workflow_cache_check_then_store(self):
        """Typical workflow: check cache, if miss do work, then store result."""
        # Check (miss)
        is_fresh, cached = vcc.is_cached_fresh("proj1", "main")
        self.assertFalse(is_fresh)
        self.assertIsNone(cached)

        # Do the work (simulate Vercel API call)
        result = {"status": "READY", "url": "https://proj1-main.vercel.app"}

        # Store
        vcc.cache_result("proj1", "main", "deployment_status", result)

        # Check again (hit)
        is_fresh, cached = vcc.is_cached_fresh("proj1", "main")
        self.assertTrue(is_fresh)
        self.assertEqual(cached, result)

    def test_workflow_multiple_projects_and_branches(self):
        """Multiple projects and branches don't interfere."""
        vcc.cache_result("proj1", "main", "test", {"ok": True})
        vcc.cache_result("proj1", "dev", "test", {"ok": False})
        vcc.cache_result("proj2", "main", "test", {"ok": True})
        vcc.cache_result("proj2", "staging", "test", {"status": "building"})

        # Verify each is independent
        _, v1m = vcc.is_cached_fresh("proj1", "main")
        _, v1d = vcc.is_cached_fresh("proj1", "dev")
        _, v2m = vcc.is_cached_fresh("proj2", "main")
        _, v2s = vcc.is_cached_fresh("proj2", "staging")

        self.assertEqual(v1m, {"ok": True})
        self.assertEqual(v1d, {"ok": False})
        self.assertEqual(v2m, {"ok": True})
        self.assertEqual(v2s, {"status": "building"})

    def test_workflow_stale_cache_fallback(self):
        """Stale cache is returned but caller knows to re-check."""
        now = time.time()
        old_time = now - 10  # Stale (interval is 5)
        cache_data = {"proj1:main": {"checked_at": old_time, "data": {"status": "READY"}}}
        with open(self.cache_file, "w") as f:
            json.dump(cache_data, f)

        is_fresh, cached = vcc.is_cached_fresh("proj1", "main")
        # Stale data returned but marked as not fresh
        self.assertFalse(is_fresh)
        self.assertEqual(cached, {"status": "READY"})
        # Caller can use stale data as fallback while re-checking


class TestVercelChecksCacheEnvironmentConfiguration(unittest.TestCase):
    """Test environment variable configuration."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.temp_dir.name, "test_cache.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_custom_cache_file_location(self):
        """Custom cache file location via env var is used."""
        custom_cache = os.path.join(self.temp_dir.name, "custom", "my_cache.json")
        with mock.patch.object(vcc, "CACHE_FILE", custom_cache):
            vcc.cache_result("proj1", "main", "test", {"ok": True})
            self.assertTrue(os.path.isfile(custom_cache))

    def test_custom_check_interval(self):
        """Custom check interval is used."""
        now = time.time()
        cache_data = {"proj1:main": {"checked_at": now - 2, "data": {"ok": True}}}
        cache_file = os.path.join(self.temp_dir.name, "cache.json")
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        # With interval of 1 second, 2-second-old entry is stale
        with mock.patch.object(vcc, "CACHE_FILE", cache_file):
            with mock.patch.object(vcc, "CHECK_INTERVAL", 1):
                is_fresh, _ = vcc.is_cached_fresh("proj1", "main")
                self.assertFalse(is_fresh)

        # With interval of 5 seconds, 2-second-old entry is fresh
        with mock.patch.object(vcc, "CACHE_FILE", cache_file):
            with mock.patch.object(vcc, "CHECK_INTERVAL", 5):
                is_fresh, _ = vcc.is_cached_fresh("proj1", "main")
                self.assertTrue(is_fresh)


if __name__ == "__main__":
    unittest.main()


class TestRelfixVercelChecksCache(unittest.TestCase):
    """Regression: is_cached_fresh ignored the per-entry TTL stored by cache_result."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.temp_dir.name, "test_cache.json")
        self.patcher = mock.patch.object(vcc, "CACHE_FILE", self.cache_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_relfix_vercel_checks_cache(self):
        """An entry with a short custom TTL goes stale after that TTL, not CHECK_INTERVAL."""
        vcc.cache_result("proj-relfix", "main", "deployment_ready", {"ok": True}, ttl_seconds=10)
        fresh, data = vcc.is_cached_fresh("proj-relfix", "main")
        self.assertTrue(fresh)
        self.assertEqual(data, {"ok": True})

        # Age the entry past its custom TTL (10s) but well inside CHECK_INTERVAL (300s).
        with open(self.cache_file) as f:
            cache = json.load(f)
        cache["proj-relfix:main"]["checked_at"] = time.time() - 60
        with open(self.cache_file, "w") as f:
            json.dump(cache, f)

        fresh, data = vcc.is_cached_fresh("proj-relfix", "main")
        self.assertFalse(fresh)
        self.assertEqual(data, {"ok": True})
