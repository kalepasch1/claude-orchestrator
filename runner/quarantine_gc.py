#!/usr/bin/env python3
"""
quarantine_gc.py - garbage-collect non-recoverable quarantined tasks.

2,588 QUARANTINED tasks with notes matching "PATCH TEMPLATE", "dedup", "duplicate",
etc. slow every materializer and claim_task scan. This module marks them so they
are excluded from future scans without requiring a new enum value.

Strategy: prefix the note with "GC:" so future queries can filter with
  note=not.like.GC:*
If the DB has an ARCHIVED state, use that instead (tried first, falls back to
note-prefixing on enum violation).

Periodic job interface: call run() from periodic.py.
"""
import os, sys, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

GC_CAP = int(os.environ.get("ORCH_QUARANTINE_GC_CAP", "200"))

# Patterns that indicate non-recoverable quarantined tasks
_GC_PATTERNS = re.compile(
    r"PATCH TEMPLATE|patch-template-corrupt|"
    r"\bdedup\b|duplicate|semantic-dedupe",
    re.I,
)


def gc_quarantine():
    """Find and GC non-recoverable QUARANTINED tasks.

    Returns dict with {found, archived} counts.
    """
    try:
        candidates = db.select("tasks", {
            "select": "id,slug,note,state",
            "state": "eq.QUARANTINED",
            "order": "created_at.asc",
            "limit": str(GC_CAP * 3),  # fetch extra, filter in Python
        }) or []
    except Exception as e:
        print(f"[quarantine-gc] query failed: {e}")
        return {"found": 0, "archived": 0}

    # Filter to only tasks matching GC patterns, and skip already-GC'd tasks
    gc_tasks = []
    for t in candidates:
        note = t.get("note") or ""
        if note.startswith("GC:"):
            continue  # already processed
        if _GC_PATTERNS.search(note):
            gc_tasks.append(t)
        if len(gc_tasks) >= GC_CAP:
            break

    if not gc_tasks:
        print("[quarantine-gc] no non-recoverable quarantined tasks to GC")
        return {"found": 0, "archived": 0}

    archived = 0
    # Try ARCHIVED state first (one task as canary)
    use_archived_state = False
    if gc_tasks:
        try:
            result = db.update("tasks", {"id": gc_tasks[0]["id"]}, {
                "state": "ARCHIVED",
                "note": f"GC: {(gc_tasks[0].get('note') or '')[:480]}",
            })
            if result is not None:
                use_archived_state = True
                archived += 1
        except Exception:
            # ARCHIVED not a valid enum value — fall back to note-prefixing
            use_archived_state = False

    start_idx = 1 if use_archived_state and archived else 0
    for t in gc_tasks[start_idx:]:
        tid = t.get("id")
        note = t.get("note") or ""
        try:
            if use_archived_state:
                db.update("tasks", {"id": tid}, {
                    "state": "ARCHIVED",
                    "note": f"GC: {note[:480]}",
                })
            else:
                # Note-prefix approach: keep state QUARANTINED but prefix note
                # so future scans can exclude with note=not.like.GC:*
                db.update("tasks", {"id": tid}, {
                    "note": f"GC: {note[:490]}",
                })
            archived += 1
        except Exception:
            # If ARCHIVED fails mid-batch (shouldn't happen), fall back
            if use_archived_state:
                try:
                    db.update("tasks", {"id": tid}, {
                        "note": f"GC: {note[:490]}",
                    })
                    archived += 1
                    use_archived_state = False  # stop trying ARCHIVED
                except Exception:
                    pass

    print(f"[quarantine-gc] found={len(gc_tasks)} archived={archived} "
          f"method={'ARCHIVED state' if use_archived_state else 'note prefix'}")
    return {"found": len(gc_tasks), "archived": archived}


def run():
    """Periodic job entry point."""
    return gc_quarantine()


if __name__ == "__main__":
    result = run()
    print(f"quarantine_gc: {result}")
