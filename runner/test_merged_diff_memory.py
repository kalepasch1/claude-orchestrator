#!/usr/bin/env python3
"""
Test suite for merged_diff_memory.py - Thread-safe diff cache for merged branches.

Tests cover:
- Normal operation: cache hit, TTL expiry, size eviction
- Edge cases: None keys, empty strings, oversized diffs
- Concurrency: multiple threads accessing cache
- Memory pressure: resource_governor blocking
- Staleness: TTL-based eviction
- Operator methods: stats() and invalidate()
"""
import os
import sys
import time
import threading
from unittest import mock
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merged_diff_memory


class TestGetDiffBasic:
    """Test basic cache hit/miss functionality."""

    def test_get_diff_cache_hit(self):
        """Returns cached diff on cache hit."""
        merged_diff_memory.invalidate()
        diff = "diff --git a/file.txt b/file.txt\n+new line"
        merged_diff_memory.put_diff("main", "feature", "abc123", diff)
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == diff

    def test_get_diff_cache_miss(self):
        """Returns empty string on cache miss."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("main", "nonexistent", "xyz789")
        assert result == ""

    def test_get_diff_none_branch_a(self):
        """Returns empty string when branch_a is None."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff(None, "feature", "abc123")
        assert result == ""

    def test_get_diff_none_branch_b(self):
        """Returns empty string when branch_b is None."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("main", None, "abc123")
        assert result == ""

    def test_get_diff_none_commit(self):
        """Returns empty string when commit_hash is None."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("main", "feature", None)
        assert result == ""

    def test_get_diff_empty_string_branch_a(self):
        """Returns empty string when branch_a is empty string."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("", "feature", "abc123")
        assert result == ""

    def test_get_diff_empty_string_branch_b(self):
        """Returns empty string when branch_b is empty string."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("main", "", "abc123")
        assert result == ""

    def test_get_diff_empty_string_commit(self):
        """Returns empty string when commit_hash is empty string."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("main", "feature", "")
        assert result == ""


class TestPutDiffBasic:
    """Test basic cache insertion."""

    def test_put_diff_simple(self):
        """Caches a diff successfully."""
        merged_diff_memory.invalidate()
        diff = "diff content"
        merged_diff_memory.put_diff("main", "feature", "abc123", diff)
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == diff

    def test_put_diff_none_branch_a(self):
        """Silently ignores put when branch_a is None."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff(None, "feature", "abc123", "diff")
        result = merged_diff_memory.get_diff(None, "feature", "abc123")
        assert result == ""

    def test_put_diff_none_branch_b(self):
        """Silently ignores put when branch_b is None."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", None, "abc123", "diff")
        result = merged_diff_memory.get_diff("main", None, "abc123")
        assert result == ""

    def test_put_diff_none_commit(self):
        """Silently ignores put when commit_hash is None."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "feature", None, "diff")
        result = merged_diff_memory.get_diff("main", "feature", None)
        assert result == ""

    def test_put_diff_none_content(self):
        """Silently ignores put when diff_content is None."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "feature", "abc123", None)
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == ""

    def test_put_diff_empty_content(self):
        """Silently ignores put when diff_content is empty string."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "feature", "abc123", "")
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == ""

    def test_put_diff_overwrites_old(self):
        """Overwrites old entry for same key."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "feature", "abc123", "old diff")
        merged_diff_memory.put_diff("main", "feature", "abc123", "new diff")
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == "new diff"

    def test_put_diff_unicode(self):
        """Handles unicode content correctly."""
        merged_diff_memory.invalidate()
        diff = "diff with unicode: 你好世界 🚀 café"
        merged_diff_memory.put_diff("main", "feature", "abc123", diff)
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == diff


class TestTTLExpiry:
    """Test time-to-live expiration."""

    def test_ttl_expiry_triggers(self):
        """Cache returns empty string when TTL expires."""
        merged_diff_memory.invalidate()
        diff = "test diff"
        merged_diff_memory.put_diff("main", "feature", "abc123", diff)

        # Verify cache hit before expiry
        result1 = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result1 == diff

        # Move time forward past TTL
        with mock.patch("merged_diff_memory.time.time", return_value=time.time() + 3700):
            result2 = merged_diff_memory.get_diff("main", "feature", "abc123")
            assert result2 == ""

    def test_ttl_respects_env_var(self):
        """Uses ORCH_DIFF_CACHE_TTL from environment."""
        with mock.patch.dict(os.environ, {"ORCH_DIFF_CACHE_TTL": "10"}):
            merged_diff_memory.CACHE_TTL = 10
            merged_diff_memory.invalidate()
            diff = "test diff"
            merged_diff_memory.put_diff("main", "feature", "abc123", diff)

            # Move time forward by 11 seconds (past 10s TTL)
            with mock.patch("merged_diff_memory.time.time", return_value=time.time() + 11):
                result = merged_diff_memory.get_diff("main", "feature", "abc123")
                assert result == ""


class TestCacheSize:
    """Test cache size limits and eviction."""

    def test_cache_size_limit_blocks_new_entry(self):
        """Silently ignores put when cache is full."""
        with mock.patch.dict(os.environ, {"ORCH_DIFF_CACHE_SIZE": "1"}):  # 1MB limit
            merged_diff_memory.CACHE_SIZE_BYTES = 1 * 1024 * 1024
            merged_diff_memory.invalidate()

            # Fill cache with 11 x 95KB diffs (1045KB total > 1MB)
            for i in range(11):
                diff = "x" * (95 * 1024)  # 95KB each
                merged_diff_memory.put_diff("main", f"feature{i}", f"commit{i}", diff)

            # Try to add another 95KB diff (should fail - cache is now full)
            merged_diff_memory.put_diff("main", "featurefull", "commitfull", "y" * (95 * 1024))
            result = merged_diff_memory.get_diff("main", "featurefull", "commitfull")
            assert result == ""

    def test_cache_respects_size_env_var(self):
        """Uses ORCH_DIFF_CACHE_SIZE from environment."""
        with mock.patch.dict(os.environ, {"ORCH_DIFF_CACHE_SIZE": "2"}):
            merged_diff_memory.CACHE_SIZE_BYTES = 2 * 1024 * 1024
            merged_diff_memory.invalidate()

            # Should allow 2MB of diffs (max 10% per entry = 200KB)
            diff1 = "x" * (100 * 1024)  # 100KB - safe
            merged_diff_memory.put_diff("main", "f1", "a1", diff1)
            result1 = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result1 == diff1

    def test_cache_truncates_oversized_diff(self):
        """Truncates diff if it exceeds 10% of cache size."""
        with mock.patch.dict(os.environ, {"ORCH_DIFF_CACHE_SIZE": "10"}):  # 10MB
            merged_diff_memory.CACHE_SIZE_BYTES = 10 * 1024 * 1024
            merged_diff_memory.invalidate()

            # Try to cache a diff > 10% of cache (> 1MB)
            huge_diff = "x" * (2 * 1024 * 1024)  # 2MB
            merged_diff_memory.put_diff("main", "feature", "abc123", huge_diff)

            result = merged_diff_memory.get_diff("main", "feature", "abc123")
            # Should be truncated, so not equal to original
            assert result != huge_diff
            # But should have something cached
            assert len(result) > 0
            # Should be <= 10% of cache
            assert len(result.encode("utf-8", errors="replace")) <= (
                10 * 1024 * 1024 // 10
            )

    def test_cache_tracks_bytes_used(self):
        """stats() reports accurate bytes_used."""
        merged_diff_memory.invalidate()
        diff1 = "x" * 1000
        diff2 = "y" * 2000
        merged_diff_memory.put_diff("main", "f1", "a1", diff1)
        merged_diff_memory.put_diff("main", "f2", "a2", diff2)

        stats = merged_diff_memory.stats()
        expected_bytes = len(diff1.encode("utf-8", errors="replace")) + len(
            diff2.encode("utf-8", errors="replace")
        )
        assert stats["bytes_used"] == expected_bytes


class TestStats:
    """Test stats() method."""

    def test_stats_entries_count(self):
        """stats() returns correct entry count."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
        merged_diff_memory.put_diff("main", "f2", "a2", "diff2")
        merged_diff_memory.put_diff("main", "f3", "a3", "diff3")

        stats = merged_diff_memory.stats()
        assert stats["entries"] == 3

    def test_stats_hits_and_misses(self):
        """stats() tracks hits and misses correctly."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")

        # Cache hit
        merged_diff_memory.get_diff("main", "f1", "a1")
        # Cache miss
        merged_diff_memory.get_diff("main", "f2", "a2")
        # Cache hit
        merged_diff_memory.get_diff("main", "f1", "a1")
        # Cache miss
        merged_diff_memory.get_diff("main", "f3", "a3")

        stats = merged_diff_memory.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 2

    def test_stats_bytes_used(self):
        """stats() reports bytes_used correctly."""
        merged_diff_memory.invalidate()
        diff = "test diff content"
        merged_diff_memory.put_diff("main", "f1", "a1", diff)

        stats = merged_diff_memory.stats()
        expected_bytes = len(diff.encode("utf-8", errors="replace"))
        assert stats["bytes_used"] == expected_bytes

    def test_stats_zero_values_on_init(self):
        """stats() returns zeros after invalidate()."""
        merged_diff_memory.invalidate()
        stats = merged_diff_memory.stats()
        assert stats["entries"] == 0
        assert stats["bytes_used"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_stats_dict_has_all_keys(self):
        """stats() returns dict with all required keys."""
        merged_diff_memory.invalidate()
        stats = merged_diff_memory.stats()
        assert "entries" in stats
        assert "bytes_used" in stats
        assert "hits" in stats
        assert "misses" in stats


class TestInvalidate:
    """Test invalidate() method."""

    def test_invalidate_clears_cache(self):
        """invalidate() removes all cached diffs."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
        merged_diff_memory.put_diff("main", "f2", "a2", "diff2")

        # Verify cache has entries
        assert merged_diff_memory.stats()["entries"] > 0

        merged_diff_memory.invalidate()

        # Verify cache is empty
        assert merged_diff_memory.stats()["entries"] == 0
        assert merged_diff_memory.get_diff("main", "f1", "a1") == ""
        assert merged_diff_memory.get_diff("main", "f2", "a2") == ""

    def test_invalidate_resets_counters(self):
        """invalidate() resets hits and misses."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff")
        merged_diff_memory.get_diff("main", "f1", "a1")  # hit
        merged_diff_memory.get_diff("main", "f2", "a2")  # miss

        merged_diff_memory.invalidate()

        stats = merged_diff_memory.stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["bytes_used"] == 0

    def test_invalidate_idempotent(self):
        """invalidate() can be called multiple times safely."""
        merged_diff_memory.put_diff("main", "f1", "a1", "diff")
        merged_diff_memory.invalidate()
        merged_diff_memory.invalidate()
        merged_diff_memory.invalidate()
        assert merged_diff_memory.stats()["entries"] == 0


class TestConcurrency:
    """Test thread-safe concurrent access."""

    def test_concurrent_gets(self):
        """Multiple threads can get diffs concurrently."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")

        results = []

        def get_diff():
            result = merged_diff_memory.get_diff("main", "f1", "a1")
            results.append(result)

        threads = [threading.Thread(target=get_diff) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should get the same result
        assert all(r == "diff1" for r in results)
        assert len(results) == 10

    def test_concurrent_puts(self):
        """Multiple threads can put diffs concurrently."""
        merged_diff_memory.invalidate()

        def put_diff(i):
            merged_diff_memory.put_diff("main", f"f{i}", f"a{i}", f"diff{i}")

        threads = [threading.Thread(target=put_diff, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = merged_diff_memory.stats()
        assert stats["entries"] == 10

    def test_concurrent_get_and_put(self):
        """Threads can get and put concurrently without corruption."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f0", "a0", "diff0")

        results = []

        def mixed_operations(i):
            if i % 2 == 0:
                merged_diff_memory.put_diff("main", f"f{i}", f"a{i}", f"diff{i}")
            else:
                result = merged_diff_memory.get_diff("main", f"f{i-1}", f"a{i-1}")
                results.append(result)

        threads = [threading.Thread(target=mixed_operations, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not crash or corrupt data
        stats = merged_diff_memory.stats()
        assert stats["entries"] > 0

    def test_concurrent_invalidate(self):
        """Threads can invalidate while others get/put."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")

        def access_and_invalidate(i):
            if i % 3 == 0:
                merged_diff_memory.invalidate()
            else:
                merged_diff_memory.get_diff("main", "f1", "a1")

        threads = [threading.Thread(target=access_and_invalidate, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not crash
        stats = merged_diff_memory.stats()
        assert isinstance(stats, dict)


class TestResourceGovernor:
    """Test resource_governor integration."""

    def test_resource_governor_blocks_oversized_diff(self):
        """put_diff respects resource_governor.can_claim()."""
        merged_diff_memory.invalidate()

        with mock.patch("merged_diff_memory.resource_governor") as mock_rg:
            mock_rg.can_claim.return_value = False
            merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
            result = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result == ""

    def test_resource_governor_allows_when_available(self):
        """put_diff succeeds when resource_governor allows."""
        merged_diff_memory.invalidate()

        with mock.patch("merged_diff_memory.resource_governor") as mock_rg:
            mock_rg.can_claim.return_value = True
            merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
            result = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result == "diff1"

    def test_resource_governor_none_is_ignored(self):
        """Works correctly when resource_governor is None."""
        merged_diff_memory.invalidate()
        original_rg = merged_diff_memory.resource_governor
        try:
            merged_diff_memory.resource_governor = None
            merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
            result = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result == "diff1"
        finally:
            merged_diff_memory.resource_governor = original_rg


class TestErrorHandling:
    """Test fail-soft error handling."""

    def test_get_diff_exception_returns_empty(self):
        """get_diff returns empty string on exception."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")

        # Mock internal exception
        with mock.patch.object(
            merged_diff_memory._pool, "get_diff", side_effect=Exception("test error")
        ):
            result = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result == ""

    def test_put_diff_exception_silently_ignored(self):
        """put_diff silently ignores exceptions."""
        merged_diff_memory.invalidate()

        with mock.patch.object(
            merged_diff_memory._pool, "put_diff", side_effect=Exception("test error")
        ):
            # Should not raise
            merged_diff_memory.put_diff("main", "f1", "a1", "diff1")


class TestMultipleKeys:
    """Test handling multiple different cache keys."""

    def test_different_branches_different_entries(self):
        """Different branch combinations create separate cache entries."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
        merged_diff_memory.put_diff("main", "f2", "a1", "diff2")
        merged_diff_memory.put_diff("develop", "f1", "a1", "diff3")

        assert merged_diff_memory.get_diff("main", "f1", "a1") == "diff1"
        assert merged_diff_memory.get_diff("main", "f2", "a1") == "diff2"
        assert merged_diff_memory.get_diff("develop", "f1", "a1") == "diff3"

    def test_different_commits_different_entries(self):
        """Different commit hashes create separate cache entries."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
        merged_diff_memory.put_diff("main", "f1", "a2", "diff2")
        merged_diff_memory.put_diff("main", "f1", "a3", "diff3")

        assert merged_diff_memory.get_diff("main", "f1", "a1") == "diff1"
        assert merged_diff_memory.get_diff("main", "f1", "a2") == "diff2"
        assert merged_diff_memory.get_diff("main", "f1", "a3") == "diff3"

    def test_stats_counts_all_entries(self):
        """stats() counts all entries regardless of key."""
        merged_diff_memory.invalidate()
        for i in range(5):
            merged_diff_memory.put_diff("main", f"f{i}", f"a{i}", f"diff{i}")

        stats = merged_diff_memory.stats()
        assert stats["entries"] == 5


class TestLargeContent:
    """Test handling of large diff content."""

    def test_large_diff_within_limit(self):
        """Caches large diffs that fit within size limit."""
        merged_diff_memory.invalidate()
        # 5MB diff (fits in 100MB cache, but within 10% per-entry limit)
        large_diff = "x" * (5 * 1024 * 1024)
        merged_diff_memory.put_diff("main", "f1", "a1", large_diff)

        result = merged_diff_memory.get_diff("main", "f1", "a1")
        # Should be truncated to 10MB (10% of 100MB cache)
        assert len(result) > 0
        # But not the full size since it exceeds 10% limit
        assert len(result) <= (100 * 1024 * 1024 // 10)

    def test_very_large_diff_truncated(self):
        """Truncates diffs larger than 10% of cache."""
        merged_diff_memory.invalidate()
        # Create a 50MB diff (with 100MB cache, this is 50% of cache, > 10% per-entry limit)
        huge_diff = "y" * (50 * 1024 * 1024)
        merged_diff_memory.put_diff("main", "f1", "a1", huge_diff)

        result = merged_diff_memory.get_diff("main", "f1", "a1")
        # Should be truncated to 10MB (10% of 100MB cache)
        assert len(result) < len(huge_diff)
        # Should still have content
        assert len(result) > 0
        # Should be <= 10% of cache
        assert len(result.encode("utf-8", errors="replace")) <= (
            100 * 1024 * 1024 // 10
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
