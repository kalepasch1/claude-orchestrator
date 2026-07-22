#!/usr/bin/env python3
"""
file_reservation.py — DB-backed file-level mutual exclusion for the orchestrator.

Prevents merge conflicts structurally: before a task starts execution, the
runner reserves the files it will touch. If another task already holds any of
those files, the new task is re-queued instead of creating a conflicting branch.

The reservation table lives in the orchestrator's Supabase DB:

    CREATE TABLE IF NOT EXISTS file_reservations (
        id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
        task_id     text NOT NULL,
        project_id  text NOT NULL,
        repo        text NOT NULL,
        filepath    text NOT NULL,
        reserved_at timestamptz DEFAULT now(),
        ttl_seconds int DEFAULT 7200,
        UNIQUE (repo, filepath)
    );

Key functions:
    reserve(task, repo, files)     — claim file locks
    release(task)                  — release all locks for a task
    blocked_by(task, repo, files)  — check which files are held by other tasks
    predict_conflicts()            — scan upcoming tasks for likely collisions

Environment:
    ORCH_FILE_RESERVATION_ENABLED  Kill switch (default: true)
    ORCH_FILE_RESERVATION_TTL      Default TTL in seconds (default: 7200)
    ORCH_SHARED_FILE_TTL           TTL for known shared files like schema.prisma (default: 1800)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import db
except Exception:
    db = None

try:
    import log as _log_mod
    _log = _log_mod.get("file_reservation")
except Exception:
    import logging
    _log = logging.getLogger("file_reservation")

ENABLED = os.environ.get("ORCH_FILE_RESERVATION_ENABLED", "true").lower() in (
    "true", "1", "yes", "on"
)
DEFAULT_TTL = int(os.environ.get("ORCH_FILE_RESERVATION_TTL", "7200"))
SHARED_FILE_TTL = int(os.environ.get("ORCH_SHARED_FILE_TTL", "1800"))

# Files that are frequently touched by multiple tasks and need shorter TTL
SHARED_FILES = {
    "prisma/schema.prisma",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    ".env",
    ".env.local",
    "app/layout.tsx",
    "app/page.tsx",
    "nuxt.config.ts",
}

TABLE = "file_reservations"


def _ensure_table():
    """Create the file_reservations table if it doesn't exist."""
    if not db:
        return False
    try:
        db.query(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
                task_id     text NOT NULL,
                project_id  text NOT NULL DEFAULT '',
                repo        text NOT NULL,
                filepath    text NOT NULL,
                reserved_at timestamptz DEFAULT now(),
                ttl_seconds int DEFAULT {DEFAULT_TTL},
                UNIQUE (repo, filepath)
            );
        """)
        return True
    except Exception as e:
        _log.debug("file_reservation: table creation failed: %s", e)
        # Table might already exist — try to proceed anyway
        return True


def _ttl_for_file(filepath: str) -> int:
    """Return the appropriate TTL for a file path."""
    normalized = filepath.strip().replace("\\", "/")
    if normalized in SHARED_FILES:
        return SHARED_FILE_TTL
    return DEFAULT_TTL


def _clean_expired():
    """Remove expired reservations."""
    if not db:
        return
    try:
        db.query(f"""
            DELETE FROM {TABLE}
            WHERE reserved_at + (ttl_seconds || ' seconds')::interval < now()
        """)
    except Exception as e:
        _log.debug("file_reservation: cleanup failed: %s", e)


def reserve(task: dict, repo: str, files: list[str]) -> dict:
    """Reserve a set of files for a task.

    Args:
        task: Task dict with at least 'id' and optionally 'project_id'
        repo: Repository path
        files: List of relative file paths to reserve

    Returns:
        {"reserved": list[str], "blocked": list[tuple[str,str]], "error": str|None}
    """
    if not ENABLED:
        return {"reserved": files, "blocked": [], "error": None}

    if not db:
        return {"reserved": files, "blocked": [], "error": "no db"}

    _ensure_table()
    _clean_expired()

    task_id = str(task.get("id", ""))
    project_id = str(task.get("project_id", ""))
    result = {"reserved": [], "blocked": [], "error": None}

    for filepath in files:
        filepath = filepath.strip()
        if not filepath:
            continue

        ttl = _ttl_for_file(filepath)

        try:
            # Try to insert (upsert: skip if already held by same task)
            db.query(f"""
                INSERT INTO {TABLE} (task_id, project_id, repo, filepath, ttl_seconds)
                VALUES ('{task_id}', '{project_id}', '{repo}', '{filepath}', {ttl})
                ON CONFLICT (repo, filepath) DO UPDATE
                SET task_id = EXCLUDED.task_id,
                    project_id = EXCLUDED.project_id,
                    reserved_at = now(),
                    ttl_seconds = EXCLUDED.ttl_seconds
                WHERE {TABLE}.task_id = '{task_id}'
            """)
            result["reserved"].append(filepath)
        except Exception as e:
            # Conflict — file is held by another task
            err_str = str(e)
            if "duplicate" in err_str.lower() or "conflict" in err_str.lower() or "unique" in err_str.lower():
                # Find who holds it
                try:
                    rows = db.select(TABLE, {"repo": f"eq.{repo}", "filepath": f"eq.{filepath}"})
                    if rows:
                        holder = rows[0].get("task_id", "unknown")
                        result["blocked"].append((filepath, holder))
                    else:
                        result["reserved"].append(filepath)
                except Exception:
                    result["blocked"].append((filepath, "unknown"))
            else:
                _log.debug("file_reservation: reserve error: %s", e)
                result["error"] = str(e)

    return result


def release(task: dict) -> int:
    """Release all file reservations held by a task.

    Args:
        task: Task dict with at least 'id'

    Returns:
        Number of reservations released
    """
    if not ENABLED or not db:
        return 0

    task_id = str(task.get("id", ""))
    if not task_id:
        return 0

    try:
        db.query(f"DELETE FROM {TABLE} WHERE task_id = '{task_id}'")
        return 1  # DB doesn't return count easily; approximate
    except Exception as e:
        _log.debug("file_reservation: release error: %s", e)
        return 0


def blocked_by(task: dict, repo: str, files: list[str]) -> list[tuple[str, str]]:
    """Check which files are currently reserved by other tasks.

    Args:
        task: The task wanting to reserve (so we can exclude its own reservations)
        repo: Repository path
        files: List of files to check

    Returns:
        List of (filepath, holder_task_id) tuples for blocked files
    """
    if not ENABLED or not db:
        return []

    _clean_expired()

    task_id = str(task.get("id", ""))
    blocked = []

    for filepath in files:
        filepath = filepath.strip()
        if not filepath:
            continue

        try:
            rows = db.select(TABLE, {
                "repo": f"eq.{repo}",
                "filepath": f"eq.{filepath}",
                "task_id": f"neq.{task_id}",
            })
            if rows:
                holder = rows[0].get("task_id", "unknown")
                blocked.append((filepath, holder))
        except Exception:
            pass

    return blocked


def predict_conflicts(project_id: str = "") -> list[dict]:
    """Scan queued tasks and predict which ones will conflict on shared files.

    Returns a list of conflict predictions:
        [{"file": str, "tasks": [task_id, ...], "risk": "high"|"medium"|"low"}, ...]
    """
    if not ENABLED or not db:
        return []

    try:
        filters = {"state": "eq.QUEUED"}
        if project_id:
            filters["project_id"] = f"eq.{project_id}"
        tasks = db.select("tasks", filters) or []
    except Exception:
        return []

    # Build file → task mapping from declared file_scope
    file_tasks: dict[str, list[str]] = {}
    for t in tasks:
        scope_str = t.get("file_scope", "")
        if not scope_str:
            continue
        task_id = str(t.get("id", ""))
        for f in scope_str.split(","):
            f = f.strip()
            if f:
                file_tasks.setdefault(f, []).append(task_id)

    # Find files claimed by multiple tasks
    predictions = []
    for filepath, task_ids in file_tasks.items():
        if len(task_ids) > 1:
            risk = "high" if filepath in SHARED_FILES else "medium"
            predictions.append({
                "file": filepath,
                "tasks": task_ids,
                "risk": risk,
            })

    return sorted(predictions, key=lambda x: (x["risk"] == "low", x["risk"] == "medium", len(x["tasks"])))


def stats() -> dict:
    """Return current reservation statistics."""
    if not db:
        return {"active": 0, "error": "no db"}

    try:
        _clean_expired()
        rows = db.select(TABLE, {}) or []
        by_repo: dict[str, int] = {}
        for r in rows:
            repo = r.get("repo", "unknown")
            by_repo[repo] = by_repo.get(repo, 0) + 1
        return {"active": len(rows), "by_repo": by_repo}
    except Exception as e:
        return {"active": 0, "error": str(e)}


# ── Standalone mode ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json as _json

    if "--predict" in sys.argv:
        preds = predict_conflicts()
        print(_json.dumps(preds, indent=2))
    elif "--stats" in sys.argv:
        print(_json.dumps(stats(), indent=2))
    elif "--cleanup" in sys.argv:
        _clean_expired()
        print("Expired reservations cleaned.")
    else:
        print("Usage: python3 file_reservation.py [--predict|--stats|--cleanup]")
