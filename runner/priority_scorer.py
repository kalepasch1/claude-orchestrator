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
#: A task older than this is re-scored so its age discount is not frozen at the
#: value it had on the pass right after it was queued. Matches the first age
#: threshold in score_task, so a task becomes eligible on the day its score
#: actually changes rather than some arbitrary time later.
RESCORE_AFTER_DAYS = int(os.environ.get("ORCH_PRIORITY_RESCORE_AFTER_DAYS", "3"))


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
    """Score QUEUED tasks: the never-scored ones, and aged ones that have drifted.

    Returns dict with {scored, updated} counts.

    WHY THIS SCANS MORE THAN priority=1000
    --------------------------------------
    score_task applies an age discount — 5 points past three days, 10 past seven
    — under the heading "Age-based starvation prevention". It never fired for a
    single task.

    The scan selected `priority=eq.1000`: tasks that have never been scored. A
    task is scored once, on the pass after it is queued, when its age is roughly
    zero. From that moment its priority is no longer 1000, so it never matches
    the query again and its age discount is frozen at the value it had on day
    one. The mechanism was unreachable for precisely the tasks it exists to
    protect — the ones that sit.

    So the scan also picks up QUEUED tasks older than RESCORE_AFTER_DAYS, and
    _apply() only ever moves a priority DOWN. See _apply for why that direction
    is not an optimisation but the safety property that makes rescoring safe.
    """
    scored = 0
    updated = 0

    tasks = _fetch_unscored() + _fetch_aged()
    if not tasks:
        print("[priority-scorer] nothing to score")
        return {"scored": 0, "updated": 0}

    seen = set()
    batch = []
    for t in tasks:
        tid = t.get("id")
        if tid in seen:          # a task can be both unscored and aged
            continue
        seen.add(tid)
        try:
            new_priority = score_task(t)
        except Exception:
            continue
        scored += 1
        if _should_apply(t, new_priority):
            batch.append((tid, new_priority))

        # Flush in groups of BATCH_SIZE
        if len(batch) >= BATCH_SIZE:
            updated += _flush_batch(batch)
            batch = []

    # Flush remaining
    if batch:
        updated += _flush_batch(batch)

    print(f"[priority-scorer] scored={scored} updated={updated} (of {len(seen)} queued tasks examined)")
    return {"scored": scored, "updated": updated}


def _fetch_unscored():
    """QUEUED tasks still carrying the default priority."""
    try:
        return db.select("tasks", {
            "select": "id,slug,kind,deps,created_at,priority",
            "state": "eq.QUEUED",
            "priority": "eq.1000",
            "order": "created_at.asc",
            "limit": str(SCORE_CAP),
        }) or []
    except Exception as e:
        print(f"[priority-scorer] unscored query failed: {e}")
        return []


def _fetch_aged():
    """QUEUED tasks old enough that their age discount has moved since scoring.

    Oldest first: if the cap truncates the page, the tasks that have waited
    longest are the ones that get their discount, which is the whole point.
    """
    cutoff = _cutoff_iso(RESCORE_AFTER_DAYS)
    if not cutoff:
        return []
    try:
        return db.select("tasks", {
            "select": "id,slug,kind,deps,created_at,priority",
            "state": "eq.QUEUED",
            "created_at": f"lt.{cutoff}",
            "order": "created_at.asc",
            "limit": str(SCORE_CAP),
        }) or []
    except Exception as e:
        print(f"[priority-scorer] aged query failed: {e}")
        return []


def _cutoff_iso(days):
    """ISO timestamp `days` in the past, or None if it cannot be computed."""
    try:
        from datetime import datetime, timedelta, timezone
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    except Exception:
        return None


def _should_apply(task, new_priority):
    """Write the new priority only when it is strictly more urgent than the old.

    Lower is more urgent, so this is a one-way ratchet toward the front of the
    queue, and it is a safety property rather than a tweak:

      * Anything that set a priority by hand, or by a rule this scorer does not
        know, keeps it. Rescoring cannot undo a deliberate escalation by
        recomputing a blander number over the top of it.
      * Rescoring is idempotent. A second pass over an unchanged task computes
        the same value and writes nothing, so the periodic job does not churn
        the table or the change stream.
      * Starvation prevention still works, because ageing only ever lowers the
        score. The one direction that mattered is the one direction allowed.
    """
    if new_priority == 1000:
        return False
    try:
        current = int(task.get("priority"))
    except (TypeError, ValueError):
        return True
    return new_priority < current


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
