#!/usr/bin/env python3
"""Metabolic scheduling: hysteresis, residency, priority wake, fail-safe.

``hivemind_v15.SpikeBudget`` decides wake/sleep from a single significance
threshold against a decaying load.  That is enough to suppress noise and not
enough to schedule real work, because a bare threshold has three failure modes
that this module closes:

* **Oscillation.**  One threshold means a module sitting near it flaps awake and
  asleep on every signal.  Hysteresis gives waking and sleeping *different*
  thresholds, and minimum residency stops a state from being abandoned before
  it has been held.
* **Starvation.**  ``significance < threshold`` is applied uniformly, so
  critical work is dropped exactly like chatter.  A resting module here still
  has a **priority wake path**, and a fail-safe mode that cannot strand work
  marked critical -- if the scheduler is uncertain, it wakes.
* **Untraceable state.**  The base class mutates ``MetabolicState`` in place with
  no record of why.  Every transition here is appended to a bounded trace with
  its trigger, so "why was this module asleep" is answerable after the fact.

Resting modules genuinely receive no scheduled work: :meth:`Scheduler.dispatch`
routes to a resting module only through the priority path, and the tests assert
the scheduled path never touches one.
"""
from __future__ import annotations

import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - import shape depends on caller
    from hivemind_v15 import SpikeBudget, canonical_app
except ImportError:  # pragma: no cover
    from .hivemind_v15 import SpikeBudget, canonical_app  # type: ignore


class Phase:
    RESTING = "resting"
    WAKING = "waking"
    ACTIVE = "active"
    OVERLOADED = "overloaded"

    ALL = (RESTING, WAKING, ACTIVE, OVERLOADED)


class Priority:
    BACKGROUND = "background"
    NORMAL = "normal"
    CRITICAL = "critical"

    ALL = (BACKGROUND, NORMAL, CRITICAL)


class WorkStranded(RuntimeError):
    """Raised only if critical work could not be placed -- the fail-safe's alarm."""


@dataclass(frozen=True)
class Thresholds:
    """Separate wake and sleep thresholds: the gap IS the hysteresis band."""

    wake: float = .60
    sleep: float = .35
    min_residency_s: float = .05
    capacity_ceiling: float = 1.0
    overload_at: float = .95

    def __post_init__(self) -> None:
        if not (0.0 <= self.sleep < self.wake <= 1.0):
            raise ValueError("require 0 <= sleep < wake <= 1 so the band is non-empty")
        if self.capacity_ceiling <= 0:
            raise ValueError("capacity_ceiling must be positive")


@dataclass
class Transition:
    module: str
    frm: str
    to: str
    trigger: str
    significance: float
    at: float


@dataclass
class Module:
    name: str
    phase: str = Phase.RESTING
    load: float = 0.0
    capacity: float = 0.0
    entered_at: Optional[float] = None
    queued: int = 0
    woken_by_priority: int = 0

    def residency(self, now: float) -> float:
        """Time held in the current phase.

        ``entered_at`` is seeded from the CALLER's clock rather than
        ``time.time()``.  A scheduler that accepts an injected clock must not
        mix it with the wall clock: doing so makes residency the difference
        between two unrelated time bases, which silently blocks every
        transition (or permits every one, depending on the sign).
        """
        if self.entered_at is None:
            return float("inf")   # never placed: no residency to serve
        return now - self.entered_at


