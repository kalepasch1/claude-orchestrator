#!/usr/bin/env python3
"""
branch_lifecycle_dataset.py — baseline ML branch prediction dataset builder.

Builds labeled training data for a branch-lifecycle classifier from the tasks
table. Each row captures features (branch age, days since activity, task state,
project queue depth) and a label (1 = needed, 0 = stale).

Fail-soft: returns empty list on any error; never raises.

Environment:
    ORCH_STALE_DONE_AGE_DAYS  — threshold for labeling DONE tasks as stale (default 7)
"""
import os
import sys
import datetime
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("branch_lifecycle_dataset")

STALE_DONE_AGE_DAYS = float(os.environ.get("ORCH_STALE_DONE_AGE_DAYS", "7"))
ACTIVE_STATES = ("QUEUED", "RUNNING", "RETRY")
STALE_STATES = ("QUARANTINED",)


def build_dataset(tasks, queue_depths=None, limit=500, now=None):
    """Build labeled dataset from task records.

    Args:
        tasks: list of task dicts with id, project_id, state, created_at, updated_at.
        queue_depths: dict {project_id: int} of current queue depths. Optional.
        limit: max rows to return.
        now: override current time for testing.

    Returns:
        list of feature dicts with keys: task_id, project_id, state,
        branch_age_days, days_since_activity, task_state_queued,
        task_state_running, project_queue_depth_norm, label.
    """
    if now is None:
        now = datetime.datetime.utcnow()
    if queue_depths is None:
        queue_depths = {}

    events = []
    try:
        for t in (tasks or [])[:limit]:
            state = (t.get("state") or "").upper()
            created_at = t.get("created_at")
            updated_at = t.get("updated_at") or created_at

            branch_age_days = _age_days(now, created_at)
            days_since_activity = _age_days(now, updated_at)

            label = _label(state, days_since_activity)
            if label is None:
                continue

            pid = t.get("project_id") or ""
            depth = queue_depths.get(pid, 0)

            events.append({
                "task_id": t.get("id"),
                "project_id": pid,
                "state": state,
                "branch_age_days": branch_age_days or 0.0,
                "days_since_activity": days_since_activity or 0.0,
                "task_state_queued": 1 if state == "QUEUED" else 0,
                "task_state_running": 1 if state == "RUNNING" else 0,
                "project_queue_depth_norm": min(depth, 20.0) / 20.0,
                "label": label,
            })
    except Exception as exc:
        log.warning("build_dataset error: %s", exc)
    return events


def _label(state, days_since_activity):
    """Return 1 (needed), 0 (stale), or None (skip ambiguous)."""
    if state in ACTIVE_STATES:
        return 1
    if state in STALE_STATES:
        return 0
    if state == "DONE":
        return 0 if (days_since_activity or 0) > STALE_DONE_AGE_DAYS else 1
    if state == "MERGED":
        return 0
    if state == "BLOCKED":
        return 0 if (days_since_activity or 0) > STALE_DONE_AGE_DAYS else None
    return None


def _age_days(now, ts):
    """Return age in days. Fail-soft: returns None on bad input."""
    if ts is None:
        return None
    try:
        if isinstance(ts, str):
            ts = ts.replace("Z", "+00:00")
            if "+" in ts[10:]:
                ts = ts[:ts.rindex("+")]
            dt = datetime.datetime.fromisoformat(ts)
        elif isinstance(ts, datetime.datetime):
            dt = ts
        else:
            return None
        return (now - dt).total_seconds() / 86400.0
    except Exception:
        return None
