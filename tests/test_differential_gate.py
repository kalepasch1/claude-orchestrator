"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836)."""
from runner.differential_gate import differential_adjudicate


def test_accepts_when_primary_matches_panel_and_ledger():
    v = differential_adjudicate(
        primary_outputs=[1, 2, 3],
        panel_outputs_by_impl=[[1, 2, 3], [1, 2, 3], [1, 2, 3]],
        primary_ledger={"assumes_utc", "closed_interval"},
        panel_ledgers=[{"assumes_utc", "closed_interval"}, {"assumes_utc", "closed_interval"}],
    )
    assert v.verdict == "accept"
    assert v.agreement == 1.0


def test_routes_to_human_on_probe_disagreement_with_counterexample():
    v = differential_adjudicate(
        primary_outputs=[1, 999, 3],  # wrong specific value on probe #1
        panel_outputs_by_impl=[[1, 2, 3], [1, 2, 3], [1, 2, 3]],
        primary_ledger=set(),
        panel_ledgers=[set(), set()],
    )
    assert v.verdict == "route_to_human"
    assert len(v.disagreements) == 1
    assert v.disagreements[0].probe_index == 1
    assert v.disagreements[0].primary == 999 and v.disagreements[0].consensus == 2


def test_routes_to_human_on_ledger_divergence_even_if_outputs_agree():
    v = differential_adjudicate(
        primary_outputs=[1, 2],
        panel_outputs_by_impl=[[1, 2], [1, 2]],
        primary_ledger={"assumes_local_time"},              # primary read the spec differently
        panel_ledgers=[{"assumes_utc"}, {"assumes_utc"}],   # panel agrees on UTC
    )
    assert v.verdict == "route_to_human"
    assert "assumes_utc" in v.ledger_divergence or "assumes_local_time" in v.ledger_divergence


def test_consensus_is_majority_not_unanimity():
    # one panel member is the odd one out; consensus is still the majority value
    v = differential_adjudicate(
        primary_outputs=[5],
        panel_outputs_by_impl=[[5], [5], [7]],
        primary_ledger=set(),
        panel_ledgers=[set(), set(), set()],
    )
    assert v.verdict == "accept"


def test_empty_probes_route_to_human():
    v = differential_adjudicate([], [], set(), [])
    assert v.verdict == "route_to_human"
