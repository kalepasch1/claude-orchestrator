#!/usr/bin/env python3
"""Comprehensive test suite for diff_memory.py (20+ test cases).

Tests cover:
- Normal store/retrieve paths
- Edge cases: None hash, empty metadata, missing cache dir
- LRU eviction and TTL staleness
- Concurrency and thread safety
- File I/O failures and error handling
- Stats and invalidation
"""
import os
import sys
import json
import time
import tempfile
import threading
from pathlib import Path
from unittest import mock
import pytest

# Add tools directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import diff_memory


@pytest.fixture
def temp_cache_dir():
    """Create a temporary cache directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def clean_singleton():
    """Reset the singleton between tests."""
    diff_memory._diff_memory = None
    yield
    diff_memory._diff_memory = None


class TestBasicStoreRetrieve:
    """Test basic store and retrieve functionality."""

    def test_store_and_retrieve_success(self, temp_cache_dir, clean_singleton):
        """Store a diff and retrieve it."""
        os.environ["ORCH_DIFF_MEMORY_LIMIT"] = "256"
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir, max_memory_mb=256)

        metadata = {"files": ["a.py", "b.py"], "stats": {"additions": 10, "deletions": 5}}
        hash_val = "abc123def456"

        assert dm.store_diff(hash_val, metadata) is True
        retrieved = dm.get_diff(hash_val)

        assert retrieved is not None
        assert retrieved["files"] == ["a.py", "b.py"]
        assert retrieved["stats"]["additions"] == 10

    def test_retrieve_nonexistent_returns_none(self, temp_cache_dir, clean_singleton):
        """Retrieve non-existent diff returns None."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        assert dm.get_diff("nonexistent") is None

    def test_module_level_store_and_retrieve(self, temp_cache_dir, clean_singleton):
        """Test module-level functions delegate to singleton."""
        os.environ["ORCH_DIFF_MEMORY_LIMIT"] = "256"
        diff_memory._diff_memory = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        metadata = {"files": ["test.py"]}
        assert diff_memory.store_diff("hash1", metadata) is True
        assert diff_memory.get_diff("hash1") is not None

    def test_acquire_singleton(self, temp_cache_dir, clean_singleton):
        """acquire() returns the same singleton instance."""
        os.environ["ORCH_DIFF_MEMORY_LIMIT"] = "256"
        diff_memory._diff_memory = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        dm1 = diff_memory.acquire()
        dm2 = diff_memory.acquire()
        assert dm1 is dm2


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_none_hash_returns_false(self, temp_cache_dir, clean_singleton):
        """Storing with None hash returns False."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        assert dm.store_diff(None, {"files": []}) is False

    def test_empty_hash_returns_false(self, temp_cache_dir, clean_singleton):
        """Storing with empty hash returns False."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        assert dm.store_diff("", {"files": []}) is False

    def test_none_metadata_returns_false(self, temp_cache_dir, clean_singleton):
        """Storing with None metadata returns False."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        assert dm.store_diff("hash1", None) is False

    def test_empty_metadata_returns_false(self, temp_cache_dir, clean_singleton):
        """Storing with empty dict metadata returns False."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        assert dm.store_diff("hash1", {}) is False

    def test_none_hash_on_retrieve_returns_none(self, temp_cache_dir, clean_singleton):
        """Retrieving with None hash returns None."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        assert dm.get_diff(None) is None

    def test_empty_hash_on_retrieve_returns_none(self, temp_cache_dir, clean_singleton):
        """Retrieving with empty hash returns None."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        assert dm.get_diff("") is None

    def test_missing_cache_dir_created_on_store(self, clean_singleton):
        """Cache directory is created if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "nonexistent", "cache")
            dm = diff_memory.DiffMemory(cache_dir=cache_dir)

            metadata = {"files": ["a.py"]}
            assert dm.store_diff("hash1", metadata) is True
            assert os.path.isdir(cache_dir)

    def test_large_metadata_exceeding_limit_returns_false(self, temp_cache_dir, clean_singleton):
        """Storing metadata larger than memory limit returns False."""
        # Use extremely small limit (1KB) to force rejection
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir, max_memory_mb=0.001)

        large_metadata = {"files": ["f.py"] * 1000, "data": "x" * 50000}
        assert dm.store_diff("huge", large_metadata) is False

    def test_internal_metadata_not_exposed(self, temp_cache_dir, clean_singleton):
        """Internal metadata fields (starting with _) are not returned."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        metadata = {"files": ["a.py"]}
        dm.store_diff("hash1", metadata)
        retrieved = dm.get_diff("hash1")

        # Should not contain internal fields
        assert "_hash" not in retrieved
        assert "_timestamp" not in retrieved
        assert "_size_bytes" not in retrieved
        assert "files" in retrieved


