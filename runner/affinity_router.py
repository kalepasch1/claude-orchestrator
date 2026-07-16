"""Value-weighted affinity-aware routing.

Routes tasks based on affinity scores (model familiarity, project context)
weighted by task value to maximize throughput on high-value work.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple

log = logging.getLogger(__name__)


class AffinityScore:
    def __init__(self, runner_id: str, affinity: float, value_weight: float):
        self.runner_id = runner_id
        self.affinity = affinity
        self.value_weight = value_weight

    @property
    def weighted_score(self) -> float:
        return self.affinity * self.value_weight


def compute_affinity(runner: Dict[str, Any], task: Dict[str, Any]) -> float:
    score = 0.0
    # Project match
    if runner.get("recent_project") == task.get("project_id"):
        score += 0.4
    # Model match
    if runner.get("loaded_model") == task.get("preferred_model"):
        score += 0.3
    # Task-class experience
    runner_classes = set(runner.get("experienced_classes", []))
    if task.get("task_class") in runner_classes:
        score += 0.2
    # Recency bonus
    if runner.get("idle_seconds", 999) < 60:
        score += 0.1
    return min(score, 1.0)


def compute_value_weight(task: Dict[str, Any]) -> float:
    base = task.get("priority", 5) / 10.0
    if task.get("is_blocked_by_count", 0) > 0:
        base *= 0.5  # Blocked tasks less urgent
    if task.get("blocking_count", 0) > 0:
        base *= 1.5  # Tasks blocking others are more valuable
    return min(max(base, 0.1), 2.0)


def route_task(task: Dict[str, Any],
               runners: List[Dict[str, Any]]) -> Optional[AffinityScore]:
    if not runners:
        return None
    scores = []
    value = compute_value_weight(task)
    for r in runners:
        aff = compute_affinity(r, task)
        scores.append(AffinityScore(r["id"], aff, value))
    scores.sort(key=lambda s: s.weighted_score, reverse=True)
    return scores[0]


def route_batch(tasks: List[Dict[str, Any]],
                runners: List[Dict[str, Any]]) -> List[Tuple[Dict, Optional[AffinityScore]]]:
    # Sort tasks by value (highest first)
    valued = [(t, compute_value_weight(t)) for t in tasks]
    valued.sort(key=lambda x: x[1], reverse=True)
    results = []
    for t, _ in valued:
        assignment = route_task(t, runners)
        results.append((t, assignment))
    return results
