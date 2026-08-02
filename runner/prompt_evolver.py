#!/usr/bin/env python3
"""
prompt_evolver.py - UCB1 bandit over per-kind prompt templates.
Selects prompt variants and records outcomes to drive continuous improvement.
"""
import logging
import math
from runner import db

logger = logging.getLogger(__name__)

TEMPLATE_IDS = ["base", "chain_of_thought", "edit_first"]


class PromptEvolver:
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
            logger.warning("Error querying prompt_templates for kind=%s: %s", kind, e)
            return (base_prompt, "base")

        if not rows:
            return (base_prompt, "base")

        total_trials = sum(r.get("n_trials", 0) for r in rows)
        best_id = None
        best_score = -float("inf")

        for row in rows:
            template_id = row.get("template_id", "base")
            n_trials = row.get("n_trials", 0)
            total_reward = row.get("total_reward", 0.0)

            if n_trials == 0:
                score = float("inf")
            else:
                mean_reward = total_reward / n_trials
                ucb = mean_reward + math.sqrt(2 * math.log(total_trials) / n_trials)
                score = ucb

            if score > best_score:
                best_score = score
                best_id = template_id

        if best_id is None:
            return (base_prompt, "base")

        if best_id == "base":
            return (base_prompt, "base")

        return (f"[template:{best_id}]\n{base_prompt}", best_id)

    def record_outcome(self, kind: str, template_id: str, merged_first_try: bool) -> None:
        """
        Record the outcome of a prompt template application.

        Args:
            kind: The prompt kind.
            template_id: The template ID that was used.
            merged_first_try: Whether the prompt resulted in a first-try merge.
        """
        reward = 1.0 if merged_first_try else 0.0

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
            logger.warning(
                "Error recording prompt outcome for kind=%s, template_id=%s: %s",
                kind,
                template_id,
                e,
            )
