#!/usr/bin/env python3
"""Exact queue counters used by autopilot and dashboard parity checks."""
import os

import db

QUEUE_STATES = tuple(
    s.strip().upper()
    for s in os.environ.get(
        "ORCH_QUEUE_COUNTER_STATES",
        "QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,CONFLICT,TESTFAIL,QUARANTINED,DECOMPOSED,SHELVED,WAITING",
    ).split(",")
    if s.strip()
)
BLOCKED_LIKE = ("BLOCKED", "CONFLICT", "TESTFAIL")
ACTIVE_LIKE = ("QUEUED", "RUNNING", "RETRY")
RECOVERY_PREFIX = "recover-missing-branch-"
IMPROVE_PREFIX = "improve-"
CANARY_PREFIX = "canary-"
RELEASE_FIX_PREFIXES = ("relfix-", "qafix-", "deployfix-", "buildfix-", "copyfix-")


def _int_count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"db.count returned non-numeric value {type(value).__name__}")
    return int(value)


def _count(db_client, params=None):
    return _int_count(db_client.count("tasks", params or {}))


def _state_count(db_client, state):
    return _count(db_client, {"state": f"eq.{state}"})


def _prefix_count(db_client, prefix, state=None):
    params = {"slug": f"like.{prefix}%"}
    if state:
        params["state"] = f"eq.{state}"
    return _count(db_client, params)


def _release_fix_count(db_client, state=None):
    return sum(_prefix_count(db_client, prefix, state=state) for prefix in RELEASE_FIX_PREFIXES)


def _view_counts(db_client):
    if not hasattr(db_client, "select"):
        return None
    rows = db_client.select("v_task_queue_counters", {"select": "bucket,name,n"}) or []
    if not isinstance(rows, list):
        return None
    rows = [r for r in rows if isinstance(r, dict) and r.get("bucket") and r.get("name")]
    if not rows:
        return None
    states = {r["name"]: _int_count(r.get("n", 0)) for r in rows if r.get("bucket") == "state"}
    totals = {r["name"]: _int_count(r.get("n", 0)) for r in rows if r.get("bucket") == "total"}
    prefixes = {r["name"]: _int_count(r.get("n", 0)) for r in rows if r.get("bucket") == "prefix"}
    total_tasks = totals.get("tasks", sum(states.values()))
    queued = states.get("QUEUED", 0)
    running = states.get("RUNNING", 0)
    retry = states.get("RETRY", 0)
    blocked_like = sum(states.get(state, 0) for state in BLOCKED_LIKE)
    active_like = sum(states.get(state, 0) for state in ACTIVE_LIKE)
    return {
        "states": states,
        "total_tasks": total_tasks,
        "known_state_total": sum(states.values()),
        "unknown_state_total": max(0, total_tasks - sum(states.values())),
        "queued": queued,
        "running": running,
        "retry": retry,
        "active_like": active_like,
        "blocked_like": blocked_like,
        "quarantined": states.get("QUARANTINED", 0),
        "recovery_queued": prefixes.get("recovery_queued", 0),
        "improvements_queued": prefixes.get("improvements_queued", 0),
        "canaries_active": prefixes.get("canaries_active", 0),
        "release_fix_queued": prefixes.get("release_fix_queued", 0),
        "release_fix_running": prefixes.get("release_fix_running", 0),
        "source": "v_task_queue_counters",
    }


def exact_counts(db_client=db):
    """Return exact full-table queue pressure counters.

    Sampled task lists are useful for recency, but they hide old backlog once the queue is deeper
    than the UI or autopilot sample window. These counters use PostgREST's SQL count path instead.
    """
    try:
        from_view = _view_counts(db_client)
        if from_view:
            return from_view
    except Exception:
        pass

    states = {state: _state_count(db_client, state) for state in QUEUE_STATES}
    total_tasks = _count(db_client, {})
    known_state_total = sum(states.values())
    queued = states.get("QUEUED", 0)
    running = states.get("RUNNING", 0)
    retry = states.get("RETRY", 0)
    blocked_like = sum(states.get(state, 0) for state in BLOCKED_LIKE)
    active_like = sum(states.get(state, 0) for state in ACTIVE_LIKE)
    recovery_queued = _prefix_count(db_client, RECOVERY_PREFIX, state="QUEUED")
    improvements_queued = _prefix_count(db_client, IMPROVE_PREFIX, state="QUEUED")
    canaries_active = _count(db_client, {
        "slug": f"like.{CANARY_PREFIX}%",
        "state": "in.(QUEUED,RUNNING)",
    })
    release_fix_queued = _release_fix_count(db_client, state="QUEUED")
    release_fix_running = _release_fix_count(db_client, state="RUNNING")
    return {
        "states": states,
        "total_tasks": total_tasks,
        "known_state_total": known_state_total,
        "unknown_state_total": max(0, total_tasks - known_state_total),
        "queued": queued,
        "running": running,
        "retry": retry,
        "active_like": active_like,
        "blocked_like": blocked_like,
        "quarantined": states.get("QUARANTINED", 0),
        "recovery_queued": recovery_queued,
        "improvements_queued": improvements_queued,
        "canaries_active": canaries_active,
        "release_fix_queued": release_fix_queued,
        "release_fix_running": release_fix_running,
        "source": "postgrest_exact_count",
    }
