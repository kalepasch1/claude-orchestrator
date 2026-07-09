#!/usr/bin/env python3
"""Fetch historical branch event data from the task queue for ML training.

Produces one record per task with branch-relevant features and a binary label:
  1 = branch needed/active (QUEUED, RUNNING, RETRY, or recently DONE)
  0 = branch stale        (MERGED, QUARANTINED, or DONE/BLOCKED and old)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ACTIVE_STATES = frozenset({"QUEUED", "RUNNING", "RETRY"})
STALE_STATES = frozenset({"MERGED", "QUARANTINED"})
STALE_DONE_AGE_DAYS = int(os.environ.get("BRANCH_TELEMETRY_STALE_DONE_DAYS", "14"))


def get_historical_branch_events(limit=2000):
    """Return list of feature dicts with 'label' key for ML training.

    Returns [] on any DB error so callers can fall back to synthetic data.
    """
    try:
        tasks = db.select("tasks", {
            "select": "id,project_id,state,created_at,updated_at",
            "state": "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,QUARANTINED)",
            "limit": str(limit),
            "order": "updated_at.desc",
        }) or []
    except Exception:
        return []

    project_queue_depth = _load_queue_depths()

    now = datetime.datetime.utcnow()
    events = []
    for t in tasks:
        state = t.get("state") or ""
        created_at = t.get("created_at")
        updated_at = t.get("updated_at") or created_at

        branch_age_days = _age_days(now, created_at)
        days_since_activity = _age_days(now, updated_at)

        label = _label(state, days_since_activity)
        if label is None:
            continue

        pid = t.get("project_id")
        depth = project_queue_depth.get(pid, 0)
        events.append({
            "task_id": t.get("id"),
            "project_id": pid,
            "state": state,
            "branch_age_days": branch_age_days,
            "days_since_activity": days_since_activity,
            "task_state_queued": 1 if state == "QUEUED" else 0,
            "task_state_running": 1 if state == "RUNNING" else 0,
            "project_queue_depth_norm": min(depth, 20.0) / 20.0,
            "label": label,
        })
    return events


def _label(state, days_since_activity):
    """Return 1 (needed), 0 (stale), or None (skip ambiguous)."""
    if state in ACTIVE_STATES:
        return 1
    if state in STALE_STATES:
        return 0
    if state == "DONE":
        return 0 if days_since_activity > STALE_DONE_AGE_DAYS else 1
    if state == "BLOCKED":
        return 0 if days_since_activity > STALE_DONE_AGE_DAYS else None
    return None


def _load_queue_depths():
    """Return {project_id: queued_task_count} mapping. Returns {} on error."""
    try:
        rows = db.select("tasks", {
            "select": "project_id",
            "state": "in.(QUEUED,RUNNING)",
            "limit": "5000",
        }) or []
        depth = {}
        for row in rows:
            pid = row.get("project_id")
            if pid:
                depth[pid] = depth.get(pid, 0) + 1
        return depth
    except Exception:
        return {}


def _age_days(now, ts):
    if not ts:
        return 0.0
    try:
        raw = str(ts).replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(raw)
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return max(0.0, (now - dt).total_seconds() / 86400.0)
    except Exception:
        return 0.0