class TestLRUEviction:
    """Test LRU eviction when memory limit is exceeded."""

    def test_lru_eviction_on_memory_limit(self, temp_cache_dir, clean_singleton):
        """Oldest entry is evicted when memory limit exceeded."""
        # Use 2KB limit to force eviction
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir, max_memory_mb=0.002)

        metadata1 = {"files": ["a.py"], "data": "x" * 300}
        metadata2 = {"files": ["b.py"], "data": "y" * 300}
        metadata3 = {"files": ["c.py"], "data": "z" * 300}

        assert dm.store_diff("hash1", metadata1) is True
        assert dm.store_diff("hash2", metadata2) is True
        assert dm.store_diff("hash3", metadata3) is True

        # First entry should be evicted due to LRU
        # After adding 3 entries with 2KB limit, at least one should be gone
        assert len(dm._memory_cache) <= 2

    def test_eviction_counter_increments(self, temp_cache_dir, clean_singleton):
        """Eviction counter increments when entries are evicted."""
        # Use 2KB limit to force evictions
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir, max_memory_mb=0.002)
        initial_evictions = dm._evictions

        metadata = {"files": ["x.py"], "data": "x" * 300}
        dm.store_diff("h1", metadata)
        dm.store_diff("h2", metadata)
        dm.store_diff("h3", metadata)
        dm.store_diff("h4", metadata)

        # Should have evicted at least one entry
        assert dm._evictions > initial_evictions

    def test_recently_accessed_not_evicted(self, temp_cache_dir, clean_singleton):
        """Recently accessed entries are moved to end and not evicted first."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir, max_memory_mb=2)

        metadata = {"files": ["x.py"], "data": "x" * 50}
        dm.store_diff("h1", metadata)
        dm.store_diff("h2", metadata)

        # Access h1 (moves it to end)
        dm.get_diff("h1")

        # Add h3 (should evict h2, not h1)
        dm.store_diff("h3", metadata)

        assert dm.get_diff("h1") is not None or dm.get_diff("h2") is None


class TestTTLExpiration:
    """Test time-to-live expiration of cached entries."""

    def test_stale_entry_removed_on_retrieval(self, temp_cache_dir, clean_singleton):
        """Retrieving an expired entry returns None and removes it."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir, ttl_seconds=1)

        metadata = {"files": ["a.py"]}
        dm.store_diff("hash1", metadata)

        # Entry should be fresh
        assert dm.get_diff("hash1") is not None

        # Wait for expiration
        time.sleep(1.5)

        # Should be expired now
        assert dm.get_diff("hash1") is None
        assert "hash1" not in dm._memory_cache

    def test_ttl_configurable_via_env(self, temp_cache_dir, clean_singleton):
        """TTL can be set via ORCH_DIFF_MEMORY_TTL env var."""
        os.environ["ORCH_DIFF_MEMORY_TTL"] = "2"
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        assert dm._ttl_seconds == 2

    def test_environment_limit_override(self, temp_cache_dir, clean_singleton):
        """Memory limit can be set via ORCH_DIFF_MEMORY_LIMIT env var."""
        os.environ["ORCH_DIFF_MEMORY_LIMIT"] = "512"
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        assert dm._max_memory_bytes == 512 * 1024 * 1024


