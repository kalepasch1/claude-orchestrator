#!/usr/bin/env python3
"""
Deduplicate Legal Radar v1 tasks: transition all queued and running tasks
from the 20260710 prompt to terminal states (superseded/closed).

One-shot idempotent script. Preserves complete task history.
Re-run as many times as needed; already-terminal tasks are skipped.

Run from runner/:  python3 scripts/supersede_legal_radar_v1.py
"""
import os, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__))) == "scripts"
                else os.path.dirname(os.path.abspath(__file__)))

import db

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
log = logging.getLogger("supersede_legal_radar_v1")


SOURCE_MARKER = "20260710-164402-dropbox-PROMPT-legal-radar"


def find_v1_tasks():
    """Query tasks created from the v1 Legal Radar prompt.

    Matches tasks where:
    - slug contains the source filename marker, OR
    - prompt contains the source marker (in wrapped contract or original text)

    Returns list of task dicts with id, slug, state fields.
    """
    try:
        # Query all QUEUED and RUNNING tasks; filter in Python by content match
        # (PostgREST doesn't support JSONB search well, and direct prompt search
        # would pull too much data; filtering in-app is simpler + fail-soft)
        candidates = db.select("tasks", {
            "select": "id,slug,prompt,state",
            "state": "in.(QUEUED,RUNNING)",
            "limit": "5000",
        }) or []

        matches = []
        for task in candidates:
            slug = task.get("slug") or ""
            prompt = task.get("prompt") or ""

            # Match by slug containing the source marker or by marker in prompt
            if SOURCE_MARKER in slug or SOURCE_MARKER in prompt:
                matches.append(task)

        return matches
    except Exception as e:
        log.warning(f"Query failed: {e}", exc_info=True)
        return []


def supersede_queued_tasks(tasks):
    """Transition QUEUED tasks to SUPERSEDED state."""
    count = 0
    updated_ids = []

    for task in tasks:
        state = task.get("state")
        if state != "QUEUED":
            continue

        task_id = task.get("id")
        if not task_id:
            continue

        try:
            db.update("tasks", {"id": task_id}, {
                "state": "SUPERSEDED",
                "reason": "superseded-by-legal-radar-v2",
                "updated_at": "now()",
            })
            count += 1
            updated_ids.append(task_id)
            log.info(f"Superseded QUEUED task {task_id}")
        except Exception as e:
            log.warning(f"Failed to supersede QUEUED task {task_id}: {e}")

    return count, updated_ids


def close_running_tasks(tasks):
    """Transition RUNNING tasks to CLOSED state (do not interrupt mid-flight)."""
    count = 0
    updated_ids = []

    for task in tasks:
        state = task.get("state")
        if state != "RUNNING":
            continue

        task_id = task.get("id")
        if not task_id:
            continue

        try:
            db.update("tasks", {"id": task_id}, {
                "state": "CLOSED",
                "reason": "superseded-by-legal-radar-v2",
                "updated_at": "now()",
            })
            count += 1
            updated_ids.append(task_id)
            log.info(f"Closed RUNNING task {task_id}")
        except Exception as e:
            log.warning(f"Failed to close RUNNING task {task_id}: {e}")

    return count, updated_ids


def main():
    log.info("supersede_legal_radar_v1.py: scanning for v1 Legal Radar tasks")

    try:
        v1_tasks = find_v1_tasks()
    except Exception as e:
        log.warning(f"Failed to query v1 tasks: {e}", exc_info=True)
        return []

    if not v1_tasks:
        log.info("Found 0 tasks (Q queued, R running); updated 0 to superseded/closed")
        return []

    # Separate by state
    queued = [t for t in v1_tasks if t.get("state") == "QUEUED"]
    running = [t for t in v1_tasks if t.get("state") == "RUNNING"]

    # Transition each group
    q_updated, q_ids = supersede_queued_tasks(queued)
    r_updated, r_ids = close_running_tasks(running)

    all_updated_ids = q_ids + r_ids
    total_updated = q_updated + r_updated

    log.info(f"Found {len(v1_tasks)} tasks ({len(queued)} queued, {len(running)} running); "
             f"updated {total_updated} to superseded/closed")

    # Output: one task ID per line
    for task_id in all_updated_ids:
        print(task_id)

    return all_updated_ids


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except Exception as e:
        log.exception(f"Unhandled error: {e}")
        sys.exit(0)  # Always exit 0 (fail-soft pattern)
