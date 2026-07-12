#!/usr/bin/env python3
"""Tests for failsoft.py - fail-soft error handling."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
import failsoft


def test_decorator_catches_exception():
    @failsoft.failsoft(default="safe")
    def boom():
        raise ValueError("kaboom")
    assert boom() == "safe"


def test_decorator_passes_through():
    @failsoft.failsoft(default=None)
    def ok():
        return 42
    assert ok() == 42


def test_callable_default():
    @failsoft.failsoft(default=list)
    def boom():
        raise RuntimeError("err")
    assert boom() == []


def test_context_manager_suppresses():
    with failsoft.failsoft_ctx("test") as ctx:
        raise RuntimeError("ctx error")
    assert ctx.error is not None


def test_failsoft_call():
    def boom():
        raise TypeError("bad")
    result = failsoft.failsoft_call(boom, default="fallback", source="test")
    assert result == "fallback"


def test_stats_tracking():
    failsoft.clear()
    @failsoft.failsoft(default=None, source="test_stats")
    def err():
        raise ValueError("tracked")
    err()
    err()
    s = failsoft.stats()
    assert s["total_caught"] >= 2
    assert "test_stats" in s["by_source"]


def test_recent_errors():
    failsoft.clear()
    @failsoft.failsoft(default=None, source="recent_test")
    def err():
        raise ValueError("recent")
    err()
    errs = failsoft.recent_errors()
    assert len(errs) >= 1
    assert errs[-1]["source"] == "recent_test"


def test_disabled():
    os.environ["ORCH_FAILSOFT_ENABLED"] = "false"
    # Re-import to pick up change - but module already loaded, so test directly
    failsoft._ENABLED = False
    @failsoft.failsoft(default="safe")
    def boom():
        raise ValueError("should raise")
    try:
        boom()
        assert False, "should have raised"
    except ValueError:
        pass
    failsoft._ENABLED = True
    os.environ["ORCH_FAILSOFT_ENABLED"] = "true"


if __name__ == "__main__":
    test_decorator_catches_exception()
    test_decorator_passes_through()
    test_callable_default()
    test_context_manager_suppresses()
    test_failsoft_call()
    test_stats_tracking()
    test_recent_errors()
    test_disabled()
    print("All failsoft tests passed!")
