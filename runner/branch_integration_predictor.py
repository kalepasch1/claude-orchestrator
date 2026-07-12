#!/usr/bin/env python3
"""
branch_integration_predictor.py — Predict optimal integration timing for branches.

Analyzes historical merge outcomes (conflicts, test failures, rebase success) to
predict the best time and order for integrating code changes. Feeds into merge_train.py
to optimize the train ordering beyond simple FIFO.

Owner module: merge_train.py, branch_materializer.py
Slice-2 of: improve-implement-dynamic-branch-management-for
"""
import os, sys, datetime, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _safe_import(mod):
    try:
        return __import__(mod)
    except Exception:
        return None

db = _safe_import("db")

# Weight factors for integration priority scoring
CONFLICT_PENALTY = float(os.environ.get("ORCH_CONFLICT_PENALTY", "0.3"))
TESTFAIL_PENALTY = float(os.environ.get("ORCH_TESTFAIL_PENALTY", "0.5"))
AGE_BONUS_PER_HOUR = float(os.environ.get("ORCH_AGE_BONUS_PER_HOUR", "0.01"))


def _task_conflict_history(project_id):
    """Get historical conflict/testfail rates per task kind.

    Returns dict: {kind: {"conflict_rate": float, "testfail_rate": float, "count": int}}
    """
    if not db:
        return {}
    try:
        tasks = db.select("tasks", {
            "select": "kind,state,note",
            "project_id": f"eq.{project_id}",
            "state": "in.(DONE,MERGED,CONFLICT,TESTFAIL,QUARANTINED)",
            "limit": "500"
        }) or []
    except Exception:
        return {}

    by_kind = {}
    for t in tasks:
        kind = t.get("kind", "unknown")
        if kind not in by_kind:
            by_kind[kind] = {"total": 0, "conflicts": 0, "testfails": 0}
        by_kind[kind]["total"] += 1
        state = t.get("state", "")
        if state == "CONFLICT":
            by_kind[kind]["conflicts"] += 1
        elif state == "TESTFAIL":
            by_kind[kind]["testfails"] += 1

    return {
        kind: {
            "conflict_rate": round(v["conflicts"] / max(v["total"], 1), 3),
            "testfail_rate": round(v["testfails"] / max(v["total"], 1), 3),
            "count": v["total"],
        }
        for kind, v in by_kind.items()
    }


def score_integration_priority(task, history=None):
    """Score a task for merge-train ordering. Higher = integrate sooner.

    Factors:
    - Low conflict/testfail history for this kind -> higher priority (safe to merge)
    - Age (older approved tasks get slight bonus to prevent starvation)
    - Task kind: docs/chore/mechanical are cheap to integrate -> bonus

    Args:
        task: dict with at least {kind, slug, created_at}
        history: optional pre-fetched history from _task_conflict_history()

    Returns: float score (higher = integrate first)
    """
    kind = task.get("kind", "unknown")
    base_score = 1.0

    # Kind bonus: safe kinds integrate first
    safe_kinds = {"docs", "chore", "lint", "format", "mechanical", "test", "cleanup"}
    if kind in safe_kinds:
        base_score += 0.5

    # History-based penalty
    if history and kind in history:
        h = history[kind]
        base_score -= h.get("conflict_rate", 0) * CONFLICT_PENALTY
        base_score -= h.get("testfail_rate", 0) * TESTFAIL_PENALTY

    # Age bonus: prevent starvation
    created = task.get("created_at")
    if created:
        try:
            if isinstance(created, str):
                created_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
            else:
                created_dt = created
            age_hours = (datetime.datetime.now(datetime.timezone.utc) - created_dt).total_seconds() / 3600
            base_score += min(age_hours * AGE_BONUS_PER_HOUR, 0.5)  # cap at 0.5
        except Exception:
            pass

    return round(base_score, 4)


def rank_for_integration(tasks, project_id=None):
    """Rank a list of tasks by integration priority (highest first).

    Args:
        tasks: list of task dicts
        project_id: optional; if provided, fetches conflict history

    Returns: sorted list of (score, task) tuples, descending by score
    """
    history = _task_conflict_history(project_id) if project_id else {}
    scored = [(score_integration_priority(t, history), t) for t in tasks]
    scored.sort(key=lambda x: -x[0])
    return scored


def stats():
    """Return predictor config."""
    return {
        "conflict_penalty": CONFLICT_PENALTY,
        "testfail_penalty": TESTFAIL_PENALTY,
        "age_bonus_per_hour": AGE_BONUS_PER_HOUR,
    }
