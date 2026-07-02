#!/usr/bin/env python3
"""queue_groom.py — culls non-actionable/duplicate QUEUED tasks so the runner spends only on real
work. Registered as the 'queue_groom' loop (30 min). Pure DB, no model spend."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def run():
    try:
        n = db.rpc("groom_task_queue", {})
        print(f"queue_groom: culled {n} non-actionable/duplicate queued tasks")
    except Exception as e:
        print(f"queue_groom error: {e}")


if __name__ == "__main__":
    run()
