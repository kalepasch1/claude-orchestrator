"""get_required_kinds() and get_task_kinds() must not share a cache slot.

Both used to read and write `_TDD_CACHE["kinds"]`, but they answer different questions:

  get_required_kinds()  ORCH_TDD_REQUIRED_KINDS, fleet_config only, empty set means "off"
  get_task_kinds()      ORCH_TDD_TASK_KINDS, fleet_config OR env, defaults to feature/new-module

On an unconfigured fleet the first call cached an empty set and the second returned it instead
of its documented default — for 30 seconds, TDD gating was silently off, and which of the two
was affected depended purely on call order. Nothing in the suite covered the interaction.
"""
import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import tdd_gate  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache():
    tdd_gate.invalidate_cache()
    yield
    tdd_gate.invalidate_cache()


def test_required_kinds_does_not_poison_task_kinds(monkeypatch):
    monkeypatch.setattr(tdd_gate.db, "select", lambda *a, **k: [])
    monkeypatch.delenv("ORCH_TDD_TASK_KINDS", raising=False)

    assert tdd_gate.get_required_kinds() == set()          # unconfigured -> off
    assert tdd_gate.get_task_kinds() == {"feature", "new-module"}


def test_task_kinds_does_not_poison_required_kinds(monkeypatch):
    """Reverse order: the documented default must not be mistaken for explicit config."""
    monkeypatch.setattr(tdd_gate.db, "select", lambda *a, **k: [])
    monkeypatch.delenv("ORCH_TDD_TASK_KINDS", raising=False)

    assert tdd_gate.get_task_kinds() == {"feature", "new-module"}
    assert tdd_gate.get_required_kinds() == set()


def test_enabled_cache_is_independent_of_kinds(monkeypatch):
    monkeypatch.setattr(tdd_gate.db, "select", lambda *a, **k: [])
    monkeypatch.setenv("ORCH_TDD_ENABLED", "true")

    tdd_gate.get_required_kinds()                          # writes its own slot only
    assert tdd_gate.is_tdd_enabled() is True


def test_invalidate_cache_clears_every_slot(monkeypatch):
    monkeypatch.setattr(tdd_gate.db, "select", lambda *a, **k: [])
    tdd_gate.get_required_kinds()
    tdd_gate.get_task_kinds()
    tdd_gate.is_tdd_enabled()

    tdd_gate.invalidate_cache()
    stale = [k for k, v in tdd_gate._TDD_CACHE.items()
             if not k.endswith("_at") and k != "cached_at" and v is not None]
    assert not stale, f"invalidate_cache() left {stale} populated; a config change won't be seen"