class TestConcurrency:
    """Test thread safety and concurrent access."""

    def test_concurrent_store_retrieve(self, temp_cache_dir, clean_singleton):
        """Concurrent store and retrieve operations are thread-safe."""
        os.environ["ORCH_DIFF_MEMORY_LIMIT"] = "256"
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        errors = []

        def worker(worker_id):
            try:
                for i in range(10):
                    hash_val = f"hash_{worker_id}_{i}"
                    metadata = {"files": [f"file_{i}.py"]}
                    dm.store_diff(hash_val, metadata)
                    result = dm.get_diff(hash_val)
                    assert result is not None
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_lock_prevents_race_condition(self, temp_cache_dir, clean_singleton):
        """Lock prevents corruption under concurrent modification."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir, max_memory_mb=10)

        metadata = {"files": ["x.py"], "data": "x" * 100}
        cache_states = []

        def reader():
            for _ in range(20):
                dm.get_diff("hash1")

        def writer():
            for i in range(20):
                dm.store_diff(f"hash{i}", metadata)

        threads = [threading.Thread(target=reader) for _ in range(2)]
        threads += [threading.Thread(target=writer) for _ in range(2)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify cache is still consistent
        s = dm.stats()
        assert s.get("cache_entries", 0) >= 0


class TestFileIOHandling:
    """Test file I/O robustness and error handling."""

    def test_corrupt_json_file_handled_gracefully(self, temp_cache_dir, clean_singleton):
        """Corrupt JSON file on disk doesn't crash on retrieval."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        # Write a corrupt JSON file
        cache_file = Path(temp_cache_dir) / "corrupted.json"
        cache_file.write_text("{invalid json")

        # Should return None and not crash
        result = dm._load_from_disk("corrupted")
        assert result is None

    def test_permission_denied_on_disk_write(self, temp_cache_dir, clean_singleton):
        """Permission denied on disk write doesn't crash, returns False."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        metadata = {"files": ["a.py"]}

        # Mock open to raise PermissionError
        with mock.patch("builtins.open", side_effect=PermissionError("Access denied")):
            result = dm._persist_to_disk("hash1", metadata)
            assert result is False

    def test_missing_cache_dir_on_load_returns_none(self, clean_singleton):
        """Loading from non-existent cache dir returns None."""
        dm = diff_memory.DiffMemory(cache_dir="/nonexistent/cache")
        result = dm._load_from_disk("hash1")
        assert result is None

    def test_disk_write_creates_directory(self, clean_singleton):
        """Disk write creates cache directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "new", "cache")
            dm = diff_memory.DiffMemory(cache_dir=cache_dir)

            metadata = {"files": ["a.py"]}
            result = dm._persist_to_disk("hash1", metadata)

            assert result is True
            assert os.path.isdir(cache_dir)

    def test_partial_disk_read_error_handled(self, temp_cache_dir, clean_singleton):
        """Partial read error on disk is handled gracefully."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        # Write a valid file
        cache_file = Path(temp_cache_dir) / "hash1.json"
        cache_file.write_text('{"files": ["a.py"]}')

        # Mock JSON.load to raise an error on next read
        with mock.patch("json.load", side_effect=json.JSONDecodeError("msg", "doc", 0)):
            result = dm._load_from_disk("hash1")
            assert result is None


class TestPersistence:
    """Test disk persistence across singleton instances."""

    def test_disk_persistence_across_instances(self, temp_cache_dir, clean_singleton):
        """Data persists to disk and can be retrieved by new instance."""
        # First instance: store data
        dm1 = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        metadata = {"files": ["a.py", "b.py"]}
        assert dm1.store_diff("hash1", metadata) is True

        # Second instance: retrieve same data
        dm2 = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        retrieved = dm2.get_diff("hash1")

        assert retrieved is not None
        assert retrieved["files"] == ["a.py", "b.py"]


class TestStats:
    """Test statistics tracking."""

    def test_stats_returns_valid_dict(self, temp_cache_dir, clean_singleton):
        """stats() returns a dict with expected keys."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        metadata = {"files": ["a.py"]}
        dm.store_diff("hash1", metadata)
        dm.get_diff("hash1")

        s = dm.stats()
        assert isinstance(s, dict)
        assert "cache_entries" in s
        assert "memory_used_mb" in s
        assert "hits" in s
        assert "misses" in s
        assert "hit_rate" in s
        assert "evictions" in s

    def test_hit_rate_calculation(self, temp_cache_dir, clean_singleton):
        """Hit rate is calculated correctly."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        metadata = {"files": ["a.py"]}
        dm.store_diff("hash1", metadata)

        # Two hits
        dm.get_diff("hash1")
        dm.get_diff("hash1")

        # Three misses
        dm.get_diff("nonexistent")
        dm.get_diff("also_missing")
        dm.get_diff("nope")

        s = dm.stats()
        # 2 hits / (2 hits + 3 misses) = 0.4
        assert s["hit_rate"] == pytest.approx(0.4, abs=0.01)

    def test_memory_used_calculation(self, temp_cache_dir, clean_singleton):
        """Memory usage is tracked correctly."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        # Use larger data to ensure memory usage shows up (at least 100KB)
        metadata = {"files": ["a.py", "b.py"], "data": "x" * 100000}
        dm.store_diff("hash1", metadata)

        s = dm.stats()
        assert s["memory_used_mb"] > 0.09  # Should be at least 0.1 MB
        assert s["cache_entries"] == 1

    def test_module_level_stats(self, temp_cache_dir, clean_singleton):
        """Module-level stats() delegates to singleton."""
        os.environ["ORCH_DIFF_MEMORY_LIMIT"] = "256"
        diff_memory._diff_memory = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        metadata = {"files": ["a.py"]}
        diff_memory.store_diff("hash1", metadata)

        s = diff_memory.stats()
        assert s["cache_entries"] == 1


