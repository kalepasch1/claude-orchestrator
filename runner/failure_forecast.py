"""
failure_forecast.py - rule-based skip for tasks with consecutive terminal failures.

should_skip(task_id, db) returns True when the task has >= 3 consecutive terminal
failures in the run history. Rule-based only - no ML, no embeddings.
"""

# Case-insensitive; rows may carry either a "status" or a "state" column.
TERMINAL_STATES = ('failed', 'error', 'blocked', 'quarantined')
CONSECUTIVE_FAIL_THRESHOLD = 3


def _row_status(row):
    return str(row.get("status") or row.get("state") or "").lower()


def should_skip(task_id, db=None, _db=None):
    """Return True when the task has >= 3 consecutive terminal failures.

    Queries the run_history table ordered by most recent first. Counts consecutive
    terminal statuses from the most recent run backwards. If the most recent run
    succeeded, returns False (the streak is broken).

    The DB client can be passed positionally as `db` or injected as `_db`
    (test double). Falls back to the module-level `db` import when omitted.
    """
    client = _db if _db is not None else db
    if client is None:
        try:
            import db as client  # type: ignore
        except Exception:
            return False

    try:
        rows = client.select("run_history", {
            "select": "status",
            "task_id": "eq." + str(task_id),
            "order": "created_at.desc",
            "limit": str(CONSECUTIVE_FAIL_THRESHOLD + 1),
        }) or []
    except Exception:
        return False

    if len(rows) < CONSECUTIVE_FAIL_THRESHOLD:
        return False

    consecutive_failures = 0
    for row in rows:
        if _row_status(row) in TERMINAL_STATES:
            consecutive_failures += 1
        else:
            break

    return consecutive_failures >= CONSECUTIVE_FAIL_THRESHOLD
