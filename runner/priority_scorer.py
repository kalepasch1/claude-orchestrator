#!/usr/bin/env python3
"""
priority_scorer.py - assign meaningful priority scores to QUEUED tasks.

95.4% of queued tasks have priority=1000 (the default). claim_task() already sorts by
priority but values were never assigned. This module scores tasks based on kind, slug
prefix, dependency state, and age so the claim ordering reflects actual urgency.

Lower priority = higher urgency (claimed sooner).

Periodic job interface: call run() from periodic.py.
"""
import os, sys, time, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Cap per invocation to avoid long-running sweeps
SCORE_CAP = int(os.environ.get("ORCH_PRIORITY_SCORE_CAP", "500"))
BATCH_SIZE = int(os.environ.get("ORCH_PRIORITY_SCORE_BATCH", "50"))


def score_task(task_row):
    """Return an integer priority for a task row (lower = higher priority).

    Considers kind, slug prefix, dependency state, and age.
    """
    slug = str(task_row.get("slug") or "").lower()
    kind = str(task_row.get("kind") or "").lower()
    deps = task_row.get("deps")
    created_at = task_row.get("created_at") or ""

    # --- Base score from slug prefix (checked first, most specific) ---
    if slug.startswith(("cont-", "batch-mech")):
        base = 900
    elif slug.startswith(("qafix-", "relfix-", "buildfix-", "deployfix-")):
        base = 10
    elif slug.startswith("rework-"):
        base = 15
    elif slug.startswith("recover-"):
        base = 25
    elif slug.startswith("improve-"):
        base = 35
    # --- Base score from kind ---
    elif kind == "bugfix":
        base = 10
    elif kind == "test":
        base = 20
    elif kind in ("cleanup", "chore"):
        base = 30
    else:
        base = 50

    # --- Modifiers ---
    # Dependency boost: ready-to-run tasks (no blockers) get a small boost
    if not deps or (isinstance(deps, list) and len(deps) == 0):
        base -= 5
    elif isinstance(deps, str):
        try:
            parsed = json.loads(deps)
            if not parsed:
                base -= 5
        except Exception:
            pass

    # Age-based starvation prevention
    age_days = _age_days(created_at)
    if age_days > 7:
        base -= 10
    elif age_days > 3:
        base -= 5

    # Floor at 1 (priority must be positive for ordering sanity)
    return max(1, base)


def _age_days(created_at):
    """Return task age in days from its created_at ISO timestamp."""
    if not created_at:
        return 0
    try:
        from datetime import datetime, timezone
        ts = created_at.replace("Z", "+00:00")
        if "+" not in ts and ts[-1] != "Z":
            ts += "+00:00"
        dt = datetime.fromisoformat(ts)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return 0


def score_backlog():
    """Query all QUEUED tasks with priority=1000, score them, batch-update.

    Returns dict with {scored, updated} counts.
    """
    scored = 0
    updated = 0

    try:
        tasks = db.select("tasks", {
            "select": "id,slug,kind,deps,created_at,priority",
            "state": "eq.QUEUED",
            "priority": "eq.1000",
            "order": "created_at.asc",
            "limit": str(SCORE_CAP),
        }) or []
    except Exception as e:
        print(f"[priority-scorer] query failed: {e}")
        return {"scored": 0, "updated": 0}

    if not tasks:
        print("[priority-scorer] no default-priority tasks to score")
        return {"scored": 0, "updated": 0}

    batch = []
    for t in tasks:
        try:
            new_priority = score_task(t)
        except Exception:
            continue
        scored += 1
        if new_priority != 1000:
            batch.append((t["id"], new_priority))

        # Flush in groups of BATCH_SIZE
        if len(batch) >= BATCH_SIZE:
            updated += _flush_batch(batch)
            batch = []

    # Flush remaining
    if batch:
        updated += _flush_batch(batch)

    print(f"[priority-scorer] scored={scored} updated={updated} (of {len(tasks)} queued with default priority)")
    return {"scored": scored, "updated": updated}


def _flush_batch(batch):
    """Update a batch of (task_id, new_priority) pairs. Returns count of successful updates."""
    count = 0
    for tid, priority in batch:
        try:
            db.update("tasks", {"id": tid}, {"priority": priority})
            count += 1
        except Exception:
            pass
    return count


def run():
    """Periodic job entry point."""
    return score_backlog()


if __name__ == "__main__":
    result = run()
    print(f"priority_scorer: {result}")
