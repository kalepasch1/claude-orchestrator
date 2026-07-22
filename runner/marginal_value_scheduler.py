#!/usr/bin/env python3
"""
marginal_value_scheduler.py — priority/duration-based task ranking.

Calculates the marginal value of each task based on its priority weight and
estimated duration.  Higher priority and shorter duration yield higher marginal
value, so the swarm picks impactful quick wins first.

Functions:
    calculate_marginal_value(task)  — value = priority_weight / max(duration, 1)
    rank_tasks(tasks)              — sort by marginal value descending
    select_next_batch(tasks, n)    — top-N tasks for next execution
    stats()                        — module statistics

Feature flag: ORCH_MARGINAL_VALUE_ENABLED (default "true")
"""
import os, sys, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("ORCH_MARGINAL_VALUE_ENABLED", "true").lower() in ("true", "1", "yes")

# Priority weight mapping — lower numeric priority = higher urgency = higher weight.
# Mirrors priority_scorer.py where priority 1 is most urgent.
PRIORITY_WEIGHTS = {
    "critical": 100,
    "high": 75,
    "medium": 50,
    "low": 25,
}
DEFAULT_PRIORITY_WEIGHT = 50

_lock = threading.Lock()
_stats = {
    "tasks_scored": 0,
    "tasks_ranked": 0,
    "batches_selected": 0,
}


def _priority_weight(task):
    """Extract a numeric priority weight from a task dict.

    Checks for an explicit 'priority_weight' field first, then maps
    string 'priority' labels, then treats numeric 'priority' as an
    inverse score (lower number = higher weight).
    """
    pw = task.get("priority_weight")
    if pw is not None:
        try:
            return float(pw)
        except (TypeError, ValueError):
            pass
    pri = task.get("priority")
    if isinstance(pri, str):
        return float(PRIORITY_WEIGHTS.get(pri.lower(), DEFAULT_PRIORITY_WEIGHT))
    if pri is not None:
        try:
            # Numeric priority: lower = more urgent, invert to weight.
            # priority 1 → weight 100, priority 1000 → weight 0.1
            p = float(pri)
            return max(100.0 / max(p, 1), 0.1)
        except (TypeError, ValueError):
            pass
    return float(DEFAULT_PRIORITY_WEIGHT)


def _duration_estimate(task):
    """Extract duration estimate from a task, defaulting to 1."""
    d = task.get("duration_estimate")
    if d is None:
        d = task.get("duration")
    if d is None:
        return 1.0
    try:
        return float(d)
    except (TypeError, ValueError):
        return 1.0


def calculate_marginal_value(task):
    """Compute marginal value = priority_weight / max(duration_estimate, 1).

    Higher priority and shorter duration produce a higher value.
    Returns 0.0 when the feature flag is disabled.
    """
    if not ENABLED:
        return 0.0
    weight = _priority_weight(task)
    duration = max(_duration_estimate(task), 1)
    value = weight / duration
    with _lock:
        _stats["tasks_scored"] += 1
    return value


def rank_tasks(tasks):
    """Sort tasks by marginal value descending.

    Returns a list of dicts, each containing the original task under 'task'
    and its computed 'marginal_value'.  Empty input returns [].
    """
    if not tasks:
        return []
    ranked = []
    for t in tasks:
        mv = calculate_marginal_value(t)
        ranked.append({"task": t, "marginal_value": mv})
    ranked.sort(key=lambda r: r["marginal_value"], reverse=True)
    with _lock:
        _stats["tasks_ranked"] += len(ranked)
    return ranked


def select_next_batch(tasks, batch_size=5):
    """Select the top N tasks by marginal value for next execution.

    Returns a list of ranked-task dicts (same shape as rank_tasks output),
    capped at batch_size.  Gracefully handles empty/None input.
    """
    if not tasks:
        return []
    ranked = rank_tasks(tasks)
    batch = ranked[:batch_size]
    with _lock:
        _stats["batches_selected"] += 1
    return batch


def stats() -> dict:
    """Return module statistics (thread-safe snapshot)."""
    with _lock:
        return dict(_stats)
