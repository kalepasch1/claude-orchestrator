"""Tests for provider_rate_tracker — rate-aware parallel routing."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import provider_rate_tracker as prt


def setup_function():
    prt.clear()


def test_not_throttled_initially():
    assert not prt.is_throttled("openai")
    assert not prt.is_throttled("deepseek")


def test_record_marks_throttled():
    prt.record_rate_limit("openai", cooldown_s=10)
    assert prt.is_throttled("openai")
    assert not prt.is_throttled("deepseek")


def test_preferred_order_unthrottled_first():
    prt.record_rate_limit("deepseek", cooldown_s=30)
    ordered = prt.preferred_order(["deepseek", "claude", "openai"])
    assert ordered.index("deepseek") > ordered.index("claude")
    assert ordered.index("deepseek") > ordered.index("openai")


def test_preferred_order_all_free_preserves_original():
    ordered = prt.preferred_order(["claude", "openai", "deepseek"])
    assert ordered == ["claude", "openai", "deepseek"]


def test_clear_removes_throttle():
    prt.record_rate_limit("openai", cooldown_s=60)
    prt.clear("openai")
    assert not prt.is_throttled("openai")


def test_clear_all():
    prt.record_rate_limit("openai", cooldown_s=60)
    prt.record_rate_limit("deepseek", cooldown_s=60)
    prt.clear()
    assert not prt.is_throttled("openai")
    assert not prt.is_throttled("deepseek")


def test_repeated_hits_extend_cooldown():
    prt.record_rate_limit("openai", cooldown_s=5)
    s1 = prt.status()["openai"]
    prt.record_rate_limit("openai", cooldown_s=5)
    s2 = prt.status()["openai"]
    assert s2 > s1  # second hit extends the window


def test_status_returns_remaining_seconds():
    prt.record_rate_limit("deepseek", cooldown_s=60)
    s = prt.status()
    assert "deepseek" in s
    assert 50 < s["deepseek"] <= 60


def test_empty_provider_ignored():
    prt.record_rate_limit("", cooldown_s=60)
    assert not prt.is_throttled("")


def test_preferred_order_multiple_throttled():
    prt.record_rate_limit("openai", cooldown_s=30)
    prt.record_rate_limit("google", cooldown_s=30)
    ordered = prt.preferred_order(["openai", "claude", "google", "deepseek"])
    free = [p for p in ordered if not prt.is_throttled(p)]
    busy = [p for p in ordered if prt.is_throttled(p)]
    assert ordered == free + busy
