"""Dynamic runner assignment optimizer.

Assigns tasks to runners using completion time predictions and
dependency inference to minimize overall latency.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple

log = logging.getLogger(__name__)

# Duration thresholds for platform preference
LOCAL_THRESHOLD_SECONDS = 5.0
CLOUD_THRESHOLD_SECONDS = 30.0


class Runner:
    """Represents an available task runner."""

    def __init__(self, runner_id: str, capacity: float = 1.0,
                 platform: str = "cloud", current_tasks: Optional[List[str]] = None):
        self.runner_id = runner_id
        self.capacity = capacity
        self.platform = platform
        self.current_tasks = current_tasks or []

    @property
    def load(self) -> float:
        return len(self.current_tasks) / max(self.capacity, 0.01)


class AssignmentResult:
    """Result of a task-to-runner assignment."""

    def __init__(self, runner_id: str, confidence_score: float,
                 reason: str = ""):
        self.runner_id = runner_id
        self.confidence_score = confidence_score
        self.reason = reason


def _score_runner(task: Dict[str, Any], runner: Runner,
                  predicted_duration: float,
                  dependency_graph: Optional[Dict[str, List[str]]] = None) -> Tuple[float, str]:
    """Score a runner for a task. Lower is better."""
    # Base score: predicted_duration / capacity
    base = predicted_duration / max(runner.capacity, 0.01)

    # Load penalty
    load_penalty = runner.load * predicted_duration * 0.5

    # Platform preference
    platform_bonus = 0.0
    if predicted_duration < LOCAL_THRESHOLD_SECONDS and runner.platform == "mac":
        platform_bonus = -2.0  # Prefer local for short tasks
    elif predicted_duration > CLOUD_THRESHOLD_SECONDS and runner.platform == "cloud":
        platform_bonus = -2.0  # Prefer cloud for long tasks

    # Context-switch avoidance: if prereqs are on this runner, bonus
    context_bonus = 0.0
    if dependency_graph:
        task_type = task.get("type", "")
        prereqs = dependency_graph.get(task_type, [])
        for prereq in prereqs:
            if prereq in runner.current_tasks:
                context_bonus -= 3.0  # Strong preference for same runner
                break

    score = base + load_penalty + platform_bonus + context_bonus
    reason_parts = [f"base={base:.1f}", f"load={load_penalty:.1f}"]
    if platform_bonus: reason_parts.append(f"platform={platform_bonus:.1f}")
    if context_bonus: reason_parts.append(f"context={context_bonus:.1f}")

    return score, ", ".join(reason_parts)


def assign_task_to_runner(
    task: Dict[str, Any],
    available_runners: List[Runner],
    prediction_model: Optional[Any] = None,
    dependency_graph: Optional[Dict[str, List[str]]] = None,
) -> AssignmentResult:
    """Assign a task to the best available runner.

    Args:
        task: Task dict with at least 'type' and optionally 'predicted_duration'
        available_runners: List of Runner objects
        prediction_model: Optional model with .predict(task) -> float seconds
        dependency_graph: {task_type: [prerequisite_types]}

    Returns:
        AssignmentResult with runner_id, confidence_score, and reason
    """
    if not available_runners:
        return AssignmentResult("", 0.0, "no runners available")

    # Get predicted duration
    predicted_duration = task.get("predicted_duration", None)
    if predicted_duration is None and prediction_model is not None:
        try:
            predicted_duration = prediction_model.predict(task)
        except Exception as e:
            log.warning("Prediction failed: %s", e)
            predicted_duration = None

    # Fallback: use average duration or default
    if predicted_duration is None:
        predicted_duration = task.get("avg_duration", 15.0)

    # Score each runner
    scored = []
    for runner in available_runners:
        score, reason = _score_runner(task, runner, predicted_duration, dependency_graph)
        scored.append((score, runner, reason))

    scored.sort(key=lambda x: x[0])
    best_score, best_runner, reason = scored[0]

    # Confidence: inverse of score spread
    if len(scored) > 1:
        worst_score = scored[-1][0]
        spread = worst_score - best_score
        confidence = min(spread / max(abs(best_score), 1.0), 1.0) if spread > 0 else 0.5
    else:
        confidence = 0.5

    return AssignmentResult(best_runner.runner_id, confidence, reason)


def assign_batch(
    tasks: List[Dict[str, Any]],
    available_runners: List[Runner],
    prediction_model: Optional[Any] = None,
    dependency_graph: Optional[Dict[str, List[str]]] = None,
) -> List[AssignmentResult]:
    """Assign a batch of tasks, updating runner loads as we go."""
    results = []
    for task in tasks:
        result = assign_task_to_runner(task, available_runners, prediction_model, dependency_graph)
        # Update the runner's current tasks
        for r in available_runners:
            if r.runner_id == result.runner_id:
                r.current_tasks.append(task.get("type", "unknown"))
                break
        results.append(result)
    return results
