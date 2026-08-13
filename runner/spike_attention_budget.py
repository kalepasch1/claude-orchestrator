#!/usr/bin/env python3
"""spike_attention_budget.py — attention is spent on spikes, never on idling.

v15-03 slice 1. The allocator core: which modules get execution budget on a given
tick, and how much.

THE PROPERTY THIS EXISTS TO GUARANTEE: a module that is not spiking receives
EXACTLY zero budget. Not "a small share", not "a rounding error" — zero. Every
other feature here (hysteresis, fairness, shedding) is a way of keeping that true
without starving anything that legitimately needs to run.

DETERMINISM IS PART OF THE CONTRACT. Nothing in this module reads a clock, a random
source, or a database. Ticks are supplied by the caller, so a sequence of
observations replays to a byte-identical allocation. That is what makes the "idle
modules got zero" claim auditable after the fact rather than a thing you have to
trust.

Integration seam: `route_hint` on a signal is passed through untouched to the
allocation record, so the neuromorphic router can attach its own scoring without
this module needing to know about it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

# A module must exceed RISE to wake, and drop below FALL to sleep again. Two
# thresholds, not one: a single threshold makes a signal hovering at the boundary
# flap between active and idle every tick, and each flap costs a full wake.
DEFAULT_RISE = 1.0
DEFAULT_FALL = 0.6
# Consecutive ticks above RISE before a wake is honoured. Absorbs single-tick noise.
DEFAULT_DEBOUNCE = 2
# A module continuously ready but never funded for this many ticks is force-admitted.
DEFAULT_STARVATION_TICKS = 20
# Hard ceiling on concurrently funded modules; excess is shed by significance.
DEFAULT_MAX_ACTIVE = 8


@dataclass
class Signal:
    """One module's significance reading for one tick."""
    module: str
    significance: float
    tick: int
    route_hint: Optional[str] = None


@dataclass
class _ModuleState:
    above_streak: int = 0
    active: bool = False
    last_funded_tick: Optional[int] = None
    ready_since: Optional[int] = None
    total_budget: float = 0.0
    wake_count: int = 0
    shed_count: int = 0


class Router:
    """Integration seam for the neuromorphic router.

    The router only ever RE-WEIGHTS an allocation the budget has already decided.
    It cannot wake an idle module, cannot exceed max_share, and cannot raise the
    total above total_budget — the broker clamps and rescales afterwards. Keeping
    the router advisory is what preserves the zero-budget-when-idle guarantee no
    matter what a future routing policy decides to do.
    """

    def weight(self, budgets: Dict[str, float],
               significance: Dict[str, float]) -> Dict[str, float]:  # pragma: no cover
        raise NotImplementedError


class ProportionalRouter(Router):
    """Reference router: split the same pot in proportion to significance."""

    def weight(self, budgets, significance):
        total_pot = sum(budgets.values())
        weights = {m: max(0.0, float(significance.get(m, 0.0))) for m in budgets}
        total_weight = sum(weights.values())
        if total_weight <= 0:
            return dict(budgets)
        return {m: total_pot * w / total_weight for m, w in weights.items()}


@dataclass
class Allocation:
    """The result of one tick. `budgets` omits every module that gets nothing."""
    tick: int
    budgets: Dict[str, float] = field(default_factory=dict)
    active: List[str] = field(default_factory=list)
    shed: List[str] = field(default_factory=list)
    starved_admitted: List[str] = field(default_factory=list)
    fallback: bool = False
    idle: List[str] = field(default_factory=list)
    # Budget the tick was entitled to but did not hand out, because max_share
    # bound it. Reported rather than redistributed so the cap always binds.
    unspent: float = 0.0

    @property
    def funded(self) -> List[str]:
        return sorted(self.budgets)


