#!/usr/bin/env python3
"""Tests for error_handling_utils.py - structured error wrapper and retry helper."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
import error_handling_utils as ehu


# --- StructuredError tests ---

def test_structured_error_basic():
    se = ehu.StructuredError(ValueError("bad"), category="logic", severity="error")
    assert se.category == "logic"
    assert se.severity == "error"
    assert se.retryable is False
    assert "bad" in str(se.original)


def test_structured_error_to_dict():
    se = ehu.StructuredError(RuntimeError("boom"), category="transient",
                              severity="warning", retryable=True, context="test_ctx")
    d = se.to_dict()
    assert d["category"] == "transient"
    assert d["retryable"] is True
    assert d["context"] == "test_ctx"
    assert d["type"] == "RuntimeError"
    assert isinstance(d["timestamp"], float)


def test_structured_error_str():
    se = ehu.StructuredError(ValueError("x"), category="logic", severity="error")
    s = str(se)
    assert "logic" in s
    assert "error" in s


# --- wrap_error tests ---

def test_wrap_error_auto_classifies_transient():
    exc = ConnectionError("connection reset")
    se = ehu.wrap_error(exc)
    assert se.category == "transient"
    assert se.retryable is True
    assert se.severity == "warning"


def test_wrap_error_auto_classifies_logic():
    exc = ValueError("bad argument")
    se = ehu.wrap_error(exc)
    assert se.category == "logic"
    assert se.retryable is False


def test_wrap_error_auto_classifies_permission():
    exc = PermissionError("denied")
    se = ehu.wrap_error(exc)
    assert se.category == "permission"
    assert se.retryable is False
    assert se.severity == "fatal"


def test_wrap_error_auto_classifies_resource():
    exc = MemoryError("OOM")
    se = ehu.wrap_error(exc)
    assert se.category == "resource"
    assert se.retryable is True


def test_wrap_error_message_heuristics():
    exc = RuntimeError("rate limit exceeded 429")
    se = ehu.wrap_error(exc)
    assert se.category == "transient"


def test_wrap_error_overrides():
    exc = ValueError("whatever")
    se = ehu.wrap_error(exc, category="toolchain", severity="fatal", retryable=False)
    assert se.category == "toolchain"
    assert se.severity == "fatal"
    assert se.retryable is False


def test_wrap_error_context():
    se = ehu.wrap_error(RuntimeError("x"), context="during merge")
    assert se.context == "during merge"


def test_wrap_error_unknown():
    # An exception type that doesn't match any heuristic
    se = ehu.wrap_error(Exception("something weird"))
    assert se.category == "unknown"


# --- retry_with_backoff tests ---

def test_retry_succeeds_first_try():
    ehu.clear_stats()
    call_count = {"n": 0}

    @ehu.retry_with_backoff(max_attempts=3, base_delay=0.01)
    def ok():
        call_count["n"] += 1
        return 42

    assert ok() == 42
    assert call_count["n"] == 1
    s = ehu.retry_stats()
    assert s["successes"] >= 1


def test_retry_recovers_transient():
    ehu.clear_stats()
    call_count = {"n": 0}

    @ehu.retry_with_backoff(max_attempts=3, base_delay=0.01)
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise ConnectionError("reset")
        return "ok"

    assert flaky() == "ok"
    assert call_count["n"] == 3


def test_retry_gives_up_after_max():
    ehu.clear_stats()
    call_count = {"n": 0}

    @ehu.retry_with_backoff(max_attempts=2, base_delay=0.01)
    def always_fails():
        call_count["n"] += 1
        raise TimeoutError("always")

    try:
        always_fails()
        assert False, "should have raised"
    except TimeoutError:
        pass
    assert call_count["n"] == 2
    s = ehu.retry_stats()
    assert s["exhausted"] >= 1


def test_retry_skips_permanent_errors():
    call_count = {"n": 0}

    @ehu.retry_with_backoff(max_attempts=5, base_delay=0.01, on_transient_only=True)
    def permanent():
        call_count["n"] += 1
        raise ValueError("logic bug")

    try:
        permanent()
        assert False, "should have raised"
    except ValueError:
        pass
    # Should NOT retry a permanent/logic error
    assert call_count["n"] == 1


def test_retry_all_errors_when_flag_off():
    call_count = {"n": 0}

    @ehu.retry_with_backoff(max_attempts=3, base_delay=0.01, on_transient_only=False)
    def always():
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise ValueError("retryable when flag off")
        return "done"

    assert always() == "done"
    assert call_count["n"] == 3


def test_retry_as_direct_call():
    ehu.clear_stats()
    call_count = {"n": 0}

    def fragile():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise ConnectionError("transient")
        return "recovered"

    wrapped = ehu.retry_with_backoff(fragile, max_attempts=3, base_delay=0.01)
    assert wrapped() == "recovered"


def test_clear_stats():
    ehu.clear_stats()
    s = ehu.retry_stats()
    assert s["attempts"] == 0
    assert s["successes"] == 0
    assert s["exhausted"] == 0


if __name__ == "__main__":
    test_structured_error_basic()
    test_structured_error_to_dict()
    test_structured_error_str()
    test_wrap_error_auto_classifies_transient()
    test_wrap_error_auto_classifies_logic()
    test_wrap_error_auto_classifies_permission()
    test_wrap_error_auto_classifies_resource()
    test_wrap_error_message_heuristics()
    test_wrap_error_overrides()
    test_wrap_error_context()
    test_wrap_error_unknown()
    test_retry_succeeds_first_try()
    test_retry_recovers_transient()
    test_retry_gives_up_after_max()
    test_retry_skips_permanent_errors()
    test_retry_all_errors_when_flag_off()
    test_retry_as_direct_call()
    test_clear_stats()
    print("All error_handling_utils tests passed")
