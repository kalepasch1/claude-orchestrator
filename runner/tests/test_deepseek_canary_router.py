"""Tests for the DeepSeek canary traffic router.

Validates enable/disable gating, percent clamping, deterministic hash-based
bucketing, override handling, monotonic rollout widening, and fail-soft
behavior on bad input.

Task: canary-deepseek-70-slice-4
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deepseek_canary_router as router


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ORCH_DEEPSEEK_CANARY_ENABLED", raising=False)
    monkeypatch.delenv("ORCH_DEEPSEEK_CANARY_PERCENT", raising=False)


def _enable(monkeypatch, percent=None):
    monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_ENABLED", "true")
    if percent is not None:
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_PERCENT", str(percent))


class TestGating:
    def test_disabled_by_default(self):
        assert router.route_deepseek_request("req-1") == router.CONTROL

    def test_disabled_even_with_full_percent(self, monkeypatch):
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_PERCENT", "100")
        assert router.route_deepseek_request("req-1") == router.CONTROL

    def test_disabled_ignores_override(self, monkeypatch):
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_ENABLED", "false")
        assert router.route_deepseek_request("req-1", override_percent=100) == router.CONTROL

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", " true "])
    def test_enabled_truthy_variants(self, monkeypatch, raw):
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_ENABLED", raw)
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_PERCENT", "100")
        assert router.route_deepseek_request("req-1") == router.CANARY

    @pytest.mark.parametrize("raw", ["0", "false", "off", "no", "", "garbage"])
    def test_disabled_falsy_variants(self, monkeypatch, raw):
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_ENABLED", raw)
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_PERCENT", "100")
        assert router.route_deepseek_request("req-1") == router.CONTROL


class TestBoundaries:
    def test_zero_percent_is_control(self, monkeypatch):
        _enable(monkeypatch, 0)
        assert all(router.route_deepseek_request(f"r{i}") == router.CONTROL for i in range(50))

    def test_hundred_percent_is_canary(self, monkeypatch):
        _enable(monkeypatch, 100)
        assert all(router.route_deepseek_request(f"r{i}") == router.CANARY for i in range(50))

    def test_negative_percent_clamped_to_control(self, monkeypatch):
        _enable(monkeypatch, -25)
        assert router.route_deepseek_request("req-1") == router.CONTROL

    def test_over_hundred_percent_clamped_to_canary(self, monkeypatch):
        _enable(monkeypatch, 250)
        assert router.route_deepseek_request("req-1") == router.CANARY


class TestDeterminism:
    def test_same_id_same_arm(self, monkeypatch):
        _enable(monkeypatch, 50)
        first = router.route_deepseek_request("stable-id")
        assert all(router.route_deepseek_request("stable-id") == first for _ in range(20))

    def test_split_roughly_matches_percent(self, monkeypatch):
        _enable(monkeypatch, 30)
        n = 2000
        hits = sum(router.route_deepseek_request(f"req-{i}") == router.CANARY for i in range(n))
        assert 0.2 < hits / n < 0.4

    def test_rollout_widening_is_monotonic(self, monkeypatch):
        # An id in the canary arm at pct must stay there at any higher pct.
        _enable(monkeypatch)
        ids = [f"req-{i}" for i in range(200)]
        in_at_10 = {i for i in ids if router.route_deepseek_request(i, override_percent=10) == router.CANARY}
        in_at_60 = {i for i in ids if router.route_deepseek_request(i, override_percent=60) == router.CANARY}
        assert in_at_10 <= in_at_60

    def test_bucket_stable_across_calls(self):
        assert router._bucket("abc") == router._bucket("abc")
        assert 0 <= router._bucket("abc") < router._BUCKETS


class TestOverride:
    def test_override_takes_precedence(self, monkeypatch):
        _enable(monkeypatch, 0)
        assert router.route_deepseek_request("req-1", override_percent=100) == router.CANARY

    def test_override_zero_forces_control(self, monkeypatch):
        _enable(monkeypatch, 100)
        assert router.route_deepseek_request("req-1", override_percent=0) == router.CONTROL

    def test_override_clamped(self, monkeypatch):
        _enable(monkeypatch, 0)
        assert router.route_deepseek_request("req-1", override_percent=999) == router.CANARY
        assert router.route_deepseek_request("req-1", override_percent=-5) == router.CONTROL

    def test_bad_override_falls_back_to_env(self, monkeypatch):
        _enable(monkeypatch, 100)
        assert router.route_deepseek_request("req-1", override_percent="not-a-number") == router.CANARY


class TestFailSoft:
    def test_none_request_id_does_not_raise(self, monkeypatch):
        _enable(monkeypatch, 50)
        assert router.route_deepseek_request(None) in (router.CANARY, router.CONTROL)

    def test_non_string_request_id(self, monkeypatch):
        _enable(monkeypatch, 100)
        assert router.route_deepseek_request(12345) == router.CANARY

    def test_bad_percent_env_defaults_to_control(self, monkeypatch):
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_ENABLED", "true")
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_PERCENT", "garbage")
        assert router.route_deepseek_request("req-1") == router.CONTROL

    def test_empty_percent_env_defaults_to_control(self, monkeypatch):
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_ENABLED", "true")
        monkeypatch.setenv("ORCH_DEEPSEEK_CANARY_PERCENT", "")
        assert router.route_deepseek_request("req-1") == router.CONTROL


class TestStats:
    def test_stats_default(self):
        assert router.get_canary_stats() == {"coder": "deepseek", "enabled": False, "percent": 0.0}

    def test_stats_reflect_env(self, monkeypatch):
        _enable(monkeypatch, 37.5)
        stats = router.get_canary_stats()
        assert stats["enabled"] is True
        assert stats["percent"] == 37.5

    def test_stats_clamp_percent(self, monkeypatch):
        _enable(monkeypatch, 400)
        assert router.get_canary_stats()["percent"] == 100.0
