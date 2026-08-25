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


#: Set once the table has been probed, so the warning below is printed at most
#: once per process rather than once per reserved file.
_TABLE_STATE = {"checked": False, "present": False}


def _table_present():
    """True if `file_reservations` is reachable.  Probes once per process.

    This function used to be `_ensure_table()` and tried to CREATE TABLE IF NOT
    EXISTS through `db.query(...)`.  Two things were wrong with that and both
    were silent.  db has no query(): it speaks PostgREST, which has no DDL
    channel at all, so the call raised AttributeError.  And the handler
    swallowed it and returned True anyway — "Table might already exist — try to
    proceed anyway" — so the caller was told the table was ready no matter what
    happened.  The table has in fact never existed on this fleet (checked
    against the live schema, 2026-08-25: `file_reservations` is not among the
    project's tables).  Creating it is a MIGRATION, not something a runtime
    hot path can do: see runner/migrations/003_file_reservations.sql.

    Absence is now reported once, loudly, instead of being reported as success
    forever.
    """
    if not db:
        return False
    if _TABLE_STATE["checked"]:
        return _TABLE_STATE["present"]
    _TABLE_STATE["checked"] = True
    try:
        db.select(TABLE, {"select": "task_id", "limit": "1"})
        _TABLE_STATE["present"] = True
    except Exception as e:
        _TABLE_STATE["present"] = False
        print("file_reservation: table %r is unavailable (%s) — file-level mutual "
              "exclusion is NOT in force; every task will be allowed to proceed. "
              "Apply runner/migrations/003_file_reservations.sql, or set "
              "ORCH_FILE_RESERVATION_ENABLED=false to say so deliberately."
              % (TABLE, e), flush=True)
        _log.warning("file_reservation: %s unavailable: %s", TABLE, e)
    return _TABLE_STATE["present"]


#: Kept as an alias: `--cleanup` and any external caller still name the old
#: function.  It no longer claims to create anything.
_ensure_table = _table_present


def _ttl_for_file(filepath: str) -> int:
    """Return the appropriate TTL for a file path."""
    normalized = filepath.strip().replace("\\", "/")
    if normalized in SHARED_FILES:
        return SHARED_FILE_TTL
    return DEFAULT_TTL


def _clean_expired():
    """Remove expired reservations.  Returns the number removed.

    The old body was a `db.query("DELETE FROM ... WHERE reserved_at +
    (ttl_seconds || ' seconds')::interval < now()")` against a db module with
    no query() and no SQL channel, inside a `_log.debug` handler — so nothing
    was ever cleaned and nothing was ever said about it.  A reservation whose
    TTL had passed would have held its file forever.

    PostgREST cannot express "reserved_at + ttl_seconds < now()" as a filter
    because the interval is a per-row column, so expiry is computed here and
    the expired ids are deleted by id.  Rows with an unparseable reserved_at
    are LEFT ALONE rather than treated as expired: releasing a lock because a
    timestamp could not be read is the dangerous direction of that mistake.
    """
    if not db or not _table_present():
        return 0
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    removed = 0
    try:
        rows = db.select(TABLE, {"select": "id,reserved_at,ttl_seconds"}) or []
    except Exception as e:
        _log.debug("file_reservation: cleanup read failed: %s", e)
        return 0
    for r in rows:
        raw = str(r.get("reserved_at") or "")
        try:
            stamp = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=_dt.timezone.utc)
            ttl = int(r.get("ttl_seconds") or DEFAULT_TTL)
        except (TypeError, ValueError):
            continue
        if (now - stamp).total_seconds() <= ttl:
            continue
        try:
            db.delete(TABLE, {"id": r["id"]})
            removed += 1
        except Exception as e:
            _log.debug("file_reservation: cleanup delete failed: %s", e)
    return removed


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

    if not _table_present():
        # Say so in the result instead of returning "reserved: everything".
        return {"reserved": [], "blocked": [],
                "error": "%s unavailable — no reservation was taken" % TABLE}

    _clean_expired()

    task_id = str(task.get("id", ""))
    project_id = str(task.get("project_id", ""))
    result = {"reserved": [], "blocked": [], "error": None}

    for filepath in files:
        filepath = filepath.strip()
        if not filepath:
            continue

        ttl = _ttl_for_file(filepath)

        # The claim is the INSERT itself: UNIQUE (repo, filepath) is what makes
        # it atomic across two Macs racing the same file.  db.insert returns the
        # created row, or None when PostgREST answers 409 — which for this table
        # means the unique constraint fired, i.e. somebody else holds the file.
        #
        # The old body sent an `INSERT ... ON CONFLICT DO UPDATE` through
        # db.query(), which does not exist.  The AttributeError it raised said
        # "module 'db' has no attribute 'query'" — containing none of the words
        # "duplicate", "conflict" or "unique" the handler below looked for — so
        # every file fell through to the `else` arm and was recorded as neither
        # reserved nor blocked.  Nothing was ever written to the table, so
        # blocked_by() (which uses the real db.select and works correctly) has
        # always read an empty relation and always returned "nothing is held".
        # runner.py:1205 re-queues a task when blocked_by is non-empty, so the
        # fleet's file-level mutual exclusion has never once blocked anything.
        #
        # Note also that the old statement's ON CONFLICT DO UPDATE would have
        # STOLEN a lock held by another task, not refused it — the WHERE clause
        # sits on the UPDATE, so a losing race left the row untouched and the
        # caller was told it had reserved the file regardless.
        try:
            row = db.insert(TABLE, {
                "task_id": task_id,
                "project_id": project_id,
                "repo": repo,
                "filepath": filepath,
                "ttl_seconds": ttl,
            })
        except Exception as e:
            _log.debug("file_reservation: reserve error: %s", e)
            result["error"] = str(e)
            continue

        if row:
            result["reserved"].append(filepath)
            continue

        # 409: somebody holds (repo, filepath).  Name them — unless it is this
        # same task, which is a re-entry and not a conflict.
        try:
            rows = db.select(TABLE, {"repo": f"eq.{repo}", "filepath": f"eq.{filepath}"}) or []
        except Exception:
            result["blocked"].append((filepath, "unknown"))
            continue
        if not rows:
            # The holder released between the INSERT and this read.  Not ours,
            # and claiming it here without the constraint would not be atomic.
            result["blocked"].append((filepath, "unknown"))
        elif str(rows[0].get("task_id", "")) == task_id:
            result["reserved"].append(filepath)
        else:
            result["blocked"].append((filepath, rows[0].get("task_id", "unknown")))

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

    if not _table_present():
        return 0
    try:
        # Was db.query("DELETE FROM ... WHERE task_id = '...'") — no such
        # function, so this raised, was logged at debug, and returned 0 while
        # its docstring promised a count.  It also interpolated task_id into
        # SQL text unquoted.  db.delete returns the deleted rows, so the count
        # is now real rather than the hardcoded 1 the old comment admitted to
        # ("DB doesn't return count easily; approximate").
        deleted = db.delete(TABLE, {"task_id": task_id})
        return len(deleted or [])
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
    if not ENABLED or not db or not _table_present():
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
