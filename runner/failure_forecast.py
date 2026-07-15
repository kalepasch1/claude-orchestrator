"""Predictive preemption: skip tasks with repeated consecutive failures.

Rule-based only — no ML, no embeddings, no proposals.
"""

import db


def should_skip(task_id: str, _db=None) -> bool:
    """Return True when the task has >=3 consecutive terminal failures.

    Checks the tasks table for rows sharing the same slug root (ignoring
    remediation suffixes) with terminal states ('QUARANTINED', 'BLOCKED',
    'FAILED', 'ERROR'). Only the most recent consecutive run of terminal
    states counts — a single success resets the streak.

    Parameters
    ----------
    task_id : str
        The task UUID to evaluate.
    _db : module, optional
        Injectable db module for testing; defaults to the real ``db`` module.
    """
    store = _db or db
    TERMINAL = {"QUARANTINED", "BLOCKED", "FAILED", "ERROR"}

    # Fetch the task to get its slug
    try:
        rows = store.select("tasks", {
            "select": "slug,project_id",
            "id": f"eq.{task_id}",
        })
    except Exception:
        return False

    if not rows:
        return False

    task = rows[0]
    slug = task.get("slug", "")
    project_id = task.get("project_id", "")

    if not slug or not project_id:
        return False

    # Extract the base slug (strip rework-/recover- prefixes and hash suffixes)
    base_slug = slug
    for prefix in ("rework-buildfail-", "rework-testfail-", "rework-",
                    "recover-missing-branch-", "recover-"):
        if base_slug.startswith(prefix):
            base_slug = base_slug[len(prefix):]
            break

    # Fetch recent tasks with similar slugs, ordered newest first
    try:
        rows = store.select("tasks", {
            "select": "state,updated_at",
            "project_id": f"eq.{project_id}",
            "slug": f"like.*{base_slug[:40]}*",
            "order": "updated_at.desc",
            "limit": "10",
        })
    except Exception:
        return False

    # Count consecutive terminal failures from most recent
    consecutive = 0
    for row in rows:
        state = (row.get("state") or "").upper()
        if state in TERMINAL:
            consecutive += 1
        else:
            break

    return consecutive >= 3
