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


def queue_stats() -> dict:
    """Return current queue state counts."""
    try:
        rows = db.sql(
            "SELECT state, count(*) as cnt FROM tasks GROUP BY state ORDER BY state"
        )
        return {r["state"]: int(r["cnt"]) for r in (rows or [])}
    except Exception:
        return {}


def project_stats(project_id: str) -> dict:
    """Return task stats for a specific project."""
    try:
        rows = db.sql(
            f"SELECT state, count(*) as cnt FROM tasks "
            f"WHERE project_id = '{project_id}' GROUP BY state ORDER BY state"
        )
        return {r["state"]: int(r["cnt"]) for r in (rows or [])}
    except Exception:
        return {}


def heartbeat(account: str, claimed: int = 0, done: int = 0) -> None:
    """Record executor heartbeat in fleet_config."""
    import json as _json
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    value = _json.dumps({"ts": ts, "claimed": claimed, "done": done})
    try:
        db.sql(
            f"INSERT INTO fleet_config (key, value) "
            f"VALUES ('{account}_LAST_RUN', '{value}'::jsonb) "
            f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )
    except Exception:
        pass
