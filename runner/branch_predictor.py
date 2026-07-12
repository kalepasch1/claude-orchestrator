#!/usr/bin/env python3
"""
branch_predictor.py - predict missing branches before merge cycles.

Uses historical branch-creation failure data to identify projects and task
patterns where missing branches have caused issues. Preemptively flags tasks
that are likely to hit the "missing branch" failure mode so the runner can
request branch creation before execution starts.

Fail-soft: returns empty predictions on any error, never raises.
Env: ORCH_BRANCH_PREDICTOR_ENABLED (default "true").
"""
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import log as _log_mod

_log = _log_mod.get("branch_predictor")
_ENABLED = os.environ.get("ORCH_BRANCH_PREDICTOR_ENABLED", "true").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Historical failure tracking (thread-safe singleton)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_failure_history = {}  # {project_id: {"total_tasks": int, "missing_branch_failures": int, "slugs": set}}
_DECAY_FACTOR = float(os.environ.get("ORCH_BRANCH_DECAY", "0.95"))
_THRESHOLD = float(os.environ.get("ORCH_BRANCH_PREDICT_THRESHOLD", "0.15"))


def record_branch_outcome(project_id, slug, had_missing_branch):
    """Record whether a task hit a missing-branch failure."""
    try:
        with _lock:
            entry = _failure_history.setdefault(project_id, {
                "total_tasks": 0, "missing_branch_failures": 0, "slugs": set(),
            })
            entry["total_tasks"] += 1
            if had_missing_branch:
                entry["missing_branch_failures"] += 1
                entry["slugs"].add(slug)
    except Exception as exc:
        _log.debug("record_branch_outcome error: %s", exc)


def _failure_rate(project_id):
    """Compute missing-branch failure rate for a project."""
    with _lock:
        entry = _failure_history.get(project_id)
        if not entry or entry["total_tasks"] == 0:
            return 0.0
        return entry["missing_branch_failures"] / entry["total_tasks"]


def predict_missing_branch(task):
    """Predict whether a task is likely to hit a missing-branch error.

    Returns dict with 'risk_score' (0.0-1.0) and 'should_precreate' bool.
    """
    if not _ENABLED:
        return {"risk_score": 0.0, "should_precreate": False, "reason": "disabled"}

    try:
        pid = task.get("project_id", "")
        slug = task.get("slug", "")
        base_rate = _failure_rate(pid)

        # Boost score for tasks whose slugs match known failure patterns
        slug_boost = 0.0
        with _lock:
            entry = _failure_history.get(pid, {})
            known_slugs = entry.get("slugs", set())
        # Check if any prefix of the slug matches a known failure slug prefix
        slug_prefix = re.sub(r'-slice-\d+$', '', slug)
        for ks in known_slugs:
            ks_prefix = re.sub(r'-slice-\d+$', '', ks)
            if slug_prefix == ks_prefix:
                slug_boost = 0.2
                break

        # Boost for tasks that have been retried (attempt > 0)
        attempt_boost = min(0.1 * task.get("attempt", 0), 0.3)

        risk = min(1.0, base_rate + slug_boost + attempt_boost)
        should_precreate = risk >= _THRESHOLD

        return {
            "risk_score": round(risk, 3),
            "should_precreate": should_precreate,
            "reason": f"base_rate={base_rate:.3f} slug_boost={slug_boost:.2f} attempt_boost={attempt_boost:.2f}",
        }
    except Exception as exc:
        _log.debug("predict_missing_branch error: %s", exc)
        return {"risk_score": 0.0, "should_precreate": False, "reason": f"error: {exc}"}


def load_history_from_db(project_id=None):
    """Bootstrap failure history from tasks table (notes containing 'missing branch')."""
    if not _ENABLED:
        return 0
    try:
        filters = {
            "select": "id,slug,project_id,note",
            "state": "in.(DONE,BLOCKED,QUARANTINED)",
            "limit": "500",
        }
        if project_id:
            filters["project_id"] = f"eq.{project_id}"
        tasks = db.select("tasks", filters) or []
        loaded = 0
        for t in tasks:
            note = t.get("note", "") or ""
            had_missing = bool(re.search(r"missing.?branch|branch.?not.?found|no.?such.?ref", note, re.I))
            record_branch_outcome(t["project_id"], t.get("slug", ""), had_missing)
            loaded += 1
        _log.info("loaded branch history: %d tasks", loaded)
        return loaded
    except Exception as exc:
        _log.debug("load_history_from_db error: %s", exc)
        return 0


def predict_batch(tasks):
    """Predict missing-branch risk for a batch of tasks. Returns list of predictions."""
    return [{"slug": t.get("slug", ""), **predict_missing_branch(t)} for t in tasks]


def stats():
    """Return current prediction state for observability."""
    with _lock:
        return {
            pid: {
                "total_tasks": e["total_tasks"],
                "missing_branch_failures": e["missing_branch_failures"],
                "failure_rate": round(e["missing_branch_failures"] / e["total_tasks"], 3) if e["total_tasks"] else 0,
                "known_slug_count": len(e["slugs"]),
            }
            for pid, e in _failure_history.items()
        }


def decay():
    """Apply exponential decay to old failure counts to adapt to changing conditions."""
    with _lock:
        for pid, entry in _failure_history.items():
            entry["total_tasks"] = int(entry["total_tasks"] * _DECAY_FACTOR)
            entry["missing_branch_failures"] = int(entry["missing_branch_failures"] * _DECAY_FACTOR)
            if entry["total_tasks"] == 0:
                entry["slugs"].clear()


if __name__ == "__main__":
    import json
    pid = sys.argv[1] if len(sys.argv) > 1 else None
    loaded = load_history_from_db(pid)
    print(f"Loaded {loaded} task records")
    print(json.dumps(stats(), indent=2, default=str))
