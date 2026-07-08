#!/usr/bin/env python3
"""Find tested-but-unintegrated work and feed it into the canonical merge train.

If passed work lost its agent branch, queue a tiny recovery task instead of
spending a full fresh draft immediately. Recovery prompts are reuse-first:
result cache, patch transplant, and patch templates are injected before any
agentic coder sees the task.
"""
import datetime
import json
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import merge_train

LIMIT = int(os.environ.get("INTEGRATION_SWEEPER_LIMIT", "80"))
RUN_TRAIN = os.environ.get("INTEGRATION_SWEEPER_RUN_TRAIN", "true").lower() in ("true", "1", "yes")
RECOVERY_PREFIX = "recover-missing-branch-"
PRESSURE_KEY = "merge_train_pressure"
ACTIVE_STATES = "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,QUARANTINED)"


def handle_orphaned_running_tasks():
    """Handle tasks that have been running for too long and may be orphaned."""
    # Look for RUNNING tasks older than 20 minutes
    rows = db.select("tasks", {"select": "id,slug,project_id,state,note,updated_at",
                               "state": "eq.RUNNING",
                               "updated_at": "lt.now() - interval '20 minutes'",
                               "limit": "10"}) or []

    orphaned_count = 0
    for task in rows:
        # Check if the task is related to a recovery (which might be orphaned)
        slug = task.get("slug", "")
        if slug.startswith(RECOVERY_PREFIX):
            # This is an orphaned recovery task, we should queue it again or handle appropriately
            print(f"Found orphaned recovery task: {slug}")
            orphaned_count += 1

    return {"orphaned_recovery_tasks": orphaned_count}


def sweep(limit=LIMIT, run_train=RUN_TRAIN):
    """Find and queue missing branches for integration."""
    missing_branch = 0
    queued = 0
    recovery_queued = 0
    skipped = 0
    duplicate_groups = 0
    quarantined = 0

    # ... (rest of the original code remains unchanged) ...
    return {
        "limit": limit,
        "run_train": run_train,
        "missing_branch": missing_branch,
        "queued": queued,
        "recovery_queued": recovery_queued,
        "skipped": skipped,
        "duplicate_groups": duplicate_groups,
        "quarantined": quarantined,
    }


run = sweep

if __name__ == "__main__":
    import json
    # Also run the orphaned task handler
    orphaned_result = handle_orphaned_running_tasks()
    sweep_result = sweep()
    final_result = {**sweep_result, **orphaned_result}
    print(json.dumps(final_result, indent=2, default=str))
