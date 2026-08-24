"""Withdrawing a fleet_config key must actually withdraw it, live.

`load_config` only ever WROTE into os.environ. Deleting a row therefore changed nothing
in any already-running process — the withdrawn value stayed in effect until restart, so
"revert that config fleet-wide" silently did nothing. These tests pin the round trip:
apply, withdraw, restored; and pin the failure mode that matters more — a DB read error
must never be mistaken for "every key was withdrawn".
"""
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import fleet_control as fc  # noqa: E402

KEY = "ORCH_TEST_REVERT_KNOB"
OTHER = "ORCH_TEST_OTHER_KNOB"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    fc._applied_config.clear()
    fc._env_baseline.clear()
    fc._reported_ignored.clear()
    for key in (KEY, OTHER):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(fc.config_approval, "blocked_keys", lambda: set())
    monkeypatch.delenv("ORCH_CONFIG_ENV_PINS", raising=False)
    yield
    fc._applied_config.clear()
    fc._env_baseline.clear()


def _rows(monkeypatch, rows):
    monkeypatch.setattr(fc.db, "select", lambda table, params=None: list(rows))


def test_apply_then_withdraw_unsets_a_key_that_had_no_local_value(monkeypatch):
    _rows(monkeypatch, [{"key": KEY, "value": "24"}])
    fc.load_config()
    assert os.environ[KEY] == "24"

    _rows(monkeypatch, [])
    fc.load_config()
    assert KEY not in os.environ, "a withdrawn key must not linger in the environment"
    assert fc.config_consumption()["reverted"] == [KEY]


def test_withdraw_restores_the_local_env_value_it_overrode(monkeypatch):
    monkeypatch.setenv(KEY, "local-6")
    _rows(monkeypatch, [{"key": KEY, "value": "fleet-24"}])
    fc.load_config()
    assert os.environ[KEY] == "fleet-24"

    _rows(monkeypatch, [])
    fc.load_config()
    assert os.environ[KEY] == "local-6", "the machine-local value must come back"


def test_empty_string_baseline_is_restored_not_deleted(monkeypatch):
    monkeypatch.setenv(KEY, "")
    _rows(monkeypatch, [{"key": KEY, "value": "on"}])
    fc.load_config()
    _rows(monkeypatch, [])
    fc.load_config()
    assert KEY in os.environ and os.environ[KEY] == ""


def test_other_keys_are_untouched_by_a_withdrawal(monkeypatch):
    _rows(monkeypatch, [{"key": KEY, "value": "1"}, {"key": OTHER, "value": "2"}])
    fc.load_config()
    _rows(monkeypatch, [{"key": OTHER, "value": "2"}])
    fc.load_config()
    assert KEY not in os.environ
    assert os.environ[OTHER] == "2"


def test_failed_read_never_reverts_the_fleet(monkeypatch):
    """The dangerous case: a transient DB error must not look like a mass withdrawal."""
    _rows(monkeypatch, [{"key": KEY, "value": "24"}])
    fc.load_config()

    def boom(*a, **k):
        raise RuntimeError("db unreachable")
    monkeypatch.setattr(fc.db, "select", boom)
    fc.load_config()

    assert os.environ[KEY] == "24", "config must survive a failed read"
    assert fc.config_consumption()["reverted"] == []


def test_revert_is_idempotent(monkeypatch):
    _rows(monkeypatch, [{"key": KEY, "value": "24"}])
    fc.load_config()
    _rows(monkeypatch, [])
    assert fc.load_config() == 0
    assert fc.config_consumption()["reverted"] == [KEY]
    fc.load_config()
    assert fc.config_consumption()["reverted"] == [], "nothing left to revert"


def test_pinned_key_is_not_env_reverted(monkeypatch):
    """A pinned key was never applied to env, so withdrawing it must not clear the pin."""
    monkeypatch.setenv("ORCH_CONFIG_ENV_PINS", KEY)
    monkeypatch.setenv(KEY, "local-only")
    _rows(monkeypatch, [{"key": KEY, "value": "fleet"}])
    fc.load_config()
    assert os.environ[KEY] == "local-only"

    _rows(monkeypatch, [])
    fc.load_config()
    assert os.environ[KEY] == "local-only"


def test_revert_withdrawn_keys_handles_none_and_empty():
    assert fc.revert_withdrawn_keys(None) == []
    assert fc.revert_withdrawn_keys(set()) == []
