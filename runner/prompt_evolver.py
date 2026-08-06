#!/usr/bin/env python3
"""
prompt_evolver.py - UCB1 bandit over per-kind prompt templates.
Selects prompt variants and records outcomes to drive continuous improvement.
"""
import logging
import math
import threading
from runner import db

logger = logging.getLogger(__name__)

TEMPLATE_IDS = ["base", "chain_of_thought", "edit_first"]

_lock = threading.Lock()
_evolver = None
_kind_counters = {}


class _PromptEvolver:
    """UCB1 bandit for selecting and evaluating prompt templates per kind."""

    def select_template(self, kind: str, base_prompt: str) -> tuple[str, str]:
        """
        Select a prompt template for the given kind using UCB1 scoring.

        Args:
            kind: The prompt kind (e.g., "bug_fix", "refactor").
            base_prompt: The default prompt if no variants exist.

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

        # Aggregate by template_id: sum total_reward and n_trials per template
        aggregated = {}
        for row in rows:
            template_id = row.get("template_id", "base")
            if template_id not in aggregated:
                aggregated[template_id] = {"total_reward": 0.0, "n_trials": 0}
            aggregated[template_id]["total_reward"] += row.get("total_reward", 0.0)
            aggregated[template_id]["n_trials"] += row.get("n_trials", 0)

        # Compute UCB1 scores
        total_trials = sum(v["n_trials"] for v in aggregated.values())
        candidates = []
        for template_id, agg in aggregated.items():
            n_trials = agg["n_trials"]
            total_reward = agg["total_reward"]

            if n_trials == 0:
                score = float("inf")
            else:
                mean_reward = total_reward / n_trials
                ucb = mean_reward + math.sqrt(2 * math.log(total_trials) / n_trials)
                score = ucb

            candidates.append((score, template_id))

        # Sort by score (descending), then by template_id (ascending) for tie-break
        candidates.sort(key=lambda x: (-x[0], x[1]))
        best_id = candidates[0][1]

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


def select_template(kind: str, base_prompt: str) -> tuple[str, str]:
    """Returns (modified_prompt, template_id). Thread-safe."""
    with _lock:
        return _get_evolver().select_template(kind, base_prompt)


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
