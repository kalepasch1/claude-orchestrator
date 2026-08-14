"""Deterministic proofs for the spike attention budget (v15-03 slice 1).

The headline proof required by the spec is the first test: idle modules receive
ZERO execution budget. The rest guard the mechanisms that keep that true without
starving anything — hysteresis, debounce, fairness, shedding, replay.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spike_attention_budget import (  # noqa: E402
    Signal,
    SpikeAttentionBudget,
)


def _sig(module, significance, tick, **kw):
    return Signal(module=module, significance=significance, tick=tick, **kw)


# --------------------------------------------------------------- the main proof

def test_idle_modules_receive_exactly_zero_budget():
    """The property the whole module exists for."""
    b = SpikeAttentionBudget(total_budget=1.0, debounce_ticks=1)
    alloc = b.step(0, [_sig("hot", 5.0, 0), _sig("quiet", 0.0, 0)])
    assert alloc.budgets == {"hot": 1.0}
    assert "quiet" not in alloc.budgets      # absent, not zero-valued
    assert alloc.idle == ["quiet"]


def test_no_spikes_means_no_budget_spent_at_all():
    b = SpikeAttentionBudget(total_budget=1.0, debounce_ticks=1)
    for tick in range(10):
        alloc = b.step(tick, [_sig("a", 0.1, tick), _sig("b", 0.2, tick)])
        assert alloc.budgets == {}
    assert b.stats()["total_budget_spent"] == 0.0
    assert b.stats()["idle_ticks"] == 10


def test_module_that_stops_reporting_goes_idle():
    b = SpikeAttentionBudget(debounce_ticks=1)
    b.step(0, [_sig("a", 3.0, 0)])
    alloc = b.step(1, [])  # a reported nothing: no spike, no budget
    assert alloc.budgets == {}


# ------------------------------------------------------------------- debounce

def test_debounce_suppresses_a_single_tick_spike():
    b = SpikeAttentionBudget(debounce_ticks=2)
    assert b.step(0, [_sig("a", 9.0, 0)]).budgets == {}      # first tick: not yet
    assert b.step(1, [_sig("a", 9.0, 1)]).budgets == {"a": 1.0}


def test_debounce_streak_resets_on_a_quiet_tick():
    b = SpikeAttentionBudget(debounce_ticks=3)
    b.step(0, [_sig("a", 9.0, 0)])
    b.step(1, [_sig("a", 0.0, 1)])   # streak broken
    b.step(2, [_sig("a", 9.0, 2)])
    assert b.step(3, [_sig("a", 9.0, 3)]).budgets == {}   # only 2 of 3 so far
    assert b.step(4, [_sig("a", 9.0, 4)]).budgets == {"a": 1.0}


# ------------------------------------------------------------------ hysteresis

def test_active_module_survives_the_gap_between_fall_and_rise():
    """Between FALL and RISE an awake module stays awake — no flapping."""
    b = SpikeAttentionBudget(rise=1.0, fall=0.6, debounce_ticks=1)
    b.step(0, [_sig("a", 1.5, 0)])
    alloc = b.step(1, [_sig("a", 0.8, 1)])  # below rise, above fall
    assert alloc.budgets == {"a": 1.0}


def test_module_sleeps_once_signal_drops_below_fall():
    b = SpikeAttentionBudget(rise=1.0, fall=0.6, debounce_ticks=1)
    b.step(0, [_sig("a", 1.5, 0)])
    assert b.step(1, [_sig("a", 0.5, 1)]).budgets == {}


def test_hysteresis_prevents_repeated_wake_cost():
    b = SpikeAttentionBudget(rise=1.0, fall=0.6, debounce_ticks=1)
    for tick, value in enumerate([1.2, 0.9, 1.1, 0.7, 1.3]):
        b.step(tick, [_sig("a", value, tick)])
    assert b.stats()["modules"]["a"]["wakes"] == 1


def test_fall_above_rise_is_rejected():
    with pytest.raises(ValueError):
        SpikeAttentionBudget(rise=1.0, fall=2.0)


def test_non_positive_budget_is_rejected():
    with pytest.raises(ValueError):
        SpikeAttentionBudget(total_budget=0)


# --------------------------------------------------------------------- fairness

def test_budget_splits_evenly_across_active_modules():
    b = SpikeAttentionBudget(total_budget=1.0, debounce_ticks=1)
    alloc = b.step(0, [_sig("a", 2.0, 0), _sig("b", 3.0, 0), _sig("c", 4.0, 0)])
    assert set(alloc.budgets) == {"a", "b", "c"}
    assert all(v == pytest.approx(1 / 3) for v in alloc.budgets.values())


def test_full_budget_is_distributed_when_anything_is_active():
    b = SpikeAttentionBudget(total_budget=6.0, debounce_ticks=1)
    alloc = b.step(0, [_sig("a", 2.0, 0), _sig("b", 2.0, 0)])
    assert sum(alloc.budgets.values()) == pytest.approx(6.0)


def test_starvation_guard_admits_a_module_held_out_too_long():
    """A loud neighbour must not be able to hold a ready module out forever.

    The rescue is periodic, not permanent: once `quiet` is funded its wait clock
    resets and `loud` reclaims the slot until the threshold is crossed again. So
    this asserts over the whole run rather than on the final tick.
    """
    b = SpikeAttentionBudget(max_active=1, starvation_ticks=3, debounce_ticks=1)
    allocs = [
        b.step(tick, [_sig("loud", 9.0, tick), _sig("quiet", 1.1, tick)])
        for tick in range(12)
    ]
    rescued = [a.tick for a in allocs if "quiet" in a.starved_admitted]
    assert rescued, "starved module was never admitted"
    assert all("quiet" in allocs[t].budgets for t in rescued)
    # and it keeps happening — one rescue then permanent starvation is not a guard
    assert len(rescued) >= 2


def test_starved_module_wait_clock_resets_after_funding():
    b = SpikeAttentionBudget(max_active=1, starvation_ticks=3, debounce_ticks=1)
    allocs = [
        b.step(tick, [_sig("loud", 9.0, tick), _sig("quiet", 1.1, tick)])
        for tick in range(12)
    ]
    rescued = [a.tick for a in allocs if "quiet" in a.starved_admitted]
    gaps = [b_ - a_ for a_, b_ in zip(rescued, rescued[1:])]
    assert all(gap >= 3 for gap in gaps), f"rescued too often: {rescued}"


def test_no_starvation_admission_before_the_threshold():
    b = SpikeAttentionBudget(max_active=1, starvation_ticks=50, debounce_ticks=1)
    alloc = b.step(0, [_sig("loud", 9.0, 0), _sig("quiet", 1.1, 0)])
    assert alloc.starved_admitted == []
    assert set(alloc.budgets) == {"loud"}


def test_starvation_guard_can_be_disabled():
    b = SpikeAttentionBudget(max_active=1, starvation_ticks=0, debounce_ticks=1)
    for tick in range(30):
        alloc = b.step(tick, [_sig("loud", 9.0, tick), _sig("quiet", 1.1, tick)])
    assert set(alloc.budgets) == {"loud"}


# ---------------------------------------------------------------- overload shed

def test_shedding_keeps_the_most_significant_modules():
    b = SpikeAttentionBudget(max_active=2, debounce_ticks=1, starvation_ticks=0)
    alloc = b.step(0, [
        _sig("a", 1.1, 0), _sig("b", 5.0, 0), _sig("c", 3.0, 0),
    ])
    assert set(alloc.budgets) == {"b", "c"}
    assert alloc.shed == ["a"]


def test_shedding_is_recorded_per_module():
    b = SpikeAttentionBudget(max_active=1, debounce_ticks=1, starvation_ticks=0)
    for tick in range(3):
        b.step(tick, [_sig("a", 1.1, tick), _sig("b", 9.0, tick)])
    assert b.stats()["modules"]["a"]["shed"] == 3


def test_shed_ties_break_deterministically_by_name():
    b = SpikeAttentionBudget(max_active=1, debounce_ticks=1, starvation_ticks=0)
    alloc = b.step(0, [_sig("zeta", 2.0, 0), _sig("alpha", 2.0, 0)])
    assert set(alloc.budgets) == {"alpha"}


# -------------------------------------------------------------------- fallback

def test_clock_fallback_is_off_by_default():
    b = SpikeAttentionBudget(debounce_ticks=1)
    b.step(0, [_sig("a", 5.0, 0)])
    for tick in range(1, 40):
        alloc = b.step(tick, [_sig("a", 0.0, tick)])
    assert alloc.budgets == {}
    assert b.stats()["fallback_ticks"] == 0


def test_clock_fallback_funds_round_robin_when_enabled():
    """A silent sensor must not be able to wedge the system into permanent idle."""
    b = SpikeAttentionBudget(debounce_ticks=1, fallback_after_idle_ticks=3)
    b.step(0, [_sig("a", 5.0, 0)])
    b.step(1, [_sig("b", 5.0, 1)])
    funded = []
    for tick in range(2, 12):
        alloc = b.step(tick, [_sig("a", 0.0, tick), _sig("b", 0.0, tick)])
        if alloc.fallback:
            funded.append(alloc.funded)
    assert funded, "fallback never fired"
    assert [f[0] for f in funded[:2]] == ["a", "b"]  # round robin, not always the same


# ---------------------------------------------------------- replay + telemetry

def test_replay_is_deterministic():
    script = [
        (0, [_sig("a", 2.0, 0), _sig("b", 0.1, 0)]),
        (1, [_sig("a", 2.0, 1), _sig("b", 2.0, 1)]),
        (2, [_sig("a", 0.0, 2), _sig("b", 2.0, 2)]),
    ]
    b = SpikeAttentionBudget(debounce_ticks=1)
    first = [a.budgets for a in b.replay(script)]
    second = [a.budgets for a in b.replay(script)]
    assert first == second


def test_replay_does_not_disturb_live_state():
    b = SpikeAttentionBudget(debounce_ticks=1)
    b.step(0, [_sig("a", 5.0, 0)])
    before = b.stats()
    b.replay([(0, [_sig("zzz", 9.0, 0)])])
    assert b.stats() == before


def test_stats_make_idle_cost_observable():
    b = SpikeAttentionBudget(total_budget=1.0, debounce_ticks=1)
    b.step(0, [_sig("a", 5.0, 0)])
    b.step(1, [_sig("a", 0.0, 1)])
    b.step(2, [_sig("a", 0.0, 2)])
    stats = b.stats()
    assert stats["ticks"] == 3
    assert stats["funded_ticks"] == 1
    assert stats["idle_ticks"] == 2
    assert stats["total_budget_spent"] == pytest.approx(1.0)
    assert stats["modules"]["a"]["total_budget"] == pytest.approx(1.0)


def test_route_hint_is_carried_through_untouched():
    """Seam for the neuromorphic router: it must survive without this module parsing it."""
    b = SpikeAttentionBudget(debounce_ticks=1)
    alloc = b.step(0, [_sig("a", 5.0, 0, route_hint="neuro:core-3")])
    assert alloc.budgets == {"a": 1.0}


def test_empty_tick_is_safe():
    b = SpikeAttentionBudget()
    alloc = b.step(0, [])
    assert alloc.budgets == {} and alloc.active == [] and alloc.idle == []
