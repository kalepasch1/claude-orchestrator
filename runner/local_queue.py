#!/usr/bin/env python3
"""
local_queue.py — SQLite-backed local mirror for runner task claiming during DB outage.

Shadows QUEUED and RUNNING tasks from remote DB when connectivity is healthy.
On DB failure (after N consecutive retries), claims from local mirror to prevent
runner stalling. Single-machine safety via ORCH_OFFLINE_CLAIM_HOST hostname allowlist.
"""
import os
import sqlite3
import threading
import socket
import json
import datetime
import logging
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RUNTIME = os.path.join(REPO, ".runtime")
MIRROR_DB = os.path.join(RUNTIME, "queue_mirror.db")

_log = logging.getLogger("local_queue")
_mirror_lock = threading.Lock()
_conn = None


def _get_connection():
    """Get or create SQLite connection to mirror database."""
    global _conn
    if _conn is not None:
        return _conn
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        _conn = sqlite3.connect(MIRROR_DB, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        return _conn
    except Exception as e:
        _log.warning("failed to open mirror DB: %s", e)
        return None


def _init_mirror_schema():
    """Create mirror tables if they don't exist."""
    conn = _get_connection()
    if not conn:
        return
    try:
        with _mirror_lock:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mirror_tasks (
                    id TEXT PRIMARY KEY,
                    slug TEXT,
                    project_id TEXT,
                    state TEXT,
                    deps TEXT,
                    confidence REAL,
                    created_at TEXT,
                    updated_at TEXT,
                    kind TEXT,
                    note TEXT,
                    priority INTEGER,
                    account TEXT,
                    synced_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_state_created
                ON mirror_tasks(state, created_at)
            """)
            conn.commit()
    except Exception as e:
        _log.warning("failed to init mirror schema: %s", e)


def sync_from_remote(remote_tasks_queued, remote_tasks_running):
    """Sync QUEUED and RUNNING tasks from remote DB to local mirror.

    Called with results from select("tasks", ...) during normal polling to maintain
    an up-to-date offline copy. Idempotent: replaying same rows does not corrupt state.
    Used by claim_task to seed the offline fallback when DB is healthy.

    Args:
        remote_tasks_queued (list | None): QUEUED tasks from remote DB.
        remote_tasks_running (list | None): RUNNING tasks from remote DB.

    Returns:
        None. Fail-soft: logs warnings on error instead of raising.
    """
    if not remote_tasks_queued and not remote_tasks_running:
        return

    conn = _get_connection()
    if not conn:
        return

    try:
        _init_mirror_schema()
        now = datetime.datetime.utcnow().isoformat() + "Z"

        with _mirror_lock:
            for task in (remote_tasks_queued or []):
                _upsert_mirror_task(conn, task, now)
            for task in (remote_tasks_running or []):
                _upsert_mirror_task(conn, task, now)
            conn.commit()
    except Exception as e:
        _log.warning("sync_from_remote failed: %s", e)


def _upsert_mirror_task(conn, task, now):
    """Insert or replace task in mirror, idempotently."""
    try:
        task_id = task.get("id")
        if not task_id:
            return
        deps_json = json.dumps(task.get("deps") or []) if task.get("deps") else "[]"
        conn.execute("""
            INSERT OR REPLACE INTO mirror_tasks
            (id, slug, project_id, state, deps, confidence, created_at, updated_at, kind, note, priority, account, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            task.get("slug"),
            task.get("project_id"),
            task.get("state", "QUEUED"),
            deps_json,
            task.get("confidence"),
            task.get("created_at"),
            task.get("updated_at"),
            task.get("kind"),
            task.get("note"),
            task.get("priority"),
            task.get("account"),
            now
        ))
    except Exception as e:
        _log.warning("failed to upsert mirror task %s: %s", task.get("id"), e)


def is_offline_claiming_allowed():
    """Check if this hostname is allowlisted for offline claiming.

    Offline claiming is restricted to a single designated host to prevent
    cross-machine task stealing when DB is unreachable. Set ORCH_OFFLINE_CLAIM_HOST
    to enable (e.g., ORCH_OFFLINE_CLAIM_HOST=myhost.local).

    Returns:
        bool: True if this hostname matches ORCH_OFFLINE_CLAIM_HOST; False otherwise.
    """
    hostname = socket.gethostname()
    allowed_host = os.environ.get("ORCH_OFFLINE_CLAIM_HOST", "").strip()
    return bool(allowed_host and hostname == allowed_host)


def claim_task_offline(runner_id):
    """Claim one task from local mirror when DB is unreachable.

    Mirrors remote claim_task behavior using SQLite local cache. Used as fallback
    when db.is_db_down() returns True (N consecutive DB failures). Respects host
    affinity via is_offline_claiming_allowed().

    Args:
        runner_id (str): Unique identifier for this runner/executor.

    Returns: Optional[dict]: Task dict (id, slug, project_id, state, etc.) if claim succeeds,
                     None if no task in queue or claiming not allowed for this host.
                     Fail-soft: returns None on any error instead of raising.
    """
    if not is_offline_claiming_allowed():
        return None

    conn = _get_connection()
    if not conn:
        return None

    try:
        _init_mirror_schema()

        with _mirror_lock:
            cursor = conn.execute("""
                SELECT id, slug, project_id, state, deps, confidence, created_at, updated_at, kind, note, priority
                FROM mirror_tasks
                WHERE state = 'QUEUED'
                ORDER BY created_at ASC
                LIMIT 1
            """)
            row = cursor.fetchone()
            if not row:
                return None

            task_id = row[0]
            conn.execute("""
                UPDATE mirror_tasks
                SET state = 'RUNNING', account = ?, updated_at = ?
                WHERE id = ?
            """, (runner_id, datetime.datetime.utcnow().isoformat() + "Z", task_id))
            conn.commit()

            return {
                "id": row[0],
                "slug": row[1],
                "project_id": row[2],
                "state": row[3],
                "deps": json.loads(row[4]) if row[4] else [],
                "confidence": row[5],
                "created_at": row[6],
                "updated_at": row[7],
                "kind": row[8],
                "note": row[9],
                "priority": row[10],
            }
    except Exception as e:
        _log.warning("claim_task_offline failed: %s", e)
        return None


def mark_task_running_offline(task_id, runner_id):
    """Mark a task as RUNNING in the mirror (idempotent)."""
    conn = _get_connection()
    if not conn:
        return

    try:
        with _mirror_lock:
            conn.execute("""
                UPDATE mirror_tasks
                SET state = 'RUNNING', account = ?, updated_at = ?
                WHERE id = ?
            """, (runner_id, datetime.datetime.utcnow().isoformat() + "Z", task_id))
            conn.commit()
    except Exception as e:
        _log.warning("mark_task_running_offline failed: %s", e)


def invalidate_mirror():
    """Clear all mirror state on DB recovery. Operator must manually resync."""
    conn = _get_connection()
    if not conn:
        return

    try:
        with _mirror_lock:
            conn.execute("DELETE FROM mirror_tasks")
            conn.commit()
            _log.info("mirror invalidated (DB recovery)")
    except Exception as e:
        _log.warning("invalidate_mirror failed: %s", e)


def stats():
    """Return mirror statistics for monitoring."""
    conn = _get_connection()
    if not conn:
        return {"status": "unavailable"}

    try:
        with _mirror_lock:
            queued = conn.execute("SELECT COUNT(*) FROM mirror_tasks WHERE state = 'QUEUED'").fetchone()[0]
            running = conn.execute("SELECT COUNT(*) FROM mirror_tasks WHERE state = 'RUNNING'").fetchone()[0]
            oldest = conn.execute("SELECT MIN(created_at) FROM mirror_tasks WHERE state = 'QUEUED'").fetchone()[0]
            return {
                "status": "ok",
                "queued": queued,
                "running": running,
                "oldest_task_age": oldest or "",
                "db_path": MIRROR_DB,
            }
    except Exception as e:
        _log.warning("stats() failed: %s", e)
        return {"status": "error", "error": str(e)}


_init_mirror_schema()