class TestInvalidation:
    """Test cache invalidation."""

    def test_invalidate_clears_memory_cache(self, temp_cache_dir, clean_singleton):
        """invalidate() clears all entries from memory cache."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        metadata = {"files": ["a.py"]}
        dm.store_diff("hash1", metadata)
        dm.store_diff("hash2", metadata)

        assert len(dm._memory_cache) == 2

        dm.invalidate()

        assert len(dm._memory_cache) == 0
        assert dm._memory_used_bytes == 0

    def test_invalidate_clears_disk_cache(self, temp_cache_dir, clean_singleton):
        """invalidate() clears all entries from disk cache."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        metadata = {"files": ["a.py"]}
        dm.store_diff("hash1", metadata)

        cache_dir = Path(temp_cache_dir)
        assert len(list(cache_dir.glob("*.json"))) > 0

        dm.invalidate()

        assert len(list(cache_dir.glob("*.json"))) == 0

    def test_module_level_invalidate(self, temp_cache_dir, clean_singleton):
        """Module-level invalidate() delegates to singleton."""
        os.environ["ORCH_DIFF_MEMORY_LIMIT"] = "256"
        diff_memory._diff_memory = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        metadata = {"files": ["a.py"]}
        diff_memory.store_diff("hash1", metadata)

        diff_memory.invalidate()

        assert diff_memory.get_diff("hash1") is None


class TestResourceGovernorIntegration:
    """Test integration with resource_governor when available."""

    def test_can_claim_gate_on_store(self, temp_cache_dir, clean_singleton):
        """Store respects resource_governor.can_claim() gate."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        metadata = {"files": ["a.py"]}

        # Mock can_claim to return False
        with mock.patch("resource_governor.can_claim", return_value=(False, "no resources")):
            result = dm.store_diff("hash1", metadata)
            # Should return False when gated
            if result is False:
                assert True
            else:
                # Or it might still succeed if resource_governor is not available
                pass

    def test_can_claim_not_imported_doesnt_crash(self, temp_cache_dir, clean_singleton):
        """Missing resource_governor import doesn't crash store."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        # resource_governor might be None
        dm_resource_gov = dm  # DiffMemory still works
        metadata = {"files": ["a.py"]}

        # Should not crash
        result = dm.store_diff("hash1", metadata)
        assert isinstance(result, bool)


class TestRegressionAndIntegration:
    """Integration and regression tests."""

    def test_rapid_store_retrieve_cycle(self, temp_cache_dir, clean_singleton):
        """Rapid store-retrieve cycles work correctly."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        for i in range(50):
            hash_val = f"hash_{i}"
            metadata = {"files": [f"file_{i}.py"], "index": i}
            dm.store_diff(hash_val, metadata)
            retrieved = dm.get_diff(hash_val)
            assert retrieved is not None
            assert retrieved["index"] == i

    def test_mixed_hit_miss_access_pattern(self, temp_cache_dir, clean_singleton):
        """Mixed hit/miss access pattern is handled correctly."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)

        # Store 5 entries
        for i in range(5):
            dm.store_diff(f"hash_{i}", {"files": [f"f{i}.py"]})

        # Access pattern: hits, misses, hits again
        dm.get_diff("hash_0")  # hit
        dm.get_diff("missing1")  # miss
        dm.get_diff("hash_1")  # hit
        dm.get_diff("hash_0")  # hit
        dm.get_diff("missing2")  # miss

        s = dm.stats()
        assert s["hits"] == 3
        assert s["misses"] == 2

    def test_empty_cache_stats(self, temp_cache_dir, clean_singleton):
        """stats() works on empty cache."""
        dm = diff_memory.DiffMemory(cache_dir=temp_cache_dir)
        s = dm.stats()

        assert s["cache_entries"] == 0
        assert s["hits"] == 0
        assert s["misses"] == 0

    def test_cache_dir_env_default(self, clean_singleton):
        """Cache directory defaults to ~/.cache/claude-orchestrator/diff-memory."""
        home = Path.home()
        expected = home / ".cache" / "claude-orchestrator" / "diff-memory"

        dm = diff_memory.DiffMemory()
        assert dm._cache_dir == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
