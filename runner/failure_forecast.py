"""
failure_forecast.py - rule-based skip for tasks with consecutive terminal failures.

should_skip(task_id, db) returns True when the task has >= 3 consecutive terminal
failures in the run history. Rule-based only - no ML, no embeddings.
"""

TERMINAL_STATES = ('failed', 'error')
CONSECUTIVE_FAIL_THRESHOLD = 3


def should_skip(task_id, db):
    """Return True when the task has >= 3 consecutive terminal failures.

    Queries the run_history table ordered by created_at DESC. Counts consecutive
    terminal statuses from the most recent run backwards. If the most recent run
    succeeded, returns False (the streak is broken).
    """
    try:
        rows = db.select("run_history", {
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
        if row.get("status") in TERMINAL_STATES:
            consecutive_failures += 1
        else:
            break

    return consecutive_failures >= CONSECUTIVE_FAIL_THRESHOLD
