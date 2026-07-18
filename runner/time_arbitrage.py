"""Time-of-day arbitrage for task scheduling.

Determines optimal execution windows based on time-of-day patterns
for API costs, model availability, and queue depth.
"""

import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple


# Cost multipliers by hour (UTC). Lower = cheaper.
# Models typical API pricing: cheaper off-peak (US nights = UTC 06-14)
_DEFAULT_COST_CURVE = {
    h: 0.7 if 6 <= h <= 13 else (0.85 if 14 <= h <= 17 else 1.0)
    for h in range(24)
}

# Queue depth patterns (relative, 0-1). Lower = less contention.
_DEFAULT_QUEUE_CURVE = {
    h: 0.3 if 6 <= h <= 11 else (0.6 if 12 <= h <= 17 else (0.9 if 18 <= h <= 23 else 0.5))
    for h in range(24)
}

# Model availability patterns (0-1, higher = more available)
_DEFAULT_AVAILABILITY_CURVE = {
    h: 0.95 if 4 <= h <= 14 else (0.8 if 15 <= h <= 20 else 0.7)
    for h in range(24)
}


def get_window_score(hour_utc: int,
                     cost_weight: float = 0.4,
                     queue_weight: float = 0.3,
                     avail_weight: float = 0.3) -> float:
    """Score an hour for task execution (higher = better window).

    Combines cost savings, queue depth, and model availability.
    Returns 0.0-1.0.
    """
    hour_utc = int(hour_utc) % 24
    cost = 1.0 - _DEFAULT_COST_CURVE.get(hour_utc, 1.0)
    queue = 1.0 - _DEFAULT_QUEUE_CURVE.get(hour_utc, 1.0)
    avail = _DEFAULT_AVAILABILITY_CURVE.get(hour_utc, 0.7)
    score = cost * cost_weight + queue * queue_weight + avail * avail_weight
    return round(max(0.0, min(1.0, score)), 3)


def best_windows(top_n: int = 3) -> List[Dict[str, Any]]:
    """Return the top N best execution windows (UTC hours)."""
    scored = []
    for h in range(24):
        scored.append({"hour_utc": h, "score": get_window_score(h)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def should_defer(current_utc: Optional[datetime] = None,
                 threshold: float = 0.5) -> Dict[str, Any]:
    """Decide whether to execute now or defer to a better window.

    Returns dict with execute_now (bool), current_score, and
    best_window suggestion if deferring.
    """
    if current_utc is None:
        current_utc = datetime.now(timezone.utc)
    hour = current_utc.hour
    current_score = get_window_score(hour)
    best = best_windows(1)[0]
    return {
        "execute_now": current_score >= threshold,
        "current_hour_utc": hour,
        "current_score": current_score,
        "best_hour_utc": best["hour_utc"],
        "best_score": best["score"],
    }


def optimal_schedule(tasks: List[Dict[str, Any]],
                     available_hours: Optional[List[int]] = None
                     ) -> List[Dict[str, Any]]:
    """Assign tasks to optimal hours based on scoring.

    Args:
        tasks: list of task dicts (must have 'id').
        available_hours: subset of hours to consider (default: all 24).

    Returns:
        List of {task_id, assigned_hour_utc, score}.
    """
    if not tasks:
        return []
    hours = available_hours if available_hours else list(range(24))
    hour_scores = [(h, get_window_score(h)) for h in hours]
    hour_scores.sort(key=lambda x: x[1], reverse=True)
    assignments = []
    for i, task in enumerate(tasks):
        h, s = hour_scores[i % len(hour_scores)]
        assignments.append({
            "task_id": task.get("id", i),
            "assigned_hour_utc": h,
            "score": s,
        })
    return assignments