class SpikeAttentionBudget:
    """Deterministic spike-triggered attention allocator.

    Usage is one call per tick:

        budget = SpikeAttentionBudget(total_budget=1.0)
        alloc = budget.step(tick=0, signals=[Signal("parser", 1.4, 0)])
    """

    def __init__(
        self,
        total_budget: float = 1.0,
        rise: float = DEFAULT_RISE,
        fall: float = DEFAULT_FALL,
        debounce_ticks: int = DEFAULT_DEBOUNCE,
        starvation_ticks: int = DEFAULT_STARVATION_TICKS,
        max_active: int = DEFAULT_MAX_ACTIVE,
        fallback_after_idle_ticks: Optional[int] = None,
        max_share: Optional[float] = None,
        router: Optional["Router"] = None,
    ):
        if fall > rise:
            raise ValueError("fall threshold must be <= rise threshold (hysteresis)")
        if total_budget <= 0:
            raise ValueError("total_budget must be positive")
        if max_share is not None and max_share <= 0:
            raise ValueError("max_share must be positive when set")
        self.total_budget = float(total_budget)
        self.rise = float(rise)
        self.fall = float(fall)
        self.debounce_ticks = max(1, int(debounce_ticks))
        self.starvation_ticks = int(starvation_ticks)
        self.max_active = max(1, int(max_active))
        # None disables the clock-driven fallback entirely.
        self.fallback_after_idle_ticks = fallback_after_idle_ticks
        # Per-module ceiling. Without it a lone spiking module absorbs the entire
        # budget, which is fine for throughput and terrible for blast radius: one
        # misbehaving significance sensor can consume every unit of attention the
        # system has. Unspent remainder is deliberately NOT redistributed — see
        # _apply_bounds.
        self.max_share = max_share
        self.router = router

        self._state: Dict[str, _ModuleState] = {}
        self._ticks_since_any_spike = 0
        self._fallback_cursor = 0
        self.history: List[Allocation] = []

    # ---------------------------------------------------------------- internals

    def _state_for(self, module: str) -> _ModuleState:
        if module not in self._state:
            self._state[module] = _ModuleState()
        return self._state[module]

    def _update_activation(self, signals: Iterable[Signal], tick: int) -> None:
        """Apply hysteresis + debounce to decide who is eligible this tick."""
        seen = set()
        for sig in signals:
            seen.add(sig.module)
            st = self._state_for(sig.module)
            if sig.significance >= self.rise:
                st.above_streak += 1
                if not st.active and st.above_streak >= self.debounce_ticks:
                    st.active = True
                    st.wake_count += 1
                    st.ready_since = tick
            else:
                st.above_streak = 0
                # Hysteresis: only release once the signal drops below FALL. Between
                # FALL and RISE an already-active module stays active, which is the
                # whole point — otherwise a signal oscillating around the threshold
                # pays a wake cost on every tick it crosses.
                if st.active and sig.significance < self.fall:
                    st.active = False
                    st.ready_since = None

        # A module that reported nothing this tick has, by definition, no spike.
        for module, st in self._state.items():
            if module not in seen:
                st.above_streak = 0
                st.active = False
                st.ready_since = None

    def _apply_bounds(self, active, sig_by_module) -> Dict[str, float]:
        """Even split, then clamp each module to max_share.

        The clamped remainder is NOT handed to the other active modules. That is a
        deliberate choice: redistributing it means the cap silently stops binding
        whenever few modules are active, so the guarantee "no module can ever draw
        more than max_share in one tick" would hold only sometimes. A bound that
        holds only sometimes is not a bound. The unspent amount is reported on the
        allocation instead, so the slack is visible rather than quietly absorbed.
        """
        share = self.total_budget / len(active)
        if self.max_share is not None:
            share = min(share, self.max_share)
        budgets = {module: share for module in active}
        if self.router is not None:
            budgets = self.router.weight(budgets, sig_by_module)
            if self.max_share is not None:
                # The router advises; it does not get to exceed the bound.
                budgets = {m: min(v, self.max_share) for m, v in budgets.items()}
            total = sum(budgets.values())
            if total > self.total_budget:
                scale = self.total_budget / total
                budgets = {m: v * scale for m, v in budgets.items()}
        return budgets

    def _shed(self, active: List[str], sig_by_module: Dict[str, float]) -> tuple:
        """Trim to max_active, keeping the most significant. Returns (kept, shed)."""
        if len(active) <= self.max_active:
            return active, []
        ranked = sorted(active, key=lambda m: (-sig_by_module.get(m, 0.0), m))
        kept, shed = ranked[: self.max_active], ranked[self.max_active:]
        for module in shed:
            self._state_for(module).shed_count += 1
        return sorted(kept), sorted(shed)

    # -------------------------------------------------------------------- step

    def step(self, tick: int, signals: Optional[Iterable[Signal]] = None) -> Allocation:
        """Advance one tick and return the allocation for it."""
        signals = list(signals or [])
        sig_by_module = {s.module: s.significance for s in signals}

        self._update_activation(signals, tick)
        active = sorted(m for m, st in self._state.items() if st.active)
        active, shed = self._shed(active, sig_by_module)

        alloc = Allocation(tick=tick, active=list(active), shed=shed)

        # Starvation guard: a module that has been ready but unfunded for too long is
        # admitted even if it lost the significance ranking this tick. Without this,
        # a permanently louder neighbour can hold a quiet-but-ready module out
        # forever, and the fairness of the split becomes meaningless.
        if self.starvation_ticks > 0:
            for module, st in sorted(self._state.items()):
                if module in active or not st.active:
                    continue
                # Explicit `is not None` on both: `st.ready_since or tick` reads
                # naturally and is wrong, because ready_since == 0 is falsy. A
                # module ready since the very first tick would compute a wait of
                # zero forever and could never be rescued — the exact module the
                # starvation guard is for.
                if st.last_funded_tick is not None:
                    waited = tick - st.last_funded_tick
                elif st.ready_since is not None:
                    waited = tick - st.ready_since
                else:
                    waited = 0
                if waited >= self.starvation_ticks:
                    active.append(module)
                    alloc.starved_admitted.append(module)
            active = sorted(set(active))

        if active:
            self._ticks_since_any_spike = 0
        else:
            self._ticks_since_any_spike += 1
            # Clock-driven fallback: if nothing has spiked for a long time, fund one
            # module round-robin so a broken or silent sensor cannot wedge the system
            # into permanent inactivity. Opt-in, because for most deployments a quiet
            # system SHOULD stay quiet.
            limit = self.fallback_after_idle_ticks
            if limit is not None and self._ticks_since_any_spike >= limit and self._state:
                known = sorted(self._state)
                pick = known[self._fallback_cursor % len(known)]
                self._fallback_cursor += 1
                active = [pick]
                alloc.fallback = True
                self._ticks_since_any_spike = 0

        # THE INVARIANT: budget is divided among active modules only. Every other
        # module is simply absent from the dict — there is no zero entry to
        # accidentally sum, and no way to hand out a sliver by mistake.
        if active:
            for module, share in self._apply_bounds(active, sig_by_module).items():
                alloc.budgets[module] = share
                st = self._state_for(module)
                st.last_funded_tick = tick
                st.total_budget += share
            alloc.unspent = round(
                self.total_budget - sum(alloc.budgets.values()), 10
            )

        alloc.active = list(active)
        alloc.idle = sorted(m for m in self._state if m not in alloc.budgets)
        self.history.append(alloc)
        return alloc

    # ----------------------------------------------------------- observability

    def stats(self) -> dict:
        """Make idle cost observable: what did we spend, and on what."""
        ticks = len(self.history)
        funded_ticks = sum(1 for a in self.history if a.budgets)
        return {
            "ticks": ticks,
            "funded_ticks": funded_ticks,
            "idle_ticks": ticks - funded_ticks,
            "fallback_ticks": sum(1 for a in self.history if a.fallback),
            "total_budget_spent": round(
                sum(sum(a.budgets.values()) for a in self.history), 10
            ),
            "modules": {
                module: {
                    "total_budget": round(st.total_budget, 10),
                    "wakes": st.wake_count,
                    "shed": st.shed_count,
                    "active": st.active,
                }
                for module, st in sorted(self._state.items())
            },
        }

    def replay(self, script) -> List[Allocation]:
        """Re-run a (tick, signals) script from a clean slate.

        Same input, same output — this is the audit hook for "prove idle modules
        received zero budget", and it is why nothing here touches a real clock.
        """
        fresh = SpikeAttentionBudget(
            total_budget=self.total_budget,
            rise=self.rise,
            fall=self.fall,
            debounce_ticks=self.debounce_ticks,
            starvation_ticks=self.starvation_ticks,
            max_active=self.max_active,
            fallback_after_idle_ticks=self.fallback_after_idle_ticks,
            max_share=self.max_share,
            router=self.router,
        )
        return [fresh.step(tick, signals) for tick, signals in script]
