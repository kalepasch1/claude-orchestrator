#!/usr/bin/env python3
"""
prompt_evolver.py - UCB1 bandit over per-kind prompt templates.
Selects prompt variants and records outcomes to drive continuous improvement.
"""
import logging
import math
import os
import random
import threading
from runner import db

logger = logging.getLogger(__name__)

TEMPLATE_IDS = ["base", "chain_of_thought", "edit_first"]

# Arm-selection strategy. ORCH_-prefixed so it is fleet-pushable via
# fleet_control.py without a deploy. Defaults to "ucb1" -- the strategy this
# module has always used -- so existing behavior is preserved unless an
# operator opts in.
BANDIT_STRATEGY = os.environ.get("ORCH_PROMPT_BANDIT_STRATEGY", "ucb1").strip().lower()

# Exploration rate for the epsilon_greedy strategy.
BANDIT_EPSILON = float(os.environ.get("ORCH_PROMPT_BANDIT_EPSILON", "0.1"))

_lock = threading.Lock()
_evolver = None
_kind_counters = {}


def _acceptance(agg):
    """Historical acceptance rate for one arm; 0.0 when never tried."""
    n = agg.get("n_trials") or 0
    if n <= 0:
        return 0.0
    return (agg.get("total_reward") or 0.0) / n


def select_arm(aggregated, strategy=None, rng=None):
    """Pick a template_id from ``{template_id: {total_reward, n_trials}}``.

    Strategies:
      ``ucb1``            mean reward + sqrt(2 ln N / n); untried arms score +inf.
      ``thompson``        sample Beta(1+successes, 1+failures) per arm, take the max.
      ``epsilon_greedy``  explore uniformly with probability BANDIT_EPSILON,
                          otherwise take the highest acceptance rate.

    ``rng`` is injectable (seedable RNG convention) so the stochastic strategies
    are testable. Fail-soft: an unknown strategy or empty input falls back to
    ucb1 / "base" rather than raising.
    """
    if not aggregated:
        return "base"
    strategy = (strategy or BANDIT_STRATEGY or "ucb1").strip().lower()
    rng = rng or random

    if strategy == "epsilon_greedy":
        arms = sorted(aggregated)
        try:
            if rng.random() < BANDIT_EPSILON:
                return rng.choice(arms)
        except Exception as exc:
            logger.warning("epsilon_greedy draw failed (%s); using greedy arm", exc)
        return sorted(arms, key=lambda t: (-_acceptance(aggregated[t]), t))[0]

    if strategy == "thompson":
        scored = []
        for template_id in sorted(aggregated):
            agg = aggregated[template_id]
            n = max(agg.get("n_trials") or 0, 0)
            successes = max(agg.get("total_reward") or 0.0, 0.0)
            failures = max(n - successes, 0.0)
            try:
                draw = rng.betavariate(1.0 + successes, 1.0 + failures)
            except Exception as exc:
                logger.warning(
                    "thompson draw failed for %s (%s); using acceptance rate",
                    template_id, exc,
                )
                draw = _acceptance(agg)
            scored.append((draw, template_id))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][1]

    if strategy != "ucb1":
        logger.warning("unknown prompt bandit strategy %r; falling back to ucb1", strategy)

    total_trials = sum(v.get("n_trials") or 0 for v in aggregated.values())
    candidates = []
    for template_id, agg in aggregated.items():
        n_trials = agg.get("n_trials") or 0
        if n_trials == 0:
            score = float("inf")
        else:
            mean_reward = (agg.get("total_reward") or 0.0) / n_trials
            score = mean_reward + math.sqrt(2 * math.log(max(total_trials, 1)) / n_trials)
        candidates.append((score, template_id))
    candidates.sort(key=lambda x: (-x[0], x[1]))
    return candidates[0][1]


