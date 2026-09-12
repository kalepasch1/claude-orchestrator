#!/usr/bin/env python3
"""bandit_selector.py — epsilon-greedy multi-armed bandit over prompt variants.

Slice 4 of the add-bandit-prompt work: the core selector with epsilon-greedy
arm selection and simple-average reward tracking. Later slices layer UCB1,
persistence, and per-context arm pools on top of this; the contract here stays
deliberately narrow so those can compose rather than rewrite.

Contract
--------
    BanditSelector(n_arms: int, epsilon: float, seed=None, alpha=None)
    .select() -> int              # always a valid index in [0, n_arms)
    .update(arm: int, reward: float) -> None

Exponential decay
-----------------
Passing ``alpha`` switches reward tracking from a simple average to an
exponentially-weighted one::

    new_avg = alpha * reward + (1 - alpha) * old_avg

The first observation for an arm seeds the average outright rather than
decaying against an unmeasured 0.0, which would otherwise drag a good arm
down for its first several pulls. ``alpha`` is a keyword arg declared AFTER
``seed`` so existing positional callers keep their binding, and it defaults
to ``None`` (simple average) so no existing caller's arm choice changes
silently. The recommended opt-in value is ``ORCH_BANDIT_DEFAULT_ALPHA``.
``counts`` and ``sums`` keep tracking raw pulls either way — a later UCB1
slice needs true pull counts.

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

#: Recommended decay factor for callers opting into exponential averaging.
#: NOT the constructor default — see the "Exponential decay" note above.
ORCH_BANDIT_DEFAULT_ALPHA = float(os.environ.get("ORCH_BANDIT_DEFAULT_ALPHA", "0.1"))


class BanditSelector:
    """Epsilon-greedy selector over a fixed number of arms.

    With probability ``epsilon`` an arm is chosen uniformly at random
    (explore); otherwise the arm with the highest average reward so far is
    chosen (exploit). Averages are maintained incrementally as sum/count, so
    memory is O(n_arms) regardless of how many updates arrive.
    """

    def __init__(
        self,
        n_arms: int,
        epsilon: float,
        seed: Optional[int] = None,
        alpha: Optional[float] = None,
    ) -> None:
        self._lock = threading.Lock()
        self.n_arms = self._coerce_n_arms(n_arms)
        self.epsilon = self._coerce_epsilon(epsilon)
        self.alpha = self._coerce_alpha(alpha)
        self._random = random.Random(seed)
        self.counts: List[int] = [0] * self.n_arms
        self.sums: List[float] = [0.0] * self.n_arms
        # Decayed averages, only consulted when self.alpha is not None.
        self.decayed: List[float] = [0.0] * self.n_arms

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

    @staticmethod
    def _coerce_alpha(alpha) -> Optional[float]:
        """None (simple average) unless a usable decay factor in (0, 1] is given.

        Garbage, NaN and alpha <= 0 all disable decay rather than freezing the
        average at its seed value, which is the failure mode a caller is least
        able to notice.
        """
        if alpha is None:
            return None
        try:
            value = float(alpha)
        except (TypeError, ValueError):
            logger.warning("BanditSelector: bad alpha %r; decay disabled", alpha)
            return None
        if value != value:  # NaN
            logger.warning("BanditSelector: NaN alpha; decay disabled")
            return None
        if value <= 0.0:
            logger.warning("BanditSelector: alpha %.3f <= 0; decay disabled", value)
            return None
        return min(value, 1.0)

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
            decayed = list(self.decayed)
            alpha = self.alpha

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
            value = decayed[arm] if alpha is not None else sums[arm] / counts[arm]
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
            # Raw counts/sums stay exact regardless of decay — a later UCB1
            # slice needs true pull counts, not decayed ones.
            first_pull = self.counts[index] == 0
            self.counts[index] += 1
            self.sums[index] += value
            if self.alpha is not None:
                if first_pull:
                    # Seed outright; decaying against an unmeasured 0.0 would
                    # penalise an arm for the accident of being new.
                    self.decayed[index] = value
                else:
                    self.decayed[index] = (
                        self.alpha * value + (1.0 - self.alpha) * self.decayed[index]
                    )

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
            if self.alpha is not None:
                return self.decayed[index]
            return self.sums[index] / self.counts[index]

    def averages(self) -> List[float]:
        with self._lock:
            if self.alpha is not None:
                return [
                    self.decayed[i] if self.counts[i] else 0.0
                    for i in range(self.n_arms)
                ]
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
            decayed = list(self.decayed)
            n_arms = self.n_arms
            epsilon = self.epsilon
            alpha = self.alpha
        if alpha is not None:
            averages = [decayed[i] if counts[i] else 0.0 for i in range(n_arms)]
        else:
            averages = [(sums[i] / counts[i]) if counts[i] else 0.0 for i in range(n_arms)]
        return {
            "n_arms": n_arms,
            "epsilon": epsilon,
            "alpha": alpha,
            "counts": counts,
            "sums": sums,
            "averages": averages,
            "total_pulls": sum(counts),
        }

    def reset(self) -> None:
        with self._lock:
            self.counts = [0] * self.n_arms
            self.sums = [0.0] * self.n_arms
            self.decayed = [0.0] * self.n_arms

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "BanditSelector(n_arms=%d, epsilon=%.3f, pulls=%d)" % (
            self.n_arms, self.epsilon, sum(self.counts)
        )
