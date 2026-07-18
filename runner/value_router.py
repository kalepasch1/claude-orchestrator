"""Value router: routes tasks to execution queues based on estimated value/priority.

Tasks are scored and routed to high, medium, or low priority queues
for differentiated execution (e.g., faster models, more retries for high-value).
"""

import os
import re
from typing import Dict, Any, Optional, List

# Queue names — configurable via env
QUEUE_HIGH = os.environ.get("QUEUE_HIGH", "queue:high")
QUEUE_MEDIUM = os.environ.get("QUEUE_MEDIUM", "queue:medium")
QUEUE_LOW = os.environ.get("QUEUE_LOW", "queue:low")

# Thresholds — configurable via env
THRESHOLD_HIGH = float(os.environ.get("VALUE_THRESHOLD_HIGH", "70"))
THRESHOLD_LOW = float(os.environ.get("VALUE_THRESHOLD_LOW", "30"))

# Value signal keywords
_HIGH_SIGNALS = {"critical", "urgent", "revenue", "security", "production",
                 "customer-facing", "regression", "data-loss", "outage"}
_LOW_SIGNALS = {"chore", "docs", "typo", "cosmetic", "cleanup", "lint",
                "formatting", "comment", "readme"}


def estimate_value(task: Dict[str, Any]) -> float:
    """Estimate a task's value on a 0-100 scale.

    Considers: explicit priority, description keywords, estimated impact,
    and any pre-assigned score.
    """
    if not task or not isinstance(task, dict):
        return 0.0
    # Start with explicit score if present
    score = float(task.get("value_score", 50))
    description = str(task.get("description", "")).lower()
    priority = str(task.get("priority", "")).lower()
    # Priority overrides
    if priority in ("critical", "p0"):
        score = max(score, 90)
    elif priority in ("high", "p1"):
        score = max(score, 75)
    elif priority in ("low", "p3", "p4"):
        score = min(score, 35)
    # Keyword signals
    words = set(re.findall(r'[a-z]+(?:-[a-z]+)*', description))
    high_hits = words & _HIGH_SIGNALS
    low_hits = words & _LOW_SIGNALS
    score += len(high_hits) * 10
    score -= len(low_hits) * 8
    return max(0.0, min(100.0, score))


def route_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Route a task to the appropriate queue based on its estimated value.

    Returns a dict with queue name, value score, and the original task.
    """
    score = estimate_value(task)
    if score >= THRESHOLD_HIGH:
        queue = QUEUE_HIGH
    elif score <= THRESHOLD_LOW:
        queue = QUEUE_LOW
    else:
        queue = QUEUE_MEDIUM
    return {
        "queue": queue,
        "value_score": round(score, 1),
        "task": task,
    }


def route_batch(tasks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Route a batch of tasks, grouping results by queue."""
    result: Dict[str, List[Dict[str, Any]]] = {
        QUEUE_HIGH: [], QUEUE_MEDIUM: [], QUEUE_LOW: [],
    }
    for t in tasks:
        routed = route_task(t)
        result[routed["queue"]].append(routed)
    return result
