"""queue_state_monitor.py — lightweight queue-state snapshots for sync monitoring.

Provides a single function that captures the current task-queue distribution
(counts by state, by project, staleness) and returns it as a plain dict.
Intended for real-time dashboards and operator alerts that need to detect
drift between the DB queue and what agents actually see.

Fail-soft: returns partial data on DB errors rather than raising.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Stale threshold in seconds — tasks RUNNING longer than this may be zombies.
STALE_THRESHOLD_S = int(os.environ.get("ORCH_STALE_THRESHOLD_S", "5400"))  # 90 min


def _safe_import_db():
    """Import the db module, returning None if unavailable."""
    try:
        import db as _db
        return _db
    except Exception:
        return None


def snapshot(db_module=None) -> Dict[str, Any]:
    """Capture a point-in-time queue state snapshot.

    Returns a dict with:
      - ``by_state``: {state: count} for every task state
      - ``by_project``: {project_name: {state: count}}
      - ``zombie_candidates``: count of RUNNING tasks older than STALE_THRESHOLD_S
      - ``total``: total task count
      - ``ts``: snapshot timestamp (epoch seconds)

    Fail-soft: on any DB error, returns whatever partial data was collected.
    """
    result: Dict[str, Any] = {
        "by_state": {},
        "by_project": {},
        "zombie_candidates": 0,
        "total": 0,
        "ts": time.time(),
    }

    db = db_module or _safe_import_db()
    if db is None:
        logger.warning("queue_state_monitor: db module unavailable")
        return result

    # State distribution
    try:
        rows = db.execute_sql(
            "SELECT state, count(*) as cnt FROM tasks GROUP BY state"
        ) or []
        for row in rows:
            state = row.get("state", "UNKNOWN")
            cnt = int(row.get("cnt", 0))
            result["by_state"][state] = cnt
            result["total"] += cnt
    except Exception as exc:
        logger.warning("queue_state_monitor state query failed: %s", exc)

    # Zombie candidates
    try:
        rows = db.execute_sql(
            f"SELECT count(*) as cnt FROM tasks "
            f"WHERE state = 'RUNNING' "
            f"AND updated_at < now() - interval '{STALE_THRESHOLD_S} seconds'"
        ) or []
        if rows:
            result["zombie_candidates"] = int(rows[0].get("cnt", 0))
    except Exception as exc:
        logger.warning("queue_state_monitor zombie query failed: %s", exc)

    # Per-project breakdown
    try:
        rows = db.execute_sql(
            "SELECT p.name, t.state, count(*) as cnt "
            "FROM tasks t JOIN projects p ON t.project_id = p.id "
            "GROUP BY p.name, t.state ORDER BY p.name"
        ) or []
        for row in rows:
            pname = row.get("name", "unknown")
            state = row.get("state", "UNKNOWN")
            cnt = int(row.get("cnt", 0))
            result["by_project"].setdefault(pname, {})[state] = cnt
    except Exception as exc:
        logger.warning("queue_state_monitor project query failed: %s", exc)

    return result

