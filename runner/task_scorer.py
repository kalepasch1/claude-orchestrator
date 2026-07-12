#!/usr/bin/env python3
"""
task_scorer.py - Priority scoring for task queue processing.

Assigns a numeric score based on kind (bugfix, feature, etc.) and age,
so critical issues are resolved faster. Higher score = higher priority.

Usage:
    import task_scorer
    scored = task_scorer.score_tasks(tasks)
    score  = task_scorer.score_one(task)

Env:
    ORCH_SCORER_ENABLED       (default "true")
    ORCH_SCORER_AGE_WEIGHT    (default "0.5") — points per hour of age
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ENABLED = os.environ.get("ORCH_SCORER_ENABLED", "true").lower() in ("true", "1")
_AGE_WEIGHT = float(os.environ.get("ORCH_SCORER_AGE_WEIGHT", "0.5"))

_DEFAULT_KIND_WEIGHTS = {
    "bugfix": 100, "hotfix": 120, "security": 110,
    "test": 60, "mechanical": 50, "chore": 40,
    "cleanup": 35, "docs": 20, "refactor": 45,
    "feature": 30, "build": 25, "speculative": 10,
}

try:
    _kind_weights = json.loads(os.environ.get("ORCH_SCORER_KIND_WEIGHTS", "{}"))
except Exception:
    _kind_weights = {}
_KIND_W = {**_DEFAULT_KIND_WEIGHTS, **_kind_weights}


def _parse_created_at(task: dict) -> float:
    """Extract creation timestamp from task. Fail-soft returns 0."""
    try:
        ca = task.get("created_at", "")
        if not ca:
            return 0.0
        if isinstance(ca, (int, float)):
            return float(ca)
        from datetime import datetime
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f+00:00", "%Y-%m-%dT%H:%M:%S+00:00",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ca[:26], fmt).timestamp()
            except ValueError:
                continue
        return 0.0
    except Exception:
        return 0.0


def score_one(task: dict) -> float:
    """Compute priority score for a single task. Higher = more urgent."""
    if not _ENABLED:
        return 0.0
    try:
        kind = (task.get("kind") or "build").lower()
        kind_score = _KIND_W.get(kind, 25)
        created = _parse_created_at(task)
        age_hours = (time.time() - created) / 3600 if created > 0 else 0
        age_score = age_hours * _AGE_WEIGHT
        attempt = int(task.get("attempt") or 0)
        retry_penalty = max(0, 10 - attempt * 3)
        return kind_score + age_score + retry_penalty
    except Exception:
        return 0.0


def score_tasks(tasks: list) -> list:
    """Score and sort tasks by priority (highest first).
    Each task dict gets a '_score' key added. Fail-soft."""
    if not _ENABLED or not tasks:
        return tasks
    try:
        for t in tasks:
            t["_score"] = score_one(t)
        return sorted(tasks, key=lambda t: t.get("_score", 0), reverse=True)
    except Exception:
        return tasks


def stats() -> dict:
    """Return scorer config."""
    return {"enabled": _ENABLED, "age_weight": _AGE_WEIGHT,
            "kind_weights": _KIND_W}
