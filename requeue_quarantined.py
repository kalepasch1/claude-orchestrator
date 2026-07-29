#!/usr/bin/env python3
"""Requeue the mass-quarantined dropbox tasks (lease-RPC casualty cohort), excluding the
5 deliberately-parked monoliths and canary tasks. Resets attempt counters so the retry
budget starts fresh under the fixed heartbeat.
Run:  python3 ~/Documents/beethoven/claude-orchestrator/requeue_quarantined.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner"))
import db

rows = db.select("tasks", {
    "select": "id,slug,note,state",
    "state": "eq.QUARANTINED",
    "slug": "like.dropbox-*",
    "created_at": "gte.2026-07-28T06:00:00",
    "limit": "500"}) or []

requeued = skipped = 0
for r in rows:
    note = (r.get("note") or "")
    if "monolith superseded" in note:
        skipped += 1
        continue
    try:
        db.update("tasks", {"id": r["id"]}, {
            "state": "QUEUED", "attempt": 0,
            "note": "requeued 2026-07-28: quarantined by lease-RPC infra error (now fail-soft)"})
        requeued += 1
    except Exception as e:
        print("ERROR", r["slug"][:60], e)
print(f"requeued={requeued}  kept-parked(monoliths)={skipped}  of {len(rows)} quarantined dropbox tasks")
