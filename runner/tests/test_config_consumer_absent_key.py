#!/usr/bin/env python3
"""A caller's default must never be cached as if a source had provided it.

THE DEFECT
----------
`load_config()` caches by key alone, and it cached the fully-resolved value — including
the case where no source had the key and the value WAS the caller's default. The next
caller, with a different default, got the first one's:

    load_config("MAX_RETRIES", "3")    -> "3"    (absent everywhere)
    load_config("MAX_RETRIES", "10")   -> "3"    <-- someone else's default

Reproduced live against origin/master@5c4eaf2f before the fix. Silent, order-dependent,
and effectively untraceable from the call site — the second module's default simply
stops having any effect, for as long as the first module happens to be imported first.

The fix keeps negative caching (an absent key still costs at most one DB read per TTL)
by recording an _ABSENT sentinel instead of the default, and applying each caller's own
default at return time.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_consumer as cc  # noqa: E402

ABSENT = "TEST_ABSENT_KEY_NOBODY_DEFINES"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    # No DB and no gateway: isolate the default/absent logic from the network.
    monkeypatch.setattr(cc, "fleet_control", None, raising=False)
    monkeypatch.delenv(f"ORCH_{ABSENT}", raising=False)
    cc.invalidate_cache()
    yield
    cc.invalidate_cache()


# ── the regression ──────────────────────────────────────────────────────────

def test_a_second_caller_gets_its_own_default():
    """The exact bug: B used to receive A's default."""
    assert cc.load_config(ABSENT, "3") == "3"
    assert cc.load_config(ABSENT, "10") == "10"


def test_a_caller_with_no_default_gets_empty_not_someone_elses_value():
    cc.load_config(ABSENT, "3")
    assert cc.load_config(ABSENT) == ""


def test_defaults_do_not_leak_in_either_order():
    assert cc.load_config(ABSENT, "10") == "10"
    assert cc.load_config(ABSENT, "3") == "3"
    assert cc.load_config(ABSENT, "10") == "10"


# ── negative caching is preserved ───────────────────────────────────────────

def test_an_absent_key_is_still_cached():
    """The point of the sentinel: keep saving the DB read."""
    cc.load_config(ABSENT, "x")
    assert ABSENT in cc._consumer._cache
    assert cc._consumer._cache[ABSENT][0] is cc._ABSENT


def test_the_absent_sentinel_is_falsey_and_not_a_string():
    assert not cc._ABSENT
    assert not isinstance(cc._ABSENT, str)


def test_an_absent_entry_expires_like_any_other(monkeypatch):
    cc.load_config(ABSENT, "x")
    cached_value, cached_time = cc._consumer._cache[ABSENT]
    cc._consumer._cache[ABSENT] = (cached_value, cached_time - 10_000)
    monkeypatch.setenv(f"ORCH_{ABSENT}", "now-it-exists")
    assert cc.load_config(ABSENT, "x") == "now-it-exists"


# ── real values are unaffected ──────────────────────────────────────────────

def test_a_real_env_value_beats_every_default(monkeypatch):
    monkeypatch.setenv("ORCH_TEST_REAL_KEY", "fromenv")
    cc.invalidate_cache()
    assert cc.load_config("TEST_REAL_KEY", "ignored") == "fromenv"
    assert cc.load_config("TEST_REAL_KEY", "also-ignored") == "fromenv"


def test_a_real_value_is_cached_as_itself(monkeypatch):
    monkeypatch.setenv("ORCH_TEST_REAL_KEY", "fromenv")
    cc.invalidate_cache()
    cc.load_config("TEST_REAL_KEY", "ignored")
    assert cc._consumer._cache["TEST_REAL_KEY"][0] == "fromenv"


def test_a_value_read_from_the_gateway_wins(monkeypatch):
    class Gateway:
        @staticmethod
        def get_fleet_config(key, default=""):
            return "fromfleet" if key == "TEST_REAL_KEY" else ""

    monkeypatch.setattr(cc, "fleet_control", Gateway, raising=False)
    cc.invalidate_cache()
    assert cc.load_config("TEST_REAL_KEY", "ignored") == "fromfleet"


# ── invalidation and fail-soft still hold ───────────────────────────────────

def test_invalidating_one_key_forces_a_re_read(monkeypatch):
    cc.load_config(ABSENT, "x")
    monkeypatch.setenv(f"ORCH_{ABSENT}", "appeared")
    cc.invalidate_cache(ABSENT)
    assert cc.load_config(ABSENT, "x") == "appeared"


def test_a_bad_key_returns_the_default_without_caching():
    for bad in (None, "", 42):
        assert cc.load_config(bad, "fallback") == "fallback"


def test_a_gateway_that_raises_does_not_propagate(monkeypatch):
    class Exploding:
        @staticmethod
        def get_fleet_config(key, default=""):
            raise RuntimeError("gateway down")

    monkeypatch.setattr(cc, "fleet_control", Exploding, raising=False)
    cc.invalidate_cache()
    assert cc.load_config(ABSENT, "fallback") == "fallback"


def test_eviction_still_bounds_the_cache(monkeypatch):
    monkeypatch.setenv("ORCH_CONFIG_CACHE_MAX_ENTRIES", "5")
    cc.invalidate_cache()
    for i in range(20):
        cc.load_config(f"{ABSENT}_{i}", "x")
        time.sleep(0.001)
    assert len(cc._consumer._cache) <= 5
