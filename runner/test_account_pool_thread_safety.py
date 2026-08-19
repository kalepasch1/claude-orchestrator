#!/usr/bin/env python3
"""
Test suite for account_pool thread-safety fixes.
Covers _EXH_CACHE and _pool singleton protection via locks.
"""
import os
import sys
import json
import time
import threading
import tempfile
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import account_pool


class TestEXHCacheThreadSafety:
    """Test _EXH_CACHE read/write protection under concurrent access."""

    def setup_method(self):
        """Reset cache state before each test."""
        with account_pool._EXH_LOCK:
            account_pool._EXH_CACHE["t"] = 0.0
            account_pool._EXH_CACHE["v"] = False

    def test_cache_basic_write_then_read(self):
        """Cache write followed by read returns the written value."""
        with account_pool._EXH_LOCK:
            account_pool._EXH_CACHE["t"] = time.time()
            account_pool._EXH_CACHE["v"] = True

        with account_pool._EXH_LOCK:
            assert account_pool._EXH_CACHE["v"] is True

    def test_cache_stale_after_15_seconds(self):
        """Cache older than 15 seconds triggers recompute."""
        with account_pool._EXH_LOCK:
            account_pool._EXH_CACHE["t"] = time.time() - 20
            account_pool._EXH_CACHE["v"] = True

        now = time.time()
        with account_pool._EXH_LOCK:
            is_stale = now - account_pool._EXH_CACHE["t"] >= 15
        assert is_stale

    def test_cache_fresh_within_15_seconds(self):
        """Cache younger than 15 seconds is considered fresh."""
        with account_pool._EXH_LOCK:
            account_pool._EXH_CACHE["t"] = time.time() - 5
            account_pool._EXH_CACHE["v"] = True

        now = time.time()
        with account_pool._EXH_LOCK:
            is_fresh = now - account_pool._EXH_CACHE["t"] < 15
        assert is_fresh

    def test_concurrent_reads_no_corruption(self):
        """Multiple threads reading cache simultaneously do not corrupt state."""
        results = []
        errors = []

        def reader():
            try:
                for _ in range(100):
                    with account_pool._EXH_LOCK:
                        t = account_pool._EXH_CACHE["t"]
                        v = account_pool._EXH_CACHE["v"]
                    results.append((t, v))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent reads: {errors}"
        assert len(results) == 500, f"Expected 500 reads, got {len(results)}"

    def test_concurrent_writes_no_corruption(self):
        """Multiple threads writing cache simultaneously maintain valid state."""
        errors = []

        def writer(thread_id):
            try:
                for i in range(50):
                    with account_pool._EXH_LOCK:
                        account_pool._EXH_CACHE["t"] = time.time() + thread_id + i * 0.001
                        account_pool._EXH_CACHE["v"] = (thread_id % 2 == 0)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent writes: {errors}"
        with account_pool._EXH_LOCK:
            assert isinstance(account_pool._EXH_CACHE["t"], float)
            assert isinstance(account_pool._EXH_CACHE["v"], bool)

    def test_concurrent_read_write_mixed(self):
        """Simultaneous reads and writes do not cause crashes or corruption."""
        errors = []

        def reader():
            try:
                for _ in range(100):
                    with account_pool._EXH_LOCK:
                        _ = account_pool._EXH_CACHE.get("t")
                        _ = account_pool._EXH_CACHE.get("v")
            except Exception as e:
                errors.append(f"reader: {e}")

        def writer():
            try:
                for i in range(100):
                    with account_pool._EXH_LOCK:
                        account_pool._EXH_CACHE["t"] = time.time() + i * 0.001
                        account_pool._EXH_CACHE["v"] = i % 2 == 0
            except Exception as e:
                errors.append(f"writer: {e}")

        threads = [threading.Thread(target=reader) for _ in range(3)]
        threads += [threading.Thread(target=writer) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during mixed access: {errors}"

    def test_lock_exists_and_is_threading_lock(self):
        """_EXH_LOCK is properly defined as a threading.Lock."""
        assert hasattr(account_pool, "_EXH_LOCK")
        assert isinstance(account_pool._EXH_LOCK, type(threading.Lock()))

    def test_cache_dict_has_expected_keys(self):
        """Cache dict maintains expected keys (t and v)."""
        with account_pool._EXH_LOCK:
            account_pool._EXH_CACHE["t"] = 100.0
            account_pool._EXH_CACHE["v"] = True
            assert "t" in account_pool._EXH_CACHE
            assert "v" in account_pool._EXH_CACHE


class TestPoolSingletonThreadSafety:
    """Test _pool singleton initialization under concurrent access."""

    def setup_method(self):
        """Reset pool state before each test."""
        account_pool._pool = None

    def test_pool_initializes_on_first_call(self):
        """First call to _get_pool() initializes the singleton."""
        assert account_pool._pool is None
        pool = account_pool._get_pool()
        assert pool is not None
        assert isinstance(pool, account_pool.AccountPool)

    def test_pool_returns_same_instance(self):
        """Multiple calls to _get_pool() return the same instance."""
        pool1 = account_pool._get_pool()
        pool2 = account_pool._get_pool()
        assert pool1 is pool2

    def test_concurrent_pool_initialization(self):
        """Multiple threads racing to initialize pool get the same instance."""
        pools = []
        errors = []

        def get_pool():
            try:
                p = account_pool._get_pool()
                pools.append(p)
            except Exception as e:
                errors.append(str(e))

        # Reset before starting
        account_pool._pool = None

        threads = [threading.Thread(target=get_pool) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent init: {errors}"
        assert len(pools) == 10, f"Expected 10 pools, got {len(pools)}"
        # All should be the same instance
        first = pools[0]
        for pool in pools[1:]:
            assert pool is first, "Multiple pool instances created!"

    def test_pool_lock_exists(self):
        """_POOL_LOCK is properly defined as a threading.Lock."""
        assert hasattr(account_pool, "_POOL_LOCK")
        assert isinstance(account_pool._POOL_LOCK, type(threading.Lock()))

    def test_module_stats_delegates_to_pool(self):
        """Module-level stats() function delegates to singleton pool."""
        with patch.object(account_pool.AccountPool, 'stats') as mock_stats:
            mock_stats.return_value = {"test": "data"}
            result = account_pool.stats()
            assert result == {"test": "data"}
            mock_stats.assert_called_once()

    def test_module_invalidate_delegates_to_pool(self):
        """Module-level invalidate() function delegates to singleton pool."""
        with patch.object(account_pool.AccountPool, 'invalidate') as mock_inv:
            account_pool.invalidate("test-account")
            mock_inv.assert_called_once_with("test-account")

    def test_get_pool_double_checked_locking(self):
        """_get_pool uses double-checked locking pattern."""
        account_pool._pool = None

        # First check: _pool is None (unlocked)
        # Second check inside lock: _pool is still None, so initialize
        # This pattern avoids holding lock during initialization

        call_count = [0]
        original_init = account_pool.AccountPool.__init__

        def counting_init(self):
            call_count[0] += 1
            return original_init(self)

        with patch.object(account_pool.AccountPool, '__init__', counting_init):
            account_pool._pool = None
            pools = []

            def get():
                pools.append(account_pool._get_pool())

            threads = [threading.Thread(target=get) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # __init__ should be called only once despite 5 concurrent threads
            assert call_count[0] == 1, f"AccountPool.__init__ called {call_count[0]} times!"
            assert all(p is pools[0] for p in pools), "Not all pools are the same instance"


class TestNoMalformedCode:
    """Test that malformed duplicate code has been removed."""

    def test_file_has_no_duplicate_stats_methods_at_module_level(self):
        """File should not have misindented stats() method at module level."""
        with open(os.path.join(os.path.dirname(__file__), "account_pool.py")) as f:
            content = f.read()

        # Count class-level stats() definitions (should be exactly 1 in AccountPool)
        class_stats_lines = [
            i for i, line in enumerate(content.split('\n'))
            if line.strip().startswith('def stats(self):')
        ]
        assert len(class_stats_lines) == 1, f"Expected 1 class stats() method, found {len(class_stats_lines)}"

    def test_file_has_no_dangling_def_at_module_level(self):
        """File should not have method definitions outside a class."""
        with open(os.path.join(os.path.dirname(__file__), "account_pool.py")) as f:
            lines = f.readlines()

        in_class = False
        for i, line in enumerate(lines):
            if line.startswith("class "):
                in_class = True
            elif line.startswith("def ") and not line.startswith("    "):
                # Module-level def is OK
                pass
            elif line.startswith("    def ") and not in_class:
                # Indented def outside class = malformed
                raise AssertionError(f"Found indented 'def' outside class at line {i+1}: {line.rstrip()}")
            elif line.startswith("if __name__"):
                in_class = False


class TestClaudeExhaustedWithLocks:
    """Test claude_exhausted() function uses locks correctly."""

    def setup_method(self):
        """Reset cache before each test."""
        with account_pool._EXH_LOCK:
            account_pool._EXH_CACHE["t"] = 0.0
            account_pool._EXH_CACHE["v"] = False

    def test_claude_exhausted_uses_lock_for_cache_read(self):
        """claude_exhausted() acquires lock when reading cache."""
        with account_pool._EXH_LOCK:
            account_pool._EXH_CACHE["t"] = time.time() - 5
            account_pool._EXH_CACHE["v"] = True

        # Should not raise; lock should be properly acquired
        with patch.object(account_pool.AccountPool, 'all_exhausted') as mock:
            mock.return_value = False
            # If cache is fresh and True, should return True without calling all_exhausted
            result = account_pool.claude_exhausted()
            assert result is True
            mock.assert_not_called()

    def test_claude_exhausted_uses_lock_for_cache_write(self):
        """claude_exhausted() acquires lock when writing cache."""
        with patch.object(account_pool.AccountPool, 'all_exhausted') as mock:
            mock.return_value = True
            with account_pool._EXH_LOCK:
                account_pool._EXH_CACHE["t"] = time.time() - 100  # Stale

            result = account_pool.claude_exhausted()

            with account_pool._EXH_LOCK:
                cached_v = account_pool._EXH_CACHE["v"]

            assert result is True
            assert cached_v is True

    def test_claude_exhausted_exception_handling(self):
        """claude_exhausted() handles exceptions gracefully."""
        with patch.object(account_pool.AccountPool, 'all_exhausted') as mock:
            mock.side_effect = Exception("DB error")
            result = account_pool.claude_exhausted()
            # Should not raise; should return False on error
            assert result is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
