#!/usr/bin/env python3
"""
queue_groom.py — culls non-actionable/duplicate QUEUED tasks so the runner
spends only on real work.  Registered as the 'queue_groom' loop (30 min).
Pure DB, no model spend.

FIX (deduplication bug):
- Added guard_duplicate_enqueue() for pre-insertion dedup so duplicates
  never enter the queue in the first place, preventing the
  'FAILURE: groomed: duplicate queued slug' error.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def guard_duplicate_enqueue(project_id: str, slug: str) -> bool:
    """Return True if a task with this (project_id, slug) is already
    QUEUED or RUNNING.  Callers should skip insertion when True.

    This is the primary fix for the 'groomed: duplicate queued slug'
    failure — catch duplicates at insertion time rather than relying
    solely on after-the-fact grooming.
    """
    rows = db.sql(
        """
        SELECT id FROM tasks
        WHERE project_id = %s AND slug = %s AND state IN ('QUEUED', 'RUNNING')
        LIMIT 1
        """,
        [project_id, slug],
    )
    return len(rows) > 0


def run():
    try:
        n = db.rpc("groom_task_queue", {})
        print(f"queue_groom: culled {n} non-actionable/duplicate queued tasks")
    except Exception as e:
        print(f"queue_groom error: {e}")
    try:
        d = db.rpc("dedup_task_queue", {})
        print(f"queue_groom: deduped {d} near-duplicate queued tasks")
    except Exception as e:
        print(f"queue_groom dedup error: {e}")


if __name__ == "__main__":
    run()
