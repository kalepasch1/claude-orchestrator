#!/usr/bin/env python3
"""
scm_branch_proposer.py — rule-based heuristic for proposing SCM branch operations.

Proposes creation for tasks entering RUNNING that lack a branch, and deletion for
tasks in terminal states (DONE/MERGED) whose agent/<slug> branch is older than
ORCH_SCM_BRANCH_RETENTION_DAYS.

Fail-soft: any error returns an empty list; never raises.
"""
import os
import sys
import datetime
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("scm_branch_proposer")

RETENTION_DAYS = int(os.environ.get("ORCH_SCM_BRANCH_RETENTION_DAYS", "14"))
TERMINAL_STATES = ("DONE", "MERGED")
ACTIVE_STATES = ("RUNNING", "QUEUED", "RETRY")


def propose(tasks, existing_branches=None, now=None):
    """Return a list of proposed branch operations.

    Args:
        tasks: list of task dicts with keys: id, slug, project_id, state,
               updated_at (ISO string or datetime).
        existing_branches: set of branch names currently in the repo.
                           If None, skip deletion proposals.
        now: override current time for testing.

    Returns:
        list of dicts: {'action': 'create'|'delete', 'project_id': str,
                        'branch_name': str, 'reason': str, 'task_id': str}
    """
    if now is None:
        now = datetime.datetime.utcnow()
    if existing_branches is None:
        existing_branches = set()

    proposals = []
    try:
        for t in (tasks or []):
            slug = (t.get("slug") or "").strip()
            state = (t.get("state") or "").upper()
            pid = t.get("project_id") or ""
            tid = t.get("id") or ""

            if not slug:
                continue

            branch_name = f"agent/{slug}"

            # Creation: task is active but branch doesn't exist
            if state in ACTIVE_STATES and branch_name not in existing_branches:
                proposals.append({
                    "action": "create",
                    "project_id": pid,
                    "branch_name": branch_name,
                    "reason": f"task {slug} is {state} but has no branch",
                    "task_id": tid,
                })

            # Deletion: task is terminal and branch is stale
            if state in TERMINAL_STATES and branch_name in existing_branches:
                age = _age_days(now, t.get("updated_at"))
                if age is not None and age > RETENTION_DAYS:
                    proposals.append({
                        "action": "delete",
                        "project_id": pid,
                        "branch_name": branch_name,
                        "reason": f"task {slug} is {state}, branch idle {age:.0f}d > {RETENTION_DAYS}d retention",
                        "task_id": tid,
                    })
    except Exception as exc:
        log.warning("scm_branch_proposer.propose error: %s", exc)
    return proposals


def _age_days(now, ts):
    """Return age in days between now and ts. Fail-soft: returns None on bad input."""
    if ts is None:
        return None
    try:
        if isinstance(ts, str):
            # Handle ISO format with or without Z/timezone
            ts = ts.replace("Z", "+00:00")
            if "+" in ts[10:]:
                ts = ts[:ts.rindex("+")]
            dt = datetime.datetime.fromisoformat(ts)
        elif isinstance(ts, datetime.datetime):
            dt = ts
        else:
            return None
        return (now - dt).total_seconds() / 86400.0
    except Exception:
        return None
