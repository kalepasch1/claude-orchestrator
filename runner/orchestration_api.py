#!/usr/bin/env python3
"""
orchestration_api.py — API layer abstracting orchestration logic from runner.py.

Provides a clean interface for task lifecycle operations that can be consumed
by the runner, external scripts, dashboard endpoints, and future REST/gRPC
services without coupling to runner.py internals.

This is the smallest mergeable first slice: task CRUD + status transitions +
queue introspection. The runner continues to own execution; this layer owns
the data contract.
"""
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


class TaskNotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


# Valid state transitions
VALID_TRANSITIONS = {
    "QUEUED": {"RUNNING", "BLOCKED", "QUARANTINED", "DECOMPOSED"},
    "RUNNING": {"DONE", "MERGED", "BLOCKED", "QUARANTINED", "QUEUED"},
    "DONE": {"MERGED", "QUEUED"},
    "MERGED": set(),
    "BLOCKED": {"QUEUED", "QUARANTINED"},
    "QUARANTINED": {"QUEUED"},
    "DECOMPOSED": {"QUEUED"},
}


def get_task(task_id: str) -> dict:
    """Fetch a single task by ID."""
    rows = db.select("tasks", {"id": f"eq.{task_id}", "limit": 1})
    if not rows:
        raise TaskNotFoundError(f"Task {task_id} not found")
    return rows[0]


def get_task_by_slug(slug: str, project_id: Optional[str] = None) -> Optional[dict]:
    """Fetch a task by slug, optionally scoped to a project."""
    params = {"slug": f"eq.{slug}", "limit": 1}
    if project_id:
        params["project_id"] = f"eq.{project_id}"
    rows = db.select("tasks", params)
    return rows[0] if rows else None


def transition(task_id: str, new_state: str, note: Optional[str] = None,
               account: Optional[str] = None) -> dict:
    """Transition a task to a new state with validation.

    Raises InvalidTransitionError if the transition is not allowed.
    Returns the updated task row.
    """
    task = get_task(task_id)
    current = task.get("state", "")

    allowed = VALID_TRANSITIONS.get(current, set())
    if new_state not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition {task_id} from {current} to {new_state}. "
            f"Allowed: {allowed}"
        )

    patch = {"state": new_state, "updated_at": "now()"}
    if note:
        patch["note"] = note
    if account:
        patch["account"] = account
    if new_state == "DONE":
        patch["finished_at"] = "now()"

    db.update("tasks", {"id": task_id}, patch)
    return {**task, **patch}


def claim_tasks(limit: int = 5, account: str = "api",
                kinds_exclude: Optional[list] = None) -> list:
    """Atomically claim up to `limit` QUEUED tasks.

    Returns list of claimed task rows. Uses SELECT FOR UPDATE SKIP LOCKED
    to avoid conflicts with concurrent claimers.
    """
    exclude = kinds_exclude or ["speculative"]
    exclude_clause = " AND ".join(f"kind != '{k}'" for k in exclude)

    query = f"""
    WITH candidates AS (
        SELECT id FROM tasks
        WHERE state = 'QUEUED' AND {exclude_clause}
        ORDER BY
            CASE kind
                WHEN 'recovery' THEN 1
                WHEN 'toolchain-repair' THEN 2
                WHEN 'bugfix' THEN 3
                WHEN 'build' THEN 4
                WHEN 'canary' THEN 5
                ELSE 6
            END,
            confidence DESC NULLS LAST,
            attempt ASC, id ASC
        LIMIT {int(limit)}
        FOR UPDATE SKIP LOCKED
    ),
    claimed AS (
        UPDATE tasks SET state='RUNNING', account='{account}', updated_at=NOW()
        WHERE id IN (SELECT id FROM candidates)
        RETURNING *
    )
    SELECT c.*, p.name AS project_name, p.repo_path
    FROM claimed c JOIN projects p ON c.project_id = p.id;
    """
    try:
        return db.sql(query) or []
    except Exception:
        return []


def _state_counts(params=None) -> dict:
    """{state: count} over the `tasks` rows matching *params*. {} on error.

    WAS `db.sql("SELECT state, count(*) ... GROUP BY state")`. db speaks
    PostgREST and has never had a `sql()` (or `query()`) function, so this
    raised AttributeError on every call and the `except Exception: return {}`
    below turned it into "the queue is empty" -- a stats endpoint that has only
    ever reported nothing at all.

    One paged read of the `state` column rather than a db.count() per state:
    the old SQL returned whatever states existed, including any this module's
    VALID_TRANSITIONS table does not know about, and losing that would make the
    replacement quietly narrower than what it replaces.
    """
    query = dict(params or {})
    query["select"] = "state"
    try:
        rows = db.select_all("tasks", query) or []
    except Exception:
        return {}
    counts = {}
    for row in rows:
        state = row.get("state")
        if state:
            counts[state] = counts.get(state, 0) + 1
    return counts


def queue_stats() -> dict:
    """Return current queue state counts."""
    return _state_counts()


def project_stats(project_id: str) -> dict:
    """Return task stats for a specific project."""
    # PostgREST needs the operator. The old SQL also interpolated project_id
    # straight into a WHERE clause; this passes it as a filter value instead.
    return _state_counts({"project_id": f"eq.{project_id}"})


def heartbeat(account: str, claimed: int = 0, done: int = 0) -> None:
    """Record executor heartbeat in fleet_config.

    WAS a raw `INSERT ... ON CONFLICT (key) DO UPDATE` through db.sql(), which
    does not exist -- so no executor using this API has ever recorded a
    heartbeat, and the `except Exception: pass` meant nobody found out.
    db.insert(upsert=True) sends Prefer: resolution=merge-duplicates, which is
    the same upsert against the same unique key.
    """
    import json as _json
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    value = _json.dumps({"ts": ts, "claimed": claimed, "done": done})
    try:
        db.insert("fleet_config",
                  {"key": f"{account}_LAST_RUN", "value": value},
                  upsert=True)
    except Exception:
        return None
