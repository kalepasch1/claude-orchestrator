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
    # Was `db.sql("SELECT ... WHERE project_id = %s ...", [project_id, slug])`.
    # db has no sql(): it is a PostgREST client and has never had a raw-SQL
    # channel, and the %s/list placeholders are psycopg2's, a driver this repo
    # does not use.  So this guard — "the primary fix for the 'groomed:
    # duplicate queued slug' failure" — raised AttributeError on every call,
    # unguarded, from its first day.  The equivalent PostgREST read:
    rows = db.select("tasks", {
        "select": "id",
        "project_id": f"eq.{project_id}",
        "slug": f"eq.{slug}",
        "state": "in.(QUEUED,RUNNING)",
        "limit": "1",
    }) or []
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
