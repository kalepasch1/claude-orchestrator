"""Value router: routes tasks to execution queues based on estimated value/priority.

Tasks are scored and routed to high, medium, or low priority queues
for differentiated execution (e.g., faster models, more retries for high-value).

THE ROUTER WAS READING FIELDS THIS FLEET DOES NOT WRITE. estimate_value() only
ever looked at `description` and `priority`. Tasks in this codebase carry
`slug`, `kind` and `prompt` — the queue table has no `description` column and
nothing sets `priority`. So every real task scored exactly the 50-point default
and landed in queue:medium, including the ones merge_train ranks by value
(merge_train.py:1283). The router looked like it was working because its unit
tests hand it synthetic `description` dicts.

Signals are now read from slug + kind + prompt as well, and `kind` carries its
own weight: a `docs` task and a `recovery` task are not the same bet regardless
of what words happen to be in the prompt. Synthetic `description`/`priority`
tasks score exactly as before.
"""

import os
import re
import threading
from typing import Dict, Any, Optional, List

# Queue names — configurable via env
QUEUE_HIGH = os.environ.get("QUEUE_HIGH", "queue:high")
QUEUE_MEDIUM = os.environ.get("QUEUE_MEDIUM", "queue:medium")
QUEUE_LOW = os.environ.get("QUEUE_LOW", "queue:low")

# Thresholds — configurable via env
THRESHOLD_HIGH = float(os.environ.get("VALUE_THRESHOLD_HIGH", "70"))
THRESHOLD_LOW = float(os.environ.get("VALUE_THRESHOLD_LOW", "30"))

# Tier names, returned alongside the queue so callers can branch on the
# decision without string-matching a configurable queue name.
TIER_HIGH, TIER_MEDIUM, TIER_LOW = "HIGH", "MEDIUM", "LOW"

# Value signal keywords
_HIGH_SIGNALS = {"critical", "urgent", "revenue", "security", "production",
                 "customer-facing", "regression", "data-loss", "outage",
                 # money and identity paths: a defect here is customer-visible
                 # by definition, whatever the prompt calls it
                 "payment", "checkout", "billing", "invoice", "subscription",
                 "credential", "auth", "login", "migration", "rollback"}
_LOW_SIGNALS = {"chore", "docs", "typo", "cosmetic", "cleanup", "lint",
                "formatting", "comment", "readme"}

# `kind` is the one field every task in this fleet actually sets, and it says
# more about risk than the prose does. Kinds absent here are worth nothing
# either way and leave the score alone.
_KIND_WEIGHTS = {
    "docs": -30, "chore": -30, "cleanup": -25, "lint": -25, "formatting": -25,
    "typo": -30, "test": -10,
    "bugfix": 10, "qafix": 10, "relfix": 10, "deployfix": 10,
    "toolchain-repair": 10, "recovery": 15,
}

_stats_lock = threading.Lock()
_stats = {"tasks_routed": 0, TIER_HIGH: 0, TIER_MEDIUM: 0, TIER_LOW: 0}


def _signal_text(task: Dict[str, Any]) -> str:
    """The text estimate_value reads signals from.

    Hyphens in a slug are separators, not word characters: the tokenizer below
    treats `update-docs-readme` as one token, so `docs` would never match. They
    are split here rather than in the pattern, which would also merge genuinely
    hyphenated signals like `customer-facing`.
    """
    parts = [
        str(task.get("description") or ""),
        str(task.get("slug") or "").replace("-", " "),
        str(task.get("prompt") or ""),
        str(task.get("kind") or ""),
    ]
    return " ".join(p for p in parts if p).lower()


def estimate_value(task: Dict[str, Any]) -> float:
    """Estimate a task's value on a 0-100 scale.

    Considers: explicit priority, `kind`, keywords across description/slug/
    prompt, and any pre-assigned score.
    """
    if not task or not isinstance(task, dict):
        return 0.0
    # Start with explicit score if present
    score = float(task.get("value_score", 50))
    description = _signal_text(task)
    priority = str(task.get("priority", "")).lower()
    score += _KIND_WEIGHTS.get(str(task.get("kind") or "").lower(), 0)
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

    Returns the queue name, the value score, the original task, and the
    routing decisions callers act on:

      tier                    HIGH / MEDIUM / LOW
      skip_integration_tests  only a LOW-tier task is cheap enough to skip them
      auto_approve            only a LOW-tier task may merge without review

    Both flags are deliberately false for MEDIUM: an unscored task defaults to
    MEDIUM, so anything else would make "we know nothing about this task" mean
    "ship it unreviewed".
    """
    score = estimate_value(task)
    if score >= THRESHOLD_HIGH:
        queue, tier = QUEUE_HIGH, TIER_HIGH
    elif score <= THRESHOLD_LOW:
        queue, tier = QUEUE_LOW, TIER_LOW
    else:
        queue, tier = QUEUE_MEDIUM, TIER_MEDIUM
    with _stats_lock:
        _stats["tasks_routed"] += 1
        _stats[tier] += 1
    return {
        "queue": queue,
        "tier": tier,
        "value_score": round(score, 1),
        "skip_integration_tests": tier == TIER_LOW,
        "auto_approve": tier == TIER_LOW,
        "task": task,
    }


def stats() -> Dict[str, int]:
    """Snapshot of routing counters since process start (or last reset)."""
    with _stats_lock:
        return dict(_stats)


def reset_stats() -> None:
    """Zero the routing counters. For tests and for periodic reporting."""
    with _stats_lock:
        for key in _stats:
            _stats[key] = 0


def route_batch(tasks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Route a batch of tasks, grouping results by queue."""
    result: Dict[str, List[Dict[str, Any]]] = {
        QUEUE_HIGH: [], QUEUE_MEDIUM: [], QUEUE_LOW: [],
    }
    for t in tasks:
        routed = route_task(t)
        result[routed["queue"]].append(routed)
    return result
