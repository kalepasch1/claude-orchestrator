"""Slice-2 proofs: bounded budget on threshold crossings, router integration,
and polling-fallback correctness.

Slice 1 proved idle modules get zero and that starvation is prevented. The two
remaining claims in the spec are that a threshold crossing receives a BOUNDED
budget, and that the polling fallback preserves correctness. Both are here.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spike_attention_budget import (  # noqa: E402
    ProportionalRouter,
    Router,
    Signal,
    SpikeAttentionBudget,
)


def _sig(module, significance, tick):
    return Signal(module=module, significance=significance, tick=tick)


# ------------------------------------------------------- bounded budget

def test_single_spiking_module_cannot_take_the_whole_budget():
    """Blast radius: one bad significance sensor must not drain all attention."""
    b = SpikeAttentionBudget(total_budget=1.0, max_share=0.25, debounce_ticks=1)
    alloc = b.step(0, [_sig("greedy", 99.0, 0)])
    assert alloc.budgets["greedy"] == 0.25


def test_bound_holds_no_matter_how_many_modules_are_active():
    b = SpikeAttentionBudget(total_budget=1.0, max_share=0.25, debounce_ticks=1)
    for count in (1, 2, 3, 8):
        fresh = SpikeAttentionBudget(total_budget=1.0, max_share=0.25, debounce_ticks=1)
        signals = [_sig(f"m{i}", 5.0, 0) for i in range(count)]
        alloc = fresh.step(0, signals)
        assert all(v <= 0.25 + 1e-9 for v in alloc.budgets.values())


def test_unspent_budget_is_reported_not_redistributed():
    """A bound that stops binding when few modules are active is not a bound."""
    b = SpikeAttentionBudget(total_budget=1.0, max_share=0.25, debounce_ticks=1)
    alloc = b.step(0, [_sig("a", 5.0, 0)])
    assert alloc.unspent == pytest.approx(0.75)
    assert sum(alloc.budgets.values()) == pytest.approx(0.25)


def test_even_split_still_applies_below_the_cap():
    b = SpikeAttentionBudget(total_budget=1.0, max_share=0.9, debounce_ticks=1)
    alloc = b.step(0, [_sig("a", 5.0, 0), _sig("b", 5.0, 0)])
    assert all(v == pytest.approx(0.5) for v in alloc.budgets.values())
    assert alloc.unspent == pytest.approx(0.0)


def test_no_cap_means_no_unspent():
    b = SpikeAttentionBudget(total_budget=1.0, debounce_ticks=1)
    alloc = b.step(0, [_sig("a", 5.0, 0)])
    assert alloc.budgets["a"] == pytest.approx(1.0)
    assert alloc.unspent == pytest.approx(0.0)


def test_non_positive_max_share_is_rejected():
    with pytest.raises(ValueError):
        SpikeAttentionBudget(max_share=0)


def test_bound_applies_to_the_fallback_path_too():
    b = SpikeAttentionBudget(total_budget=1.0, max_share=0.3,
                             debounce_ticks=1, fallback_after_idle_ticks=2)
    b.step(0, [_sig("a", 5.0, 0)])
    for tick in range(1, 8):
        alloc = b.step(tick, [_sig("a", 0.0, tick)])
        if alloc.fallback:
            assert all(v <= 0.3 + 1e-9 for v in alloc.budgets.values())
            break
    else:
        pytest.fail("fallback never fired")


# ------------------------------------------------------ router integration

def test_router_reweights_within_the_same_pot():
    b = SpikeAttentionBudget(total_budget=1.0, debounce_ticks=1,
                             router=ProportionalRouter())
    alloc = b.step(0, [_sig("loud", 3.0, 0), _sig("soft", 1.0, 0)])
    assert sum(alloc.budgets.values()) == pytest.approx(1.0)
    assert alloc.budgets["loud"] == pytest.approx(0.75)
    assert alloc.budgets["soft"] == pytest.approx(0.25)


def test_router_cannot_wake_an_idle_module():
    """The router only ever re-weights what the allocator already funded."""
    class Meddler(Router):
        def weight(self, budgets, significance):
            out = dict(budgets)
            out["ghost"] = 5.0     # not active, must not appear
            return out

    b = SpikeAttentionBudget(total_budget=1.0, debounce_ticks=1, router=Meddler())
    b.step(0, [_sig("a", 5.0, 0), _sig("ghost", 0.0, 0)])
    alloc = b.step(1, [_sig("a", 5.0, 1), _sig("ghost", 0.0, 1)])
    # ghost never spiked, so even though the router named it, it is not active.
    assert "ghost" not in alloc.active


def test_router_cannot_exceed_max_share():
    class Greedy(Router):
        def weight(self, budgets, significance):
            return {m: 100.0 for m in budgets}

    b = SpikeAttentionBudget(total_budget=1.0, max_share=0.2,
                             debounce_ticks=1, router=Greedy())
    alloc = b.step(0, [_sig("a", 5.0, 0), _sig("b", 5.0, 0)])
    assert all(v <= 0.2 + 1e-9 for v in alloc.budgets.values())


def test_router_cannot_exceed_total_budget():
    class Greedy(Router):
        def weight(self, budgets, significance):
            return {m: 10.0 for m in budgets}

    b = SpikeAttentionBudget(total_budget=1.0, debounce_ticks=1, router=Greedy())
    alloc = b.step(0, [_sig("a", 5.0, 0), _sig("b", 5.0, 0)])
    assert sum(alloc.budgets.values()) <= 1.0 + 1e-9


def test_router_with_zero_significance_falls_back_to_even_split():
    b = SpikeAttentionBudget(total_budget=1.0, rise=0.0, fall=0.0,
                             debounce_ticks=1, router=ProportionalRouter())
    alloc = b.step(0, [_sig("a", 0.0, 0), _sig("b", 0.0, 0)])
    assert all(v == pytest.approx(0.5) for v in alloc.budgets.values())


def test_router_does_not_break_the_zero_budget_guarantee():
    b = SpikeAttentionBudget(total_budget=1.0, debounce_ticks=1,
                             router=ProportionalRouter())
    alloc = b.step(0, [_sig("hot", 5.0, 0), _sig("quiet", 0.0, 0)])
    assert "quiet" not in alloc.budgets


# ------------------------------------------- polling fallback correctness

def test_fallback_does_not_fire_while_spikes_are_arriving():
    b = SpikeAttentionBudget(debounce_ticks=1, fallback_after_idle_ticks=2)
    for tick in range(10):
        alloc = b.step(tick, [_sig("a", 5.0, tick)])
        assert alloc.fallback is False


def test_fallback_covers_every_known_module_over_time():
    """Round robin must be fair, not just non-empty."""
    b = SpikeAttentionBudget(debounce_ticks=1, fallback_after_idle_ticks=1)
    for tick, name in enumerate(["a", "b", "c"]):
        b.step(tick, [_sig(name, 5.0, tick)])
    seen = set()
    for tick in range(3, 20):
        alloc = b.step(tick, [_sig(n, 0.0, tick) for n in ("a", "b", "c")])
        if alloc.fallback:
            seen.update(alloc.funded)
    assert seen == {"a", "b", "c"}


def test_fallback_yields_immediately_to_a_real_spike():
    b = SpikeAttentionBudget(debounce_ticks=1, fallback_after_idle_ticks=1)
    b.step(0, [_sig("a", 5.0, 0)])
    b.step(1, [_sig("a", 0.0, 1)])
    b.step(2, [_sig("a", 0.0, 2)])
    alloc = b.step(3, [_sig("a", 9.0, 3)])
    assert alloc.fallback is False
    assert alloc.budgets["a"] == pytest.approx(1.0)


def test_fallback_never_invents_a_module():
    b = SpikeAttentionBudget(debounce_ticks=1, fallback_after_idle_ticks=1)
    for tick in range(5):
        alloc = b.step(tick, [])
    assert alloc.budgets == {}   # nothing known yet, nothing to poll


# ----------------------------------------------------- determinism holds

def test_replay_preserves_bounds_and_router():
    script = [
        (0, [_sig("a", 3.0, 0), _sig("b", 1.0, 0)]),
        (1, [_sig("a", 3.0, 1), _sig("b", 1.0, 1)]),
    ]
    b = SpikeAttentionBudget(total_budget=1.0, max_share=0.4, debounce_ticks=1,
                             router=ProportionalRouter())
    first = [a.budgets for a in b.replay(script)]
    second = [a.budgets for a in b.replay(script)]
    assert first == second
    assert all(v <= 0.4 + 1e-9 for a in first for v in a.values())