class Scheduler:
    """Metabolic scheduler with hysteresis, residency and a fail-safe wake path."""

    TRACE_LIMIT = 512

    def __init__(self, thresholds: Optional[Thresholds] = None,
                 budget: Optional[SpikeBudget] = None,
                 decay: float = .85, fail_safe: bool = True) -> None:
        self.thresholds = thresholds or Thresholds()
        self.budget = budget or SpikeBudget(threshold=self.thresholds.wake, decay=decay)
        self.decay = decay
        self.fail_safe = fail_safe
        self.modules: Dict[str, Module] = {}
        self.trace: Deque[Transition] = deque(maxlen=self.TRACE_LIMIT)
        self.metrics: Counter = Counter()
        self._lock = threading.RLock()

    # -- state -----------------------------------------------------------
    def module(self, name: str) -> Module:
        name = canonical_app(name)
        with self._lock:
            m = self.modules.get(name)
            if m is None:
                m = Module(name=name)
                self.modules[name] = m
            return m

    def _transition(self, m: Module, to: str, trigger: str, significance: float,
                    now: float) -> bool:
        if m.phase == to:
            return False
        if m.residency(now) < self.thresholds.min_residency_s and trigger != "priority_wake":
            self.metrics["residency_blocked"] += 1
            return False
        self.trace.append(Transition(m.name, m.phase, to, trigger, significance, now))
        m.phase = to
        m.entered_at = now
        self.metrics[f"to_{to}"] += 1
        return True

    # -- signal ----------------------------------------------------------
    def signal(self, module: str, significance: float, demand: float = 1.0,
               now: Optional[float] = None) -> float:
        """Update load and phase under hysteresis; return the granted budget."""
        now = now if now is not None else time.time()
        m = self.module(module)
        with self._lock:
            m.load = self.decay * m.load + (1 - self.decay) * max(0.0, demand)

            if significance >= self.thresholds.wake:
                self._transition(m, Phase.ACTIVE, "significance_above_wake", significance, now)
            elif significance <= self.thresholds.sleep:
                self._transition(m, Phase.RESTING, "significance_below_sleep", significance, now)
            else:
                # Inside the hysteresis band: hold the current phase.  This is
                # the anti-oscillation property -- a module near the boundary
                # must not flap on every signal.
                self.metrics["held_in_band"] += 1

            if m.phase == Phase.RESTING:
                m.capacity = 0.0
                return 0.0

            m.capacity = min(self.thresholds.capacity_ceiling, max(.1, m.load))
            if m.load >= self.thresholds.overload_at:
                self._transition(m, Phase.OVERLOADED, "load_above_overload", significance, now)
            granted = min(self.thresholds.capacity_ceiling, significance * m.capacity)
            return granted

    # -- dispatch --------------------------------------------------------
    def dispatch(self, module: str, work: Callable[[], Any], priority: str = Priority.NORMAL,
                 now: Optional[float] = None) -> Tuple[bool, Optional[Any]]:
        """Route work.  A resting module is reachable ONLY by the priority path."""
        if priority not in Priority.ALL:
            raise ValueError(f"unknown priority {priority!r}")
        now = now if now is not None else time.time()
        m = self.module(module)
        with self._lock:
            resting = m.phase == Phase.RESTING
            overloaded = m.phase == Phase.OVERLOADED

            if resting and priority == Priority.CRITICAL:
                # Priority wake bypasses residency: critical work is never
                # stranded behind a timer.
                self._transition(m, Phase.WAKING, "priority_wake", 1.0, now)
                m.woken_by_priority += 1
                m.capacity = max(m.capacity, .1)
                self.metrics["priority_wakes"] += 1
            elif resting:
                m.queued += 1
                self.metrics["deferred_while_resting"] += 1
                return False, None
            elif overloaded and priority == Priority.BACKGROUND:
                m.queued += 1
                self.metrics["shed_background"] += 1
                return False, None

        self.metrics["dispatched"] += 1
        return True, work()

    def dispatch_or_fail_safe(self, module: str, work: Callable[[], Any],
                              priority: str = Priority.NORMAL,
                              now: Optional[float] = None) -> Any:
        """Fail-safe: critical work runs even if the scheduler cannot place it.

        A scheduler that is uncertain must wake, not drop.  If placement fails
        for critical work and fail-safe is disabled, the caller gets a loud
        ``WorkStranded`` rather than silence.
        """
        placed, result = self.dispatch(module, work, priority, now)
        if placed:
            return result
        if priority != Priority.CRITICAL:
            return None
        if not self.fail_safe:
            raise WorkStranded(f"critical work for {module} could not be placed")
        self.metrics["fail_safe_runs"] += 1
        return work()

    # -- maintenance -----------------------------------------------------
    def rest_idle(self, idle_seconds: float = 60.0, now: Optional[float] = None) -> int:
        """Put long-quiet modules to sleep, respecting minimum residency."""
        now = now if now is not None else time.time()
        rested = 0
        with self._lock:
            for m in self.modules.values():
                if m.phase == Phase.RESTING:
                    continue
                if m.residency(now) >= max(idle_seconds, self.thresholds.min_residency_s):
                    if self._transition(m, Phase.RESTING, "idle_timeout", 0.0, now):
                        m.capacity = 0.0
                        rested += 1
        return rested

    def transitions_for(self, module: str) -> List[Transition]:
        name = canonical_app(module)
        return [t for t in self.trace if t.module == name]

    def energy_report(self) -> Dict[str, Any]:
        """Compute proxy: granted capacity is the only thing that costs anything.

        This is a PROXY, not joules.  It counts capacity actually granted versus
        capacity that would have been granted if every module were always awake
        at the ceiling, and says so.
        """
        with self._lock:
            modules = list(self.modules.values())
        active = [m for m in modules if m.phase != Phase.RESTING]
        granted = sum(m.capacity for m in modules)
        always_on = len(modules) * self.thresholds.capacity_ceiling
        return {
            "modules": len(modules),
            "active": len(active),
            "resting": len(modules) - len(active),
            "granted_capacity": granted,
            "always_on_capacity": always_on,
            "fraction_of_always_on": (granted / always_on) if always_on else 0.0,
            "priority_wakes": self.metrics["priority_wakes"],
            "deferred_while_resting": self.metrics["deferred_while_resting"],
            "note": "capacity proxy, not measured energy; a resting module grants 0",
        }
