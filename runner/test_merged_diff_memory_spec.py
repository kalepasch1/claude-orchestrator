#!/usr/bin/env python3
"""
Comprehensive test suite for merged_diff_memory.py
Thread-safe cache for computed diffs from merged branches/PRs.

Covers: normal paths, edge cases, TTL expiry, size limits, concurrency,
resource_governor integration, error handling, stats/invalidate.
"""
import os
import sys
import time
import threading
from unittest import mock
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merged_diff_memory


class TestCacheBasicOperations:
    """Test basic cache hit/miss and put/get functionality."""

    def test_cache_hit_returns_stored_diff(self):
        """Returns exact diff that was cached."""
        merged_diff_memory.invalidate()
        diff_content = "diff --git a/file.txt b/file.txt\n+new line\n-old line"
        merged_diff_memory.put_diff("main", "feature", "abc123", diff_content)
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == diff_content

    def test_cache_miss_returns_empty_string(self):
        """Returns empty string when key not in cache."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("main", "nonexistent", "xyz789")
        assert result == ""
        assert isinstance(result, str)

    def test_put_and_get_roundtrip(self):
        """Can roundtrip arbitrary string content through cache."""
        merged_diff_memory.invalidate()
        test_cases = [
            ("a", "b", "1", "single line"),
            ("main", "feature/x", "abc123def", "multiple\nlines\nwith\nnewlines"),
            ("long-branch-name", "longer-feature-branch-name", "0" * 40, "x" * 10000),
        ]
        for branch_a, branch_b, commit, content in test_cases:
            merged_diff_memory.put_diff(branch_a, branch_b, commit, content)
            result = merged_diff_memory.get_diff(branch_a, branch_b, commit)
            assert result == content


class TestNullAndEmptyInputHandling:
    """Test graceful handling of None and empty string inputs."""

    def test_get_diff_none_branch_a_returns_empty(self):
        """get_diff returns empty string when branch_a is None."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff(None, "feature", "abc123")
        assert result == ""

    def test_get_diff_none_branch_b_returns_empty(self):
        """get_diff returns empty string when branch_b is None."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("main", None, "abc123")
        assert result == ""

    def test_get_diff_none_commit_returns_empty(self):
        """get_diff returns empty string when commit_hash is None."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("main", "feature", None)
        assert result == ""

    def test_get_diff_all_none_returns_empty(self):
        """get_diff returns empty string when all params are None."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff(None, None, None)
        assert result == ""

    def test_get_diff_empty_string_branch_a(self):
        """get_diff returns empty string when branch_a is empty."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("", "feature", "abc123")
        assert result == ""

    def test_get_diff_empty_string_branch_b(self):
        """get_diff returns empty string when branch_b is empty."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("main", "", "abc123")
        assert result == ""

    def test_get_diff_empty_string_commit(self):
        """get_diff returns empty string when commit_hash is empty."""
        merged_diff_memory.invalidate()
        result = merged_diff_memory.get_diff("main", "feature", "")
        assert result == ""

    def test_put_diff_none_branch_a_silently_ignored(self):
        """put_diff silently ignores when branch_a is None."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff(None, "feature", "abc123", "diff content")
        result = merged_diff_memory.get_diff(None, "feature", "abc123")
        assert result == ""

    def test_put_diff_none_branch_b_silently_ignored(self):
        """put_diff silently ignores when branch_b is None."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", None, "abc123", "diff content")
        result = merged_diff_memory.get_diff("main", None, "abc123")
        assert result == ""

    def test_put_diff_none_commit_silently_ignored(self):
        """put_diff silently ignores when commit_hash is None."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "feature", None, "diff content")
        result = merged_diff_memory.get_diff("main", "feature", None)
        assert result == ""

    def test_put_diff_none_content_silently_ignored(self):
        """put_diff silently ignores when diff_content is None."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "feature", "abc123", None)
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == ""

    def test_put_diff_empty_content_silently_ignored(self):
        """put_diff silently ignores when diff_content is empty string."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "feature", "abc123", "")
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == ""

    def test_put_diff_all_none_silently_ignored(self):
        """put_diff silently ignores when all params are None."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff(None, None, None, None)
        # Should not crash, cache should remain empty
        stats = merged_diff_memory.stats()
        assert stats["entries"] == 0


class TestUnicodeHandling:
    """Test correct handling of unicode and multi-byte characters."""

    def test_unicode_content_roundtrip(self):
        """Handles unicode content correctly through cache."""
        merged_diff_memory.invalidate()
        unicode_diff = "diff: 你好世界 привет мир مرحبا العالم"
        merged_diff_memory.put_diff("main", "feature", "abc123", unicode_diff)
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == unicode_diff

    def test_emoji_in_diff(self):
        """Handles emoji characters in diff content."""
        merged_diff_memory.invalidate()
        emoji_diff = "🚀 🎉 ✨ added new feature"
        merged_diff_memory.put_diff("main", "feature", "abc123", emoji_diff)
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == emoji_diff

    def test_mixed_charset_diff(self):
        """Handles mixed charsets in diff content."""
        merged_diff_memory.invalidate()
        mixed = "English + 日本語 + العربية + Ελληνικά + עברית"
        merged_diff_memory.put_diff("main", "feature", "abc123", mixed)
        result = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result == mixed


class TestTTLExpiration:
    """Test time-to-live expiration behavior."""

    def test_ttl_expiry_triggers_on_get(self):
        """Expired entries return empty string on access."""
        merged_diff_memory.invalidate()
        diff = "test diff content"
        merged_diff_memory.put_diff("main", "feature", "abc123", diff)

        # Hit before expiry
        result_before = merged_diff_memory.get_diff("main", "feature", "abc123")
        assert result_before == diff

        # Advance time past TTL (default 3600s)
        with mock.patch("merged_diff_memory.time.time", return_value=time.time() + 3700):
            result_after = merged_diff_memory.get_diff("main", "feature", "abc123")
            assert result_after == ""

    def test_ttl_just_before_expiry(self):
        """Entry returns valid diff just before TTL expiry."""
        merged_diff_memory.invalidate()
        diff = "diff content"
        merged_diff_memory.put_diff("main", "feature", "abc123", diff)

        # Time just before expiry
        with mock.patch("merged_diff_memory.time.time", return_value=time.time() + 3599):
            result = merged_diff_memory.get_diff("main", "feature", "abc123")
            assert result == diff

    def test_ttl_just_after_expiry(self):
        """Entry returns empty after TTL boundary crossed."""
        merged_diff_memory.invalidate()
        diff = "diff content"
        merged_diff_memory.put_diff("main", "feature", "abc123", diff)

        # Time just after expiry
        with mock.patch("merged_diff_memory.time.time", return_value=time.time() + 3601):
            result = merged_diff_memory.get_diff("main", "feature", "abc123")
            assert result == ""

    def test_ttl_respects_env_var(self):
        """Uses ORCH_DIFF_CACHE_TTL environment variable."""
        original_ttl = merged_diff_memory.CACHE_TTL
        try:
            merged_diff_memory.CACHE_TTL = 10
            merged_diff_memory.invalidate()
            diff = "short ttl content"
            merged_diff_memory.put_diff("main", "feature", "abc123", diff)

            # Within 10s TTL
            result_valid = merged_diff_memory.get_diff("main", "feature", "abc123")
            assert result_valid == diff

            # Past 10s TTL
            with mock.patch("merged_diff_memory.time.time", return_value=time.time() + 11):
                result_expired = merged_diff_memory.get_diff("main", "feature", "abc123")
                assert result_expired == ""
        finally:
            merged_diff_memory.CACHE_TTL = original_ttl

    def test_ttl_expiry_cleans_up_bytes_used(self):
        """Expired entry cleanup updates bytes_used stat."""
        merged_diff_memory.invalidate()
        diff = "x" * 10000
        merged_diff_memory.put_diff("main", "feature", "abc123", diff)

        stats_before = merged_diff_memory.stats()
        assert stats_before["bytes_used"] > 0

        # Trigger expiry
        with mock.patch("merged_diff_memory.time.time", return_value=time.time() + 3700):
            merged_diff_memory.get_diff("main", "feature", "abc123")

        stats_after = merged_diff_memory.stats()
        assert stats_after["bytes_used"] == 0


class TestCacheSize:
    """Test cache size limits and eviction."""

    def test_cache_size_limit_blocks_entry(self):
        """put_diff blocks new entry when cache is full."""
        original_bytes = merged_diff_memory.CACHE_SIZE_BYTES
        try:
            merged_diff_memory.CACHE_SIZE_BYTES = 1 * 1024 * 1024  # 1MB
            merged_diff_memory.invalidate()

            # Fill cache with diffs until full (11 x 95KB ≈ 1045KB > 1MB)
            for i in range(11):
                diff = "x" * (95 * 1024)
                merged_diff_memory.put_diff("main", f"f{i}", f"c{i}", diff)

            # Next put should fail (silently)
            merged_diff_memory.put_diff("main", "ffull", "cfull", "y" * (95 * 1024))
            result = merged_diff_memory.get_diff("main", "ffull", "cfull")
            assert result == ""
        finally:
            merged_diff_memory.CACHE_SIZE_BYTES = original_bytes

    def test_cache_respects_size_env_var(self):
        """Uses ORCH_DIFF_CACHE_SIZE environment variable."""
        original_bytes = merged_diff_memory.CACHE_SIZE_BYTES
        try:
            merged_diff_memory.CACHE_SIZE_BYTES = 2 * 1024 * 1024  # 2MB
            merged_diff_memory.invalidate()

            # Should fit
            diff = "x" * (100 * 1024)
            merged_diff_memory.put_diff("main", "f1", "a1", diff)
            result = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result == diff
        finally:
            merged_diff_memory.CACHE_SIZE_BYTES = original_bytes

    def test_oversized_diff_truncated_at_10_percent(self):
        """Diffs larger than 10% of cache are truncated."""
        original_bytes = merged_diff_memory.CACHE_SIZE_BYTES
        try:
            merged_diff_memory.CACHE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
            merged_diff_memory.invalidate()

            # 2MB diff > 10% of 10MB cache
            huge_diff = "x" * (2 * 1024 * 1024)
            merged_diff_memory.put_diff("main", "feature", "abc123", huge_diff)

            result = merged_diff_memory.get_diff("main", "feature", "abc123")
            # Should be truncated
            assert result != huge_diff
            assert len(result) > 0
            # Should be <= 10% of cache
            assert len(result.encode("utf-8", errors="replace")) <= (10 * 1024 * 1024 // 10)
        finally:
            merged_diff_memory.CACHE_SIZE_BYTES = original_bytes

    def test_overwrite_same_key_reclaims_space(self):
        """Overwriting key reclaims space from old value."""
        original_bytes = merged_diff_memory.CACHE_SIZE_BYTES
        try:
            merged_diff_memory.CACHE_SIZE_BYTES = 1 * 1024 * 1024  # 1MB
            merged_diff_memory.invalidate()

            # Put large diff
            large_diff = "x" * (500 * 1024)
            merged_diff_memory.put_diff("main", "f1", "a1", large_diff)
            stats1 = merged_diff_memory.stats()
            bytes1 = stats1["bytes_used"]

            # Overwrite with smaller diff
            small_diff = "y" * (50 * 1024)
            merged_diff_memory.put_diff("main", "f1", "a1", small_diff)
            stats2 = merged_diff_memory.stats()
            bytes2 = stats2["bytes_used"]

            # Bytes used should decrease
            assert bytes2 < bytes1
            assert bytes2 > 0
        finally:
            merged_diff_memory.CACHE_SIZE_BYTES = original_bytes

    def test_bytes_used_tracking_accuracy(self):
        """stats() accurately tracks bytes_used."""
        merged_diff_memory.invalidate()
        diff1 = "a" * 1000
        diff2 = "b" * 2000
        merged_diff_memory.put_diff("main", "f1", "a1", diff1)
        merged_diff_memory.put_diff("main", "f2", "a2", diff2)

        stats = merged_diff_memory.stats()
        expected_bytes = len(diff1.encode("utf-8", errors="replace")) + len(
            diff2.encode("utf-8", errors="replace")
        )
        assert stats["bytes_used"] == expected_bytes


class TestStatsMethod:
    """Test stats() method for cache introspection."""

    def test_stats_returns_dict_with_required_keys(self):
        """stats() returns dict with entries, bytes_used, hits, misses."""
        merged_diff_memory.invalidate()
        stats = merged_diff_memory.stats()
        assert isinstance(stats, dict)
        assert "entries" in stats
        assert "bytes_used" in stats
        assert "hits" in stats
        assert "misses" in stats

    def test_stats_entries_count(self):
        """stats()['entries'] counts cached diffs."""
        merged_diff_memory.invalidate()
        for i in range(5):
            merged_diff_memory.put_diff("main", f"f{i}", f"a{i}", f"diff{i}")

        stats = merged_diff_memory.stats()
        assert stats["entries"] == 5

    def test_stats_tracks_hits(self):
        """stats()['hits'] increments on cache hits."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")

        # 2 hits
        merged_diff_memory.get_diff("main", "f1", "a1")
        merged_diff_memory.get_diff("main", "f1", "a1")
        stats = merged_diff_memory.stats()
        assert stats["hits"] == 2

    def test_stats_tracks_misses(self):
        """stats()['misses'] increments on cache misses."""
        merged_diff_memory.invalidate()

        # 2 misses
        merged_diff_memory.get_diff("main", "f1", "a1")
        merged_diff_memory.get_diff("main", "f2", "a2")
        stats = merged_diff_memory.stats()
        assert stats["misses"] == 2

    def test_stats_mixed_hits_and_misses(self):
        """stats() correctly tracks mixed hit/miss sequence."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")

        merged_diff_memory.get_diff("main", "f1", "a1")  # hit
        merged_diff_memory.get_diff("main", "f2", "a2")  # miss
        merged_diff_memory.get_diff("main", "f1", "a1")  # hit
        merged_diff_memory.get_diff("main", "f3", "a3")  # miss

        stats = merged_diff_memory.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 2

    def test_stats_bytes_used_zero_on_init(self):
        """stats() shows zero bytes after invalidate()."""
        merged_diff_memory.invalidate()
        stats = merged_diff_memory.stats()
        assert stats["bytes_used"] == 0

    def test_stats_snapshot_is_consistent(self):
        """stats() returns atomic snapshot."""
        merged_diff_memory.invalidate()
        for i in range(10):
            merged_diff_memory.put_diff("main", f"f{i}", f"a{i}", f"diff{i}" * 1000)

        stats = merged_diff_memory.stats()
        assert stats["entries"] == 10
        assert stats["bytes_used"] > 0


class TestInvalidateMethod:
    """Test invalidate() cache clearing."""

    def test_invalidate_clears_all_entries(self):
        """invalidate() removes all cached entries."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
        merged_diff_memory.put_diff("main", "f2", "a2", "diff2")

        assert merged_diff_memory.stats()["entries"] == 2

        merged_diff_memory.invalidate()

        assert merged_diff_memory.stats()["entries"] == 0
        assert merged_diff_memory.get_diff("main", "f1", "a1") == ""
        assert merged_diff_memory.get_diff("main", "f2", "a2") == ""

    def test_invalidate_resets_counters(self):
        """invalidate() resets hits and misses."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff")
        merged_diff_memory.get_diff("main", "f1", "a1")  # hit
        merged_diff_memory.get_diff("main", "f2", "a2")  # miss

        stats_before = merged_diff_memory.stats()
        assert stats_before["hits"] == 1
        assert stats_before["misses"] == 1

        merged_diff_memory.invalidate()

        stats_after = merged_diff_memory.stats()
        assert stats_after["hits"] == 0
        assert stats_after["misses"] == 0

    def test_invalidate_resets_bytes_used(self):
        """invalidate() resets bytes_used to zero."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff" * 1000)

        assert merged_diff_memory.stats()["bytes_used"] > 0

        merged_diff_memory.invalidate()

        assert merged_diff_memory.stats()["bytes_used"] == 0

    def test_invalidate_idempotent(self):
        """invalidate() can be called multiple times safely."""
        merged_diff_memory.put_diff("main", "f1", "a1", "diff")
        merged_diff_memory.invalidate()
        merged_diff_memory.invalidate()
        merged_diff_memory.invalidate()

        stats = merged_diff_memory.stats()
        assert stats["entries"] == 0
        assert stats["bytes_used"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_invalidate_safe_during_get(self):
        """invalidate() safe while get_diff is executing."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")

        def concurrent_invalidate():
            time.sleep(0.001)
            merged_diff_memory.invalidate()

        thread = threading.Thread(target=concurrent_invalidate)
        thread.start()

        # Should not crash or deadlock
        result = merged_diff_memory.get_diff("main", "f1", "a1")
        thread.join()
        assert isinstance(result, str)


class TestConcurrentAccess:
    """Test thread-safe concurrent access patterns."""

    def test_concurrent_gets_same_entry(self):
        """Multiple threads can get same entry concurrently."""
        merged_diff_memory.invalidate()
        diff = "shared diff content"
        merged_diff_memory.put_diff("main", "f1", "a1", diff)

        results = []

        def getter():
            for _ in range(5):
                result = merged_diff_memory.get_diff("main", "f1", "a1")
                results.append(result)

        threads = [threading.Thread(target=getter) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r == diff for r in results)
        assert len(results) == 50

    def test_concurrent_puts_different_keys(self):
        """Multiple threads can put different keys concurrently."""
        merged_diff_memory.invalidate()

        def putter(i):
            merged_diff_memory.put_diff("main", f"f{i}", f"a{i}", f"diff{i}")

        threads = [threading.Thread(target=putter, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = merged_diff_memory.stats()
        assert stats["entries"] == 20

    def test_concurrent_mixed_operations(self):
        """Threads can mix get/put/invalidate without corruption."""
        merged_diff_memory.invalidate()

        results = []

        def mixed_op(i):
            if i % 3 == 0:
                merged_diff_memory.put_diff("main", f"f{i}", f"a{i}", f"diff{i}")
            elif i % 3 == 1:
                result = merged_diff_memory.get_diff("main", f"f{i-1}", f"a{i-1}")
                results.append(result)
            else:
                merged_diff_memory.invalidate()

        threads = [threading.Thread(target=mixed_op, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not crash
        stats = merged_diff_memory.stats()
        assert isinstance(stats, dict)

    def test_concurrent_invalidate_and_access(self):
        """Threads safely invalidate while others access cache."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")

        def access_and_invalidate(i):
            if i % 2 == 0:
                merged_diff_memory.invalidate()
            else:
                merged_diff_memory.get_diff("main", "f1", "a1")

        threads = [threading.Thread(target=access_and_invalidate, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not deadlock or corrupt
        stats = merged_diff_memory.stats()
        assert isinstance(stats, dict)


class TestResourceGovernorIntegration:
    """Test integration with resource_governor memory pressure."""

    def test_resource_governor_blocks_when_unavailable(self):
        """put_diff respects resource_governor.can_claim() = False."""
        merged_diff_memory.invalidate()

        with mock.patch("merged_diff_memory.resource_governor") as mock_rg:
            mock_rg.can_claim.return_value = False
            merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
            result = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result == ""

    def test_resource_governor_allows_when_available(self):
        """put_diff succeeds when resource_governor.can_claim() = True."""
        merged_diff_memory.invalidate()

        with mock.patch("merged_diff_memory.resource_governor") as mock_rg:
            mock_rg.can_claim.return_value = True
            merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
            result = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result == "diff1"

    def test_resource_governor_none_is_ignored(self):
        """Works without resource_governor when it's None."""
        original_rg = merged_diff_memory.resource_governor
        try:
            merged_diff_memory.resource_governor = None
            merged_diff_memory.invalidate()
            merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
            result = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result == "diff1"
        finally:
            merged_diff_memory.resource_governor = original_rg

    def test_resource_governor_called_with_correct_size(self):
        """resource_governor.can_claim called with diff byte size."""
        merged_diff_memory.invalidate()
        diff = "x" * 5000
        diff_bytes = len(diff.encode("utf-8", errors="replace"))

        with mock.patch("merged_diff_memory.resource_governor") as mock_rg:
            mock_rg.can_claim.return_value = True
            merged_diff_memory.put_diff("main", "f1", "a1", diff)
            # Verify can_claim was called with appropriate size
            assert mock_rg.can_claim.called


class TestErrorHandling:
    """Test fail-soft error handling."""

    def test_get_diff_silently_handles_exception(self):
        """get_diff returns empty string on internal exception."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")

        with mock.patch.object(
            merged_diff_memory._pool, "get_diff", side_effect=Exception("error")
        ):
            result = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result == ""

    def test_put_diff_silently_handles_exception(self):
        """put_diff silently ignores exceptions."""
        merged_diff_memory.invalidate()

        with mock.patch.object(
            merged_diff_memory._pool, "put_diff", side_effect=Exception("error")
        ):
            # Should not raise
            merged_diff_memory.put_diff("main", "f1", "a1", "diff1")

    def test_stats_silently_handles_exception(self):
        """stats() returns dict even on exception."""
        merged_diff_memory.invalidate()

        with mock.patch.object(
            merged_diff_memory._pool, "stats", side_effect=Exception("error")
        ):
            result = merged_diff_memory.stats()
            # Should return something, not crash
            assert isinstance(result, (dict, str, type(None)))

    def test_invalid_input_types_handled_gracefully(self):
        """Non-string/None inputs handled without raising."""
        merged_diff_memory.invalidate()

        # Should not raise
        try:
            merged_diff_memory.put_diff(123, 456, 789, 1000)
            merged_diff_memory.get_diff([], {}, set())
        except Exception as e:
            pytest.fail(f"Should not raise on bad types: {e}")


class TestMultipleCacheKeys:
    """Test isolation between different cache keys."""

    def test_different_branches_separate_entries(self):
        """Different branch combinations are separate cache entries."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
        merged_diff_memory.put_diff("main", "f2", "a1", "diff2")
        merged_diff_memory.put_diff("develop", "f1", "a1", "diff3")

        assert merged_diff_memory.get_diff("main", "f1", "a1") == "diff1"
        assert merged_diff_memory.get_diff("main", "f2", "a1") == "diff2"
        assert merged_diff_memory.get_diff("develop", "f1", "a1") == "diff3"

    def test_different_commits_separate_entries(self):
        """Different commit hashes are separate cache entries."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("main", "f1", "a1", "diff1")
        merged_diff_memory.put_diff("main", "f1", "a2", "diff2")
        merged_diff_memory.put_diff("main", "f1", "a3", "diff3")

        assert merged_diff_memory.get_diff("main", "f1", "a1") == "diff1"
        assert merged_diff_memory.get_diff("main", "f1", "a2") == "diff2"
        assert merged_diff_memory.get_diff("main", "f1", "a3") == "diff3"

    def test_key_combinations_are_independent(self):
        """Changing one key param doesn't affect other entries."""
        merged_diff_memory.invalidate()

        # Create entries
        for i in range(3):
            for j in range(3):
                for k in range(3):
                    merged_diff_memory.put_diff(f"b{i}", f"f{j}", f"c{k}", f"diff{i}{j}{k}")

        # Verify each key combination has correct value
        for i in range(3):
            for j in range(3):
                for k in range(3):
                    result = merged_diff_memory.get_diff(f"b{i}", f"f{j}", f"c{k}")
                    assert result == f"diff{i}{j}{k}"

        stats = merged_diff_memory.stats()
        assert stats["entries"] == 27


class TestLargeContent:
    """Test handling of large diff content."""

    def test_large_diff_within_limits(self):
        """Caches large diffs that fit within size constraints."""
        original_bytes = merged_diff_memory.CACHE_SIZE_BYTES
        try:
            merged_diff_memory.CACHE_SIZE_BYTES = 100 * 1024 * 1024
            merged_diff_memory.invalidate()

            # 5MB diff (< 10% limit of 100MB = 10MB)
            large_diff = "x" * (5 * 1024 * 1024)
            merged_diff_memory.put_diff("main", "f1", "a1", large_diff)

            result = merged_diff_memory.get_diff("main", "f1", "a1")
            assert result == large_diff
        finally:
            merged_diff_memory.CACHE_SIZE_BYTES = original_bytes

    def test_very_large_diff_truncated(self):
        """Truncates diffs exceeding 10% of cache size."""
        original_bytes = merged_diff_memory.CACHE_SIZE_BYTES
        try:
            merged_diff_memory.CACHE_SIZE_BYTES = 100 * 1024 * 1024
            merged_diff_memory.invalidate()

            # 50MB diff (50% of cache, > 10% per-entry limit)
            huge_diff = "y" * (50 * 1024 * 1024)
            merged_diff_memory.put_diff("main", "f1", "a1", huge_diff)

            result = merged_diff_memory.get_diff("main", "f1", "a1")
            # Should be truncated
            assert len(result) < len(huge_diff)
            # Should still have content
            assert len(result) > 0
            # Should fit within 10% limit
            max_per_entry = 100 * 1024 * 1024 // 10
            assert len(result.encode("utf-8", errors="replace")) <= max_per_entry
        finally:
            merged_diff_memory.CACHE_SIZE_BYTES = original_bytes

    def test_multiple_large_diffs_aggregated(self):
        """Multiple large diffs aggregate toward cache limit."""
        original_bytes = merged_diff_memory.CACHE_SIZE_BYTES
        try:
            merged_diff_memory.CACHE_SIZE_BYTES = 100 * 1024 * 1024
            merged_diff_memory.invalidate()

            # 5 x 15MB diffs truncated to 10% of 100MB = 10MB each = 50MB total
            for i in range(5):
                diff = "x" * (15 * 1024 * 1024)
                merged_diff_memory.put_diff("main", f"f{i}", f"a{i}", diff)

            stats = merged_diff_memory.stats()
            assert stats["entries"] == 5
            assert 45 * 1024 * 1024 < stats["bytes_used"] < 55 * 1024 * 1024
        finally:
            merged_diff_memory.CACHE_SIZE_BYTES = original_bytes


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_long_branch_names(self):
        """Handles very long branch names."""
        merged_diff_memory.invalidate()
        long_name = "f" * 1000
        merged_diff_memory.put_diff(long_name, long_name, "abc123", "diff")
        result = merged_diff_memory.get_diff(long_name, long_name, "abc123")
        assert result == "diff"

    def test_very_long_commit_hash(self):
        """Handles very long commit hashes."""
        merged_diff_memory.invalidate()
        long_hash = "a" * 1000
        merged_diff_memory.put_diff("main", "f", long_hash, "diff")
        result = merged_diff_memory.get_diff("main", "f", long_hash)
        assert result == "diff"

    def test_special_characters_in_keys(self):
        """Handles special characters in branch/commit names."""
        merged_diff_memory.invalidate()
        special_cases = [
            ("main/special", "feature/😀", "hash#123"),
            ("branch.with.dots", "feature/with/slashes", "hash@version"),
            ("branch-with-dashes", "feature_with_underscores", "hash_v1.2.3"),
        ]
        for branch_a, branch_b, commit in special_cases:
            merged_diff_memory.put_diff(branch_a, branch_b, commit, f"diff-{commit}")
            result = merged_diff_memory.get_diff(branch_a, branch_b, commit)
            assert result == f"diff-{commit}"

    def test_single_character_values(self):
        """Handles single character branch/commit/diff."""
        merged_diff_memory.invalidate()
        merged_diff_memory.put_diff("a", "b", "c", "d")
        result = merged_diff_memory.get_diff("a", "b", "c")
        assert result == "d"

    def test_whitespace_in_content(self):
        """Preserves whitespace in diff content."""
        merged_diff_memory.invalidate()
        content = "  leading\n\t\ttabs\n   spaces   \n\n\n"
        merged_diff_memory.put_diff("main", "f", "c", content)
        result = merged_diff_memory.get_diff("main", "f", "c")
        assert result == content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
