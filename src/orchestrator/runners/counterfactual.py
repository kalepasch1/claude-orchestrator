"""Counterfactual replay runner for re-evaluating cached task decisions.

Provides the core re-runner function that loads cached decisions, re-executes them
with current model/policy state, and reports divergences.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Any, Optional
from src.orchestrator.runners.replay_runner import ReplayRunner, DivergenceReport
from src.orchestrator.policies import DecisionContext, DefaultPolicy


@dataclass
class ModelConfig:
    """Configuration for models used in replay."""
    model_id: str
    version: str = "1.0"

    def __post_init__(self):
        if not self.model_id:
            raise ValueError("model_id is required")


@dataclass
class DataConfig:
    """Configuration for data used in replay."""
    data_version: str = "1.0"
    context_data: Optional[Dict[str, Any]] = None


def re_run_cached_decisions(
    task_ids: List[str],
    models: ModelConfig,
    data: DataConfig,
    policies: Optional[List] = None,
) -> List[DivergenceReport]:
    """Re-run cached task decisions with current models and data.

    Loads past task decisions, re-executes them with current model/policy state,
    and compares outcomes to detect divergences.

    Args:
        task_ids: List of task IDs to replay (empty list triggers all cached records).
        models: ModelConfig specifying the model to use for replay.
        data: DataConfig specifying data version and context.
        policies: Optional list of policy objects; defaults to [DefaultPolicy()].

    Returns:
        List of DivergenceReport objects comparing original vs. new decisions.

    Raises:
        ValueError: If models is missing required model_id.
    """
    if not task_ids:
        task_ids = []

    runner = ReplayRunner(policies=policies or [DefaultPolicy()])
    runner.load_history(limit=len(task_ids) or 100)

    if not runner.records:
        return []

    filtered_records = [
        r for r in runner.records
        if not task_ids or r.task_id in task_ids
    ]

    runner.records = filtered_records
    reports = runner.run_replay()

    return reports
