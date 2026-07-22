#!/usr/bin/env python3
"""Tests for auto_error_categorizer.py - automated error classification."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
import auto_error_categorizer as aec


# --- Fingerprinting tests ---

def test_fingerprint_stable():
    fp1, _ = aec.fingerprint("connection reset at 1721000000")
    fp2, _ = aec.fingerprint("connection reset at 1721999999")
    assert fp1 == fp2, "timestamps should be normalized"


def test_fingerprint_strips_hex_ids():
    fp1, _ = aec.fingerprint("task abcdef12 failed")
    fp2, _ = aec.fingerprint("task 99887766 failed")
    assert fp1 == fp2


def test_fingerprint_strips_ips():
    fp1, _ = aec.fingerprint("cannot reach 10.0.0.1")
    fp2, _ = aec.fingerprint("cannot reach 192.168.1.1")
    assert fp1 == fp2


def test_fingerprint_empty():
    fp, norm = aec.fingerprint("")
    assert isinstance(fp, str)
    assert len(fp) == 12


def test_fingerprint_none():
    fp, norm = aec.fingerprint(None)
    assert isinstance(fp, str)


# --- Categorization tests ---

def test_categorize_transient_timeout():
    r = aec.categorize("connection timed out after 30s")
    assert r["category"] == "transient"
    assert r["retryable"] is True
    assert r["confidence"] > 0.5


def test_categorize_transient_rate_limit():
    r = aec.categorize("429 Too Many Requests - rate limit exceeded")
    assert r["category"] == "transient"
    assert r["retryable"] is True


def test_categorize_transient_503():
    r = aec.categorize("HTTP 503 Service Unavailable")
    assert r["category"] == "transient"


def test_categorize_permanent_syntax():
    r = aec.categorize("SyntaxError: unexpected token at line 42")
    assert r["category"] == "permanent"
    assert r["retryable"] is False


def test_categorize_permanent_import():
    r = aec.categorize("ModuleNotFoundError: No module named 'missing_pkg'")
    assert r["category"] == "permanent"
    assert r["retryable"] is False


def test_categorize_permanent_permission():
    r = aec.categorize("PermissionError: permission denied: /etc/shadow")
    assert r["category"] == "permanent"


def test_categorize_ambiguous():
    r = aec.categorize("something completely unknown happened xyz123")
    assert r["category"] == "ambiguous"
    assert r["confidence"] < 0.5


def test_categorize_empty():
    r = aec.categorize("")
    assert r["category"] == "ambiguous"


def test_categorize_none():
    r = aec.categorize(None)
    assert "category" in r


def test_categorize_has_fingerprint():
    r = aec.categorize("timeout error")
    assert "fingerprint" in r
    assert len(r["fingerprint"]) == 12


def test_categorize_has_recommendation():
    r = aec.categorize("connection reset by peer")
    assert "recommendation" in r
    assert len(r["recommendation"]) > 0


# --- Batch categorization ---

def test_categorize_batch():
    errors = ["timeout", "SyntaxError: bad", "unknown thing"]
    results = aec.categorize_batch(errors)
    assert len(results) == 3
    assert results[0]["category"] == "transient"
    assert results[1]["category"] == "permanent"


def test_categorize_batch_empty():
    assert aec.categorize_batch([]) == []
    assert aec.categorize_batch(None) == []


# --- Feedback learning ---

def test_feedback_improves_classification():
    aec.clear()
    error = "weird flaky error abc123"
    # Initially ambiguous
    r1 = aec.categorize(error)
    assert r1["category"] == "ambiguous"

    # Record successful retries
    for _ in range(5):
        aec.record_feedback(error, retry_succeeded=True)

    # Now should be classified as transient from history
    r2 = aec.categorize(error)
    assert r2["category"] == "transient"
    assert r2["retryable"] is True


def test_feedback_marks_permanent():
    aec.clear()
    error = "strange failure qrs789"
    # Record failed retries
    for _ in range(5):
        aec.record_feedback(error, retry_succeeded=False)

    r = aec.categorize(error)
    assert r["category"] == "permanent"
    assert r["retryable"] is False


def test_feedback_insufficient_data():
    aec.clear()
    error = "one-off glitch"
    aec.record_feedback(error, retry_succeeded=True)
    # Only 1 data point — not enough to override
    r = aec.categorize(error)
    # Should fall through to pattern matching, not learned
    assert r["normalized"] != "(learned)"


# --- Stats ---

def test_stats():
    aec.clear()
    aec.categorize("timeout")
    aec.categorize("SyntaxError")
    s = aec.stats()
    assert s["total_classified"] >= 2
    assert "by_category" in s


def test_clear():
    aec.clear()
    s = aec.stats()
    assert s["total_classified"] == 0
    assert s["feedback_entries"] == 0


# --- Disabled mode ---

def test_disabled_returns_default():
    aec.ENABLED = False
    r = aec.categorize("timeout")
    assert r["confidence"] == 0.0
    aec.ENABLED = True


if __name__ == "__main__":
    test_fingerprint_stable()
    test_fingerprint_strips_hex_ids()
    test_fingerprint_strips_ips()
    test_fingerprint_empty()
    test_fingerprint_none()
    test_categorize_transient_timeout()
    test_categorize_transient_rate_limit()
    test_categorize_transient_503()
    test_categorize_permanent_syntax()
    test_categorize_permanent_import()
    test_categorize_permanent_permission()
    test_categorize_ambiguous()
    test_categorize_empty()
    test_categorize_none()
    test_categorize_has_fingerprint()
    test_categorize_has_recommendation()
    test_categorize_batch()
    test_categorize_batch_empty()
    test_feedback_improves_classification()
    test_feedback_marks_permanent()
    test_feedback_insufficient_data()
    test_stats()
    test_clear()
    test_disabled_returns_default()
    print("All auto_error_categorizer tests passed")
