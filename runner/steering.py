#!/usr/bin/env python3
"""
steering.py - attributed steering_events writer (Wave-0 review gate, spec item 4).

Every human steering act (release decisions, approval rationales, fleet control,
kill-switch flips, clarification answers, redirects) becomes a first-class
`steering_events` row so attribution and downstream routing (hivemind item 5)
have a single substrate. Fail-soft by design: a steering write must never break
the caller (release train, fleet control, approval endpoints).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

EVENT_TYPES = {"clarification_answer", "redirect", "approval_rationale",
               "fleet_control", "kill_switch", "release_decision"}


def record(event_type, project=None, task_id=None, approval_id=None,
           actor_id=None, actor_label=None, rationale=None, payload=None):
    """Insert one steering_events row. Returns the row or None (never raises)."""
    if event_type not in EVENT_TYPES:
        return None
    row = {"event_type": event_type, "payload": payload or {}}
    if project:
        row["project"] = str(project)[:200]
    if task_id:
        row["task_id"] = task_id
    if approval_id:
        row["approval_id"] = approval_id
    if actor_id:
        row["actor_id"] = actor_id
    if actor_label:
        row["actor_label"] = str(actor_label)[:200]
    if rationale:
        row["rationale"] = str(rationale)[:4000]
    try:
        return db.insert("steering_events", row)
    except Exception:
        return None


def record_once(event_type, approval_id, **kw):
    """record(), but at most one row per (approval_id, event_type) — the release
    train observes an approved card on every cycle until the release completes."""
    if not approval_id:
        return record(event_type, **kw)
    try:
        existing = db.select("steering_events", {
            "select": "id", "approval_id": f"eq.{approval_id}",
            "event_type": f"eq.{event_type}", "limit": "1"}) or []
        if existing:
            return None
    except Exception:
        pass
    return record(event_type, approval_id=approval_id, **kw)
