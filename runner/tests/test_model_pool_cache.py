#!/usr/bin/env python3
"""Tests for model_pool_cache.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import model_pool_cache as mpc

def test_cache_prefix_basic():
    mpc.invalidate()
    key = mpc.cache_prefix("system prompt here", 42)
    assert key, "should return a key"
    info = mpc.get_prefix(key)
    assert info["tokens"] == 42

def test_cache_prefix_empty():
    assert mpc.cache_prefix("", 0) == ""
    assert mpc.cache_prefix(None, 0) == ""

def test_get_prefix_missing():
    assert mpc.get_prefix("nonexistent") == {}

def test_invalidate_one():
    mpc.invalidate()
    k1 = mpc.cache_prefix("a", 1)
    k2 = mpc.cache_prefix("b", 2)
    mpc.invalidate(k1)
    assert mpc.get_prefix(k1) == {}
    assert mpc.get_prefix(k2)["tokens"] == 2

def test_invalidate_all():
    mpc.cache_prefix("x", 10)
    mpc.invalidate()
    assert mpc.stats()["cached_prefixes"] == 0

def test_eviction():
    mpc.invalidate()
    old_max = mpc.PREFIX_CACHE_MAX
    mpc.PREFIX_CACHE_MAX = 3
    try:
        for i in range(5):
            mpc.cache_prefix(f"prefix-{i}", i)
        assert mpc.stats()["cached_prefixes"] <= 3
    finally:
        mpc.PREFIX_CACHE_MAX = old_max

def test_stats():
    mpc.invalidate()
    mpc.cache_prefix("test", 5)
    s = mpc.stats()
    assert "cached_prefixes" in s
    assert "warm_ok" in s
    assert s["cached_prefixes"] == 1

def test_warm_no_ollama():
    """Warm should fail-soft when Ollama isn't running."""
    old = mpc.OLLAMA_HOST
    mpc.OLLAMA_HOST = "http://localhost:99999"
    try:
        result = mpc.warm(force=True)
        assert result is False  # no crash
    finally:
        mpc.OLLAMA_HOST = old

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as e:
                print(f"  FAIL {name}: {e}")
    print("done")
