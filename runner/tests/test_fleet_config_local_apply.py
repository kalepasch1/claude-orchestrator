#!/usr/bin/env python3
"""A fleet_config push must be visible in the process that made it.

THE DEFECT
----------
`update_fleet_config()` wrote the row and published a WebSocket event, but did nothing
locally. The pushing process kept reading the OLD value until the next periodic
`load_config()`, and `config_consumer.load_config()` kept serving its cached value for
up to `ORCH_CONFIG_CACHE_TTL_SEC` on top of that.

So the change was durable and broadcast to everyone else, and invisible to the one
process that should have seen it instantly. `config_consumer.invalidate_cache()` had
existed for exactly this purpose and nothing called it.

The local apply reuses `_classify_key`, so it refuses precisely what `load_config()`
refuses. That matters most for pinned keys: a write path that applied them would
silently override the local .env value the pin exists to protect.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_control as fc  # noqa: E402

KEY = "ORCH_TEST_RT_CONFIG_VALUE"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """No DB, no websocket, no approval lookups."""
    monkeypatch.setattr(fc.db, "insert", lambda *a, **k: None)
    monkeypatch.setattr(fc.db, "select", lambda *a, **k: [])
    monkeypatch.setattr(fc, "_ws_server", None, raising=False)
    monkeypatch.setattr(fc.config_approval, "blocked_keys", lambda: set())
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.delenv("ORCH_CONFIG_ENV_PINS", raising=False)
    fc._applied_config.pop(KEY, None)
    yield
    fc._applied_config.pop(KEY, None)


# ── the regression ──────────────────────────────────────────────────────────

def test_a_push_is_visible_in_this_process_immediately():
    fc.update_fleet_config(KEY, "newvalue")
    assert os.environ.get(KEY) == "newvalue"


def test_the_gateway_reads_back_the_value_just_written():
    fc.update_fleet_config(KEY, "newvalue")
    assert fc.get_fleet_config("TEST_RT_CONFIG_VALUE") == "newvalue"


def test_the_consumer_cache_is_dropped_so_a_stale_read_cannot_survive():
    import config_consumer

    os.environ[KEY] = "old"
    config_consumer.invalidate_cache()
    assert config_consumer.load_config("TEST_RT_CONFIG_VALUE", "") == "old"  # now cached

    fc.update_fleet_config(KEY, "new")
    assert config_consumer.load_config("TEST_RT_CONFIG_VALUE", "") == "new"


def test_the_applied_config_ledger_records_the_write():
    fc.update_fleet_config(KEY, "newvalue")
    assert fc._applied_config.get(KEY) == "newvalue"


def test_a_value_is_stringified_like_the_stored_row():
    fc.update_fleet_config(KEY, 42)
    assert os.environ.get(KEY) == "42"


# ── the gates are honoured, not re-derived ──────────────────────────────────

def test_a_pinned_key_is_not_applied_locally(monkeypatch):
    """The important one: a pin protects the LOCAL value from fleet_config."""
    monkeypatch.setenv("ORCH_CONFIG_ENV_PINS", KEY)
    monkeypatch.setenv(KEY, "local-wins")
    fc.update_fleet_config(KEY, "fleet-value")
    assert os.environ[KEY] == "local-wins"


def test_a_blocked_key_is_not_applied_locally(monkeypatch):
    monkeypatch.setattr(fc.config_approval, "blocked_keys", lambda: {KEY})
    fc.update_fleet_config(KEY, "newvalue")
    assert KEY not in os.environ


def test_apply_locally_reports_why_it_declined(monkeypatch):
    monkeypatch.setattr(fc.config_approval, "blocked_keys", lambda: {KEY})
    assert fc._apply_locally(KEY, "v") is not None


def test_apply_locally_returns_none_when_it_applied():
    assert fc._apply_locally(KEY, "v") is None


def test_a_credential_shaped_key_is_refused_by_the_write_itself():
    """_safe_key still rejects it before anything is written or applied."""
    with pytest.raises(ValueError):
        fc.update_fleet_config("ORCH_SOME_TOKEN", "secret")


# ── fail-soft ───────────────────────────────────────────────────────────────

def test_a_classify_failure_does_not_break_the_write(monkeypatch):
    def boom():
        raise RuntimeError("approval lookup down")

    monkeypatch.setattr(fc.config_approval, "blocked_keys", boom)
    row = fc.update_fleet_config(KEY, "newvalue")
    assert row["key"] == KEY and row["value"] == "newvalue"


def test_a_missing_config_consumer_does_not_break_the_write(monkeypatch):
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "config_consumer":
            raise ImportError("gone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    row = fc.update_fleet_config(KEY, "newvalue")
    assert row["value"] == "newvalue"
    assert os.environ.get(KEY) == "newvalue"


def test_invalidate_helper_reports_failure_rather_than_raising(monkeypatch):
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "config_consumer":
            raise ImportError("gone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert fc._invalidate_consumer_cache(KEY) is False


# ── the write path is otherwise unchanged ───────────────────────────────────

def test_the_row_shape_is_preserved():
    row = fc.update_fleet_config(KEY, "newvalue")
    assert set(row) == {"key", "value", "updated_by", "updated_at"}


def test_the_websocket_event_still_fires(monkeypatch):
    published = []

    class WS:
        @staticmethod
        def publish_event(topic, payload):
            published.append((topic, payload))

    monkeypatch.setattr(fc, "_ws_server", WS, raising=False)
    fc.update_fleet_config(KEY, "newvalue")
    assert published and published[0][0] == "config/*"
    assert published[0][1]["new_value"] == "newvalue"
