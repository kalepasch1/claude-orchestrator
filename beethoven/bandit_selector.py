#!/usr/bin/env python3
"""bandit_selector.py — epsilon-greedy multi-armed bandit over prompt variants.

Slice 4 of the add-bandit-prompt work: the core selector with epsilon-greedy
arm selection and simple-average reward tracking. Later slices layer UCB1,
persistence, and per-context arm pools on top of this; the contract here stays
deliberately narrow so those can compose rather than rewrite.

Contract
--------
    BanditSelector(n_arms: int, epsilon: float)
    .select() -> int              # always a valid index in [0, n_arms)
    .update(arm: int, reward: float) -> None

Conventions (CLAUDE.md)
-----------------------
  * fail-soft — bad input never raises; it is clamped or ignored with a
    diagnostic, so a mis-wired caller cannot wedge the runner;
  * thread-safe with an explicit lock, critical sections kept minimal;
  * every tunable is an ``ORCH_``-prefixed env var with a sensible default;
  * seedable RNG so a bandit run is reproducible in tests.
"""
from __future__ import annotations

import logging
import os
import random
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

#: Default exploration probability when a caller passes something unusable.
ORCH_BANDIT_DEFAULT_EPSILON = float(os.environ.get("ORCH_BANDIT_DEFAULT_EPSILON", "0.1"))

#: Upper bound on arms. A pathological n_arms is clamped rather than allocated.
ORCH_BANDIT_MAX_ARMS = int(os.environ.get("ORCH_BANDIT_MAX_ARMS", "1024"))


class BanditSelector:
    """Epsilon-greedy selector over a fixed number of arms.

    With probability ``epsilon`` an arm is chosen uniformly at random
    (explore); otherwise the arm with the highest average reward so far is
    chosen (exploit). Averages are maintained incrementally as sum/count, so
    memory is O(n_arms) regardless of how many updates arrive.
    """

    def __init__(self, n_arms: int, epsilon: float, seed: Optional[int] = None) -> None:
        self._lock = threading.Lock()
        self.n_arms = self._coerce_n_arms(n_arms)
        self.epsilon = self._coerce_epsilon(epsilon)
        self._random = random.Random(seed)
        self.counts: List[int] = [0] * self.n_arms
        self.sums: List[float] = [0.0] * self.n_arms

    # -- input coercion (fail-soft) -----------------------------------------

    @staticmethod
    def _coerce_n_arms(n_arms) -> int:
        try:
            value = int(n_arms)
        except (TypeError, ValueError):
            logger.warning("BanditSelector: bad n_arms %r -> 1", n_arms)
            return 1
        if value < 1:
            logger.warning("BanditSelector: n_arms %d < 1 -> 1", value)
            return 1
        if value > ORCH_BANDIT_MAX_ARMS:
            logger.warning("BanditSelector: n_arms %d clamped to %d", value, ORCH_BANDIT_MAX_ARMS)
            return ORCH_BANDIT_MAX_ARMS
        return value

    @staticmethod
    def _coerce_epsilon(epsilon) -> float:
        try:
            value = float(epsilon)
        except (TypeError, ValueError):
            logger.warning("BanditSelector: bad epsilon %r -> %.3f", epsilon,
                           ORCH_BANDIT_DEFAULT_EPSILON)
            return ORCH_BANDIT_DEFAULT_EPSILON
        if value != value:  # NaN
            return ORCH_BANDIT_DEFAULT_EPSILON
        return min(max(value, 0.0), 1.0)

    # -- core API -----------------------------------------------------------

    def select(self) -> int:
        """Return an arm index in ``[0, n_arms)``. Never raises.

        Explores with probability ``epsilon``; otherwise exploits the highest
        average reward. Untried arms are exploited first (their average is
        treated as ``+inf``) so every arm gets at least one observation before
        the greedy branch can lock onto an early winner.
        """
        with self._lock:
            n_arms = self.n_arms
            epsilon = self.epsilon
            counts = list(self.counts)
            sums = list(self.sums)

        if n_arms == 1:
            return 0
        if self._random.random() < epsilon:
            return self._random.randrange(n_arms)

        untried = [i for i in range(n_arms) if counts[i] == 0]
        if untried:
            return self._random.choice(untried)

        best_value = None
        best_arms: List[int] = []
        for arm in range(n_arms):
            value = sums[arm] / counts[arm]
            if best_value is None or value > best_value:
                best_value = value
                best_arms = [arm]
            elif value == best_value:
                best_arms.append(arm)
        # Random tiebreak keeps a cold start from always favouring arm 0.
        return self._random.choice(best_arms)

    def update(self, arm: int, reward: float) -> None:
        """Record `reward` for `arm`. Bad input is ignored, never raised."""
        try:
            index = int(arm)
        except (TypeError, ValueError):
            logger.warning("BanditSelector.update: bad arm %r; ignored", arm)
            return
        try:
            value = float(reward)
        except (TypeError, ValueError):
            logger.warning("BanditSelector.update: bad reward %r; ignored", reward)
            return
        if value != value:  # NaN would poison the running average
            logger.warning("BanditSelector.update: NaN reward; ignored")
            return

        with self._lock:
            if not 0 <= index < self.n_arms:
                logger.warning("BanditSelector.update: arm %d out of range; ignored", index)
                return
            self.counts[index] += 1
            self.sums[index] += value

    # -- observability ------------------------------------------------------

    def average(self, arm: int) -> float:
        """Average reward for `arm`; 0.0 when untried or out of range."""
        try:
            index = int(arm)
        except (TypeError, ValueError):
            return 0.0
        with self._lock:
            if not 0 <= index < self.n_arms or self.counts[index] == 0:
                return 0.0
            return self.sums[index] / self.counts[index]

    def averages(self) -> List[float]:
        with self._lock:
            return [
                (self.sums[i] / self.counts[i]) if self.counts[i] else 0.0
                for i in range(self.n_arms)
            ]

    def best_arm(self) -> int:
        """Index of the highest-average arm; 0 when nothing has been tried."""
        averages = self.averages()
        if not averages:
            return 0
        return max(range(len(averages)), key=lambda i: averages[i])

    def stats(self) -> Dict[str, object]:
        with self._lock:
            counts = list(self.counts)
            sums = list(self.sums)
            n_arms = self.n_arms
            epsilon = self.epsilon
        return {
            "n_arms": n_arms,
            "epsilon": epsilon,
            "counts": counts,
            "sums": sums,
            "averages": [(sums[i] / counts[i]) if counts[i] else 0.0 for i in range(n_arms)],
            "total_pulls": sum(counts),
        }

    def reset(self) -> None:
        with self._lock:
            self.counts = [0] * self.n_arms
            self.sums = [0.0] * self.n_arms

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "BanditSelector(n_arms=%d, epsilon=%.3f, pulls=%d)" % (
            self.n_arms, self.epsilon, sum(self.counts)
        )
