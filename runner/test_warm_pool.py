#!/usr/bin/env python3
"""Tests for warm_pool.py — context-prefix pool and subprocess pool."""
import os, sys, time, tempfile, threading
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import warm_pool
from warm_pool import WarmPool, SubprocessWarmPool, get_or_create_pool, shutdown_all_pools, POOL_REGISTRY


# ── 1. WarmPool instantiates without error ────────────────────────────────────

def test_warmpool_instantiates():
    pool = WarmPool(pool_size=2)
    assert pool is not None
    assert pool._size == 2
    assert pool._enabled is True


# ── 2. start() + stop() on SubprocessWarmPool ────────────────────────────────

def test_subprocess_pool_start_stop():
    with tempfile.TemporaryDirectory() as td:
        sp = SubprocessWarmPool(td, max_size=1)
        sp.start()
        assert sp._started is True
        sp.stop()
        assert sp._started is False
        assert len(sp._procs) == 0


# ── 3. acquire() returns empty string when pool empty / never started ────────

def test_acquire_returns_empty_on_miss():
    pool = WarmPool(pool_size=2)
    # Non-existent path → returns ""
    result = pool.acquire("/nonexistent/path/that/does/not/exist")
    assert result == ""


def test_acquire_returns_empty_on_none():
    pool = WarmPool()
    assert pool.acquire(None) == ""
    assert pool.acquire("") == ""


# ── 4. release() of a dead process does not add it back ──────────────────────

def test_release_dead_process():
    with tempfile.TemporaryDirectory() as td:
        sp = SubprocessWarmPool(td, max_size=2)
        # Create a mock dead process
        dead = MagicMock()
        dead.poll.return_value = 1  # already exited
        sp.release(dead)
        assert len(sp._procs) == 0


def test_release_none():
    with tempfile.TemporaryDirectory() as td:
        sp = SubprocessWarmPool(td, max_size=2)
        sp.release(None)  # should not raise
        assert len(sp._procs) == 0


# ── 5. get_or_create_pool returns same instance for same repo ────────────────

def test_get_or_create_pool_same_instance():
    POOL_REGISTRY.clear()
    with tempfile.TemporaryDirectory() as td:
        p1 = get_or_create_pool(td)
        p2 = get_or_create_pool(td)
        assert p1 is p2
    POOL_REGISTRY.clear()


# ── 6. shutdown_all_pools clears POOL_REGISTRY ───────────────────────────────

def test_shutdown_all_pools_clears_registry():
    POOL_REGISTRY.clear()
    with tempfile.TemporaryDirectory() as td:
        get_or_create_pool(td)
        assert len(POOL_REGISTRY) == 1
        shutdown_all_pools()
        assert len(POOL_REGISTRY) == 0


# ── 7. Resource governor: low memory → effective_max_size <= 1 ───────────────

def test_resource_governor_constrains_pool_size():
    mock_gov = MagicMock()
    mock_gov.can_claim.return_value = (False, "low RAM")
    pool = WarmPool(pool_size=5, resource_governor=mock_gov)
    assert pool.effective_max_size <= 1


def test_resource_governor_normal_returns_full_size():
    mock_gov = MagicMock()
    mock_gov.can_claim.return_value = (True, "ok")
    pool = WarmPool(pool_size=5, resource_governor=mock_gov)
    assert pool.effective_max_size == 5


def test_no_governor_returns_full_size():
    pool = WarmPool(pool_size=4)
    assert pool.effective_max_size == 4


# ── 8. acquire() with a real CLAUDE.md returns content ───────────────────────

def test_acquire_with_claude_md():
    with tempfile.TemporaryDirectory() as td:
        md_path = os.path.join(td, "CLAUDE.md")
        with open(md_path, "w") as f:
            f.write("# Test Project\nSome instructions here.")
        pool = WarmPool(pool_size=3)
        ctx = pool.acquire(td)
        assert "Test Project" in ctx
        assert "Some instructions here" in ctx
        # Second acquire should be a cache hit
        ctx2 = pool.acquire(td)
        assert ctx2 == ctx


# ── 9. invalidate drops the slot ─────────────────────────────────────────────

def test_invalidate():
    with tempfile.TemporaryDirectory() as td:
        md_path = os.path.join(td, "CLAUDE.md")
        with open(md_path, "w") as f:
            f.write("original content")
        pool = WarmPool(pool_size=3)
        pool.acquire(td)
        assert td in pool._slots
        pool.invalidate(td)
        assert td not in pool._slots


# ── 10. stats() returns expected shape ───────────────────────────────────────

def test_stats():
    pool = WarmPool(pool_size=2)
    s = pool.stats()
    assert "pool_size" in s
    assert "loaded" in s
    assert "enabled" in s
    assert "repos" in s
    assert s["pool_size"] == 2
    assert s["loaded"] == 0


# ── 11. set_enabled(False) clears slots ──────────────────────────────────────

def test_set_enabled_false_clears():
    with tempfile.TemporaryDirectory() as td:
        md_path = os.path.join(td, "CLAUDE.md")
        with open(md_path, "w") as f:
            f.write("content")
        pool = WarmPool(pool_size=3)
        pool.acquire(td)
        assert len(pool._slots) == 1
        pool.set_enabled(False)
        assert len(pool._slots) == 0
        assert pool.acquire(td) == ""
