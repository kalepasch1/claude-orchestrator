"""get_regime_oracle + the consume-one-event shape, and the pareto.* import path.

Deliberately a SEPARATE file from test_household_legal.py. That file is one of
the five paths this task kept conflicting on; adding here keeps the new coverage
out of the merge path entirely.
"""
import os
import sys

# '2080' is not a valid Python identifier — same sys.path convention as
# pareto/2080/contracts/test_contracts_smoke.py.
# The modules under test live one directory up. This file moved into a
# `tests/` directory so write_guard's placement rule holds for the tree;
# the import targets did not move.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import regime_consumer as rc  # noqa: E402


# ── get_regime_oracle: always returns something usable ───────────────────────

def test_returns_an_oracle_with_the_protocol_shape():
    oracle = rc.get_regime_oracle()
    assert callable(getattr(oracle, "get_events", None))
    assert callable(getattr(oracle, "subscribe", None))


def test_degrades_to_the_noop_when_contracts_expose_no_instance():
    """RegimeOracle is a Protocol, so today there is no instance to return."""
    assert isinstance(rc.get_regime_oracle(), rc.NoOpRegimeOracle)


def test_the_noop_oracle_reports_no_events_rather_than_raising():
    oracle = rc.get_regime_oracle()
    assert oracle.get_events("CA") == []
    assert oracle.subscribe("CA", "cb") is None


def test_noop_is_distinguishable_from_a_quiet_real_feed():
    """An empty list alone cannot say "no feed" vs "no changes"; `available` can."""
    assert rc.get_regime_oracle().available is False


def test_an_explicit_provider_wins():
    sentinel = object()
    assert rc.get_regime_oracle(lambda: sentinel) is sentinel


def test_a_non_callable_provider_is_used_as_the_instance():
    sentinel = object()
    assert rc.get_regime_oracle(sentinel) is sentinel


def test_a_provider_that_raises_degrades_silently():
    def boom():
        raise RuntimeError("feed down")

    assert isinstance(rc.get_regime_oracle(boom), rc.NoOpRegimeOracle)


def test_a_provider_that_returns_none_degrades_silently():
    assert isinstance(rc.get_regime_oracle(lambda: None), rc.NoOpRegimeOracle)


def test_import_error_inside_contracts_degrades_silently(monkeypatch):
    def boom():
        raise ImportError("no autonomy module here")

    monkeypatch.setattr(rc, "_load_contracts_module", boom)
    assert isinstance(rc.get_regime_oracle(), rc.NoOpRegimeOracle)


# ── safe_consume_regime_event, one-argument shape -> dict ────────────────────

def test_one_arg_none_returns_an_empty_dict():
    result = rc.safe_consume_regime_event(None)
    assert result == {}
    assert isinstance(result, dict)


def test_one_arg_garbage_returns_an_empty_dict():
    for junk in (object(), "", 0, [], {"nothing": "useful"}):
        assert rc.safe_consume_regime_event(junk) == {}


def test_one_arg_valid_event_returns_the_normalised_dict():
    result = rc.safe_consume_regime_event({"regime": "CA", "rule_id": "R-1"})
    assert result["jurisdiction"] == "CA"
    assert result["rule_id"] == "R-1"


def test_one_arg_accepts_the_regime_event_dataclass():
    contracts = rc._load_contracts_module()
    event = contracts.RegimeEvent(jurisdiction="NY", rule_id="R-9")
    assert rc.safe_consume_regime_event(event)["jurisdiction"] == "NY"


# ── the two-argument shape is untouched ──────────────────────────────────────

class _Oracle:
    def get_events(self, jurisdiction):
        return [{"regime": jurisdiction, "rule_id": "R-2"}]

    def subscribe(self, jurisdiction, callback):
        return None


def test_two_arg_shape_still_returns_a_list():
    events = rc.safe_consume_regime_event(_Oracle(), "CA")
    assert isinstance(events, list)
    assert events[0]["jurisdiction"] == "CA"


def test_two_arg_shape_still_fails_soft_to_a_list_not_a_dict():
    """The regression that arity dispatch could plausibly introduce."""
    assert rc.safe_consume_regime_event(None, "CA") == []
    assert rc.safe_consume_regime_event(object(), "CA") == []


def test_explicit_none_jurisdiction_is_not_mistaken_for_the_one_arg_shape():
    assert rc.safe_consume_regime_event(None, None) == []


# ── the dotted import path the acceptance command uses ───────────────────────

def test_pareto_household_legal_is_importable_by_dotted_path():
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from pareto.household_legal import (  # noqa: PLC0415
        get_regime_oracle,
        safe_consume_regime_event,
    )

    assert callable(get_regime_oracle)
    assert isinstance(safe_consume_regime_event(None), dict)
