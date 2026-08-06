#!/usr/bin/env python3
"""Tests for runner/persona_registry.py against the v4_contracts.PersonaRegistry
Protocol. No DB required: the loader is stubbed."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import persona_registry as pr
from v4_contracts import PersonaRegistry


def _offline_registry():
    """A registry that cannot reach the DB - exercises the degrade path."""
    reg = pr._Registry()
    reg._load_calibration = lambda: {}
    return reg


def test_singleton_satisfies_protocol():
    assert isinstance(pr.registry, PersonaRegistry)


def test_definitions_are_declared_once_and_read_only():
    reg = _offline_registry()
    ids = reg.personas()
    assert ids == sorted(ids), "persona order must be stable"
    assert "compliance_counsel" in ids
    definition = reg.get("compliance_counsel")
    definition["label"] = "mutated"
    assert reg.get("compliance_counsel")["label"] == "Compliance Counsel"


def test_unknown_persona_reads_default_not_zero():
    reg = _offline_registry()
    assert reg.get("nope") is None
    assert reg.reliability("nope") == reg.default_reliability
    assert reg.reliability("nope") != 0.0


def test_db_outage_degrades_to_defaults():
    """The real loader must swallow a broken db module, not propagate."""
    reg = pr._Registry()
    saved = sys.modules.get("db")
    sys.modules["db"] = object()  # any attribute access -> AttributeError
    try:
        loaded = reg._load_calibration()
        assert loaded == {}
        assert reg.reliability("risk_officer") == reg.default_reliability
    finally:
        if saved is None:
            sys.modules.pop("db", None)
        else:
            sys.modules["db"] = saved


def test_record_outcome_moves_reliability_and_returns_new_value():
    reg = _offline_registry()
    start = reg.reliability("staff_engineer")
    after_good = reg.record_outcome("staff_engineer", True)
    assert after_good > start
    assert after_good == reg.reliability("staff_engineer")
    after_bad = reg.record_outcome("staff_engineer", False)
    assert after_bad < after_good


def test_reliability_stays_in_unit_interval():
    reg = _offline_registry()
    for _ in range(200):
        reg.record_outcome("operator", True)
    assert 0.0 <= reg.reliability("operator") <= 1.0
    for _ in range(400):
        reg.record_outcome("operator", False)
    assert 0.0 <= reg.reliability("operator") <= 1.0


def test_calibration_compounds_rather_than_resetting():
    reg = _offline_registry()
    for _ in range(10):
        reg.record_outcome("product_owner", True)
    learned = reg.reliability("product_owner")
    reg._load_calibration = lambda: {"product_owner": (0.1, 99.0)}
    reg.refresh()
    assert reg.reliability("product_owner") == learned, \
        "locally observed outcomes must survive a refresh"


def test_unknown_persona_cannot_be_calibrated_into_existence():
    reg = _offline_registry()
    before = set(reg.personas())
    reg.record_outcome("typo_persona", True)
    assert set(reg.personas()) == before


def test_reliabilities_covers_every_persona():
    reg = _offline_registry()
    scores = reg.reliabilities()
    assert set(scores) == set(reg.personas())
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_calibration_rows_are_adopted_when_no_local_history():
    reg = pr._Registry()
    reg._load_calibration = lambda: {"risk_officer": (0.83, 40.0)}
    reg.refresh()
    assert abs(reg.reliability("risk_officer") - 0.83) < 1e-9


def test_zero_weight_outcome_is_a_noop():
    reg = _offline_registry()
    before = reg.reliability("security_reviewer")
    reg.record_outcome("security_reviewer", False, weight=0.0)
    assert reg.reliability("security_reviewer") == before


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("PASS", name)
        except AssertionError as exc:
            failures += 1
            print("FAIL", name, exc)
    sys.exit(1 if failures else 0)