class _PromptEvolver:
    """UCB1 bandit for selecting and evaluating prompt templates per kind."""

    def select_template(self, kind: str, base_prompt: str, strategy: str = None) -> tuple[str, str]:
        """
        Select a prompt template for the given kind using bandit scoring.

        Args:
            kind: The prompt kind (e.g., "bug_fix", "refactor").
            base_prompt: The default prompt if no variants exist.
            strategy: Arm-selection strategy; defaults to BANDIT_STRATEGY
                ("ucb1"). See select_arm for the supported values.

        Returns:
            (modified_prompt, template_id) where modified_prompt has a variant tag
            prepended if template_id != "base".
        """
        try:
            rows = db.select("prompt_templates", {"kind": f"eq.{kind}"}) or []
        except Exception as e:
            logger.warning(f"select_template failed for kind={kind!r}: {e}")
            return (base_prompt, "base")

        if not rows:
            # Cold-start: return next template from round-robin
            if kind not in _kind_counters:
                _kind_counters[kind] = 0
            idx = _kind_counters[kind] % len(TEMPLATE_IDS)
            _kind_counters[kind] += 1
            template_id = TEMPLATE_IDS[idx]
            if template_id == "base":
                return (base_prompt, "base")
            else:
                return (f"[template:{template_id}]\n{base_prompt}", template_id)

        # Aggregate by template_id: sum total_reward and n_trials per template.
        #
        # CORRECTED 2026-08-12. This used to seed every id in TEMPLATE_IDS at
        # n_trials=0 before aggregating, reasoning that UCB1 needs every arm
        # reachable. The reasoning is sound for a bandit that OWNS its arm set;
        # it is wrong here, and it broke the module in practice.
        #
        # A seeded arm has n_trials == 0, which scores +inf, which outranks
        # every arm that has real history — permanently, because a seeded arm
        # is never written to the database by select_template (the spec is
        # explicit that TEMPLATE_IDS "are not auto-inserted"). So the +inf arm
        # was re-selected on every call and the recorded rewards were never
        # able to influence anything: a bandit that cannot exploit is not a
        # bandit. Measured: 12 of 43 tests failed, all of them cases where a
        # template with real trials lost to an untried constant.
        #
        # Arms enter through record_outcome, which is what actually creates the
        # row. Cold start is already handled above by the round-robin over
        # TEMPLATE_IDS when the kind has no rows at all, so exploration still
        # happens — through the path designed for it, not by making the score
        # function unable to converge.
        aggregated = {}
        for row in rows:
            template_id = row.get("template_id", "base")
            if template_id not in aggregated:
                aggregated[template_id] = {"total_reward": 0.0, "n_trials": 0}
            # `or 0` also absorbs SQL NULLs, which .get()'s default does not.
            aggregated[template_id]["total_reward"] += row.get("total_reward") or 0.0
            aggregated[template_id]["n_trials"] += row.get("n_trials") or 0

        # Delegate arm selection so the strategy is swappable (ucb1 / thompson /
        # epsilon_greedy) without changing the DB-aggregation above.
        best_id = select_arm(aggregated, strategy=strategy)

        if best_id == "base":
            return (base_prompt, "base")
        else:
            return (f"[template:{best_id}]\n{base_prompt}", best_id)

    def record_outcome(self, kind: str, template_id: str, merged_first_try: bool = False,
                       deployed_verified: bool = False, artifact_commit: str = "") -> None:
        """
        Record the outcome of a prompt template application.

        REWARD HYGIENE (2026-08-04): the UCB1 reward used to be merged_first_try alone.
        With ~96% of MERGED rows later found to be phantoms, the bandit was optimizing
        state-flipping, not delivery. Full reward now requires DEPLOYED_AND_VERIFIED;
        a first-try merge backed by a real artifact_commit earns partial credit (0.5);
        a bare merge claim earns nothing.

        Args:
            kind: The prompt kind.
            template_id: The template ID that was used.
            merged_first_try: Whether the prompt resulted in a first-try merge.
            deployed_verified: Whether the task reached DEPLOYED_AND_VERIFIED.
            artifact_commit: The task's evidence sha ('' when absent).
        """
        if deployed_verified:
            reward = 1.0
        elif merged_first_try and artifact_commit:
            reward = 0.5
        else:
            reward = 0.0

        try:
            db.insert(
                "prompt_templates",
                {
                    "kind": kind,
                    "template_id": template_id,
                    "total_reward": reward,
                    "n_trials": 1,
                },
                resolution="merge-duplicates",
            )
        except Exception as e:
            logger.warning(f"Failed to record outcome: {e}")

    def stats(self) -> dict:
        """Return {"total_trials": int, "kinds": {...}} for monitoring."""
        try:
            rows = db.select("prompt_templates") or []
            total_trials = sum(r.get("n_trials", 0) for r in rows)

            kinds = {}
            for row in rows:
                kind = row.get("kind", "unknown")
                if kind not in kinds:
                    kinds[kind] = 0
                kinds[kind] += row.get("n_trials", 0)

            return {"total_trials": total_trials, "kinds": kinds}
        except Exception as e:
            logger.warning(f"Error in stats(): {e}")
            return {"total_trials": 0, "kinds": {}}


def _get_evolver() -> _PromptEvolver:
    global _evolver
    if _evolver is None:
        _evolver = _PromptEvolver()
    return _evolver


def select_template(kind: str, base_prompt: str, strategy: str = None) -> tuple[str, str]:
    """Returns (modified_prompt, template_id). Thread-safe."""
    with _lock:
        return _get_evolver().select_template(kind, base_prompt, strategy=strategy)


def record_outcome(kind: str, template_id: str, merged_first_try: bool = False,
                   deployed_verified: bool = False, artifact_commit: str = "") -> None:
    """Record trial outcome. Thread-safe, swallows all exceptions.
    Full reward requires deployed_verified; merged_first_try + artifact_commit = 0.5."""
    with _lock:
        _get_evolver().record_outcome(kind, template_id, merged_first_try,
                                      deployed_verified=deployed_verified,
                                      artifact_commit=artifact_commit)


def stats() -> dict:
    """Return {"total_trials": int, "kinds": {...}} for monitoring."""
    with _lock:
        return _get_evolver().stats()


def invalidate() -> None:
    """Clear singleton for testing."""
    global _evolver, _kind_counters
    _evolver = None
    _kind_counters = {}


# For backward compatibility: expose PromptEvolver as an alias
PromptEvolver = _PromptEvolver
