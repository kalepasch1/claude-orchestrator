#!/usr/bin/env python3
"""
monitoring_feedback.py — real-time monitoring feedback integration.

Collects task state changes and surfaces them as a feed for the Supabase
dashboard. Writes feedback entries to the `monitoring_feed` table so the
web UI can poll/subscribe for live updates.

Fail-soft: returns empty results on error; never raises.
"""
import os
import sys
import time
import json
import datetime
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("monitoring_feedback")

FEED_TABLE = "monitoring_feed"
MAX_FEED_AGE_HOURS = int(os.environ.get("ORCH_FEED_AGE_HOURS", "24"))


def record_state_change(db, task_id, old_state, new_state, account="", detail=""):
    """Record a task state change to the monitoring feed.

    Args:
        db: the db module (must have .insert()).
        task_id: task UUID.
        old_state: previous state string.
        new_state: new state string.
        account: executor account name.
        detail: optional detail string.

    Returns:
        True on success, False on failure.
    """
    try:
        entry = {
            "task_id": task_id,
            "old_state": old_state or "",
            "new_state": new_state or "",
            "account": account or "",
            "detail": (detail or "")[:1000],
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
        db.insert(FEED_TABLE, entry)
        return True
    except Exception as exc:
        log.warning("record_state_change error: %s", exc)
        return False


def get_recent_feed(db, limit=50, hours=None):
    """Fetch recent monitoring feed entries.

    Args:
        db: the db module (must have .select()).
        limit: max entries to return.
        hours: only return entries from the last N hours (default: MAX_FEED_AGE_HOURS).

    Returns:
        list of feed entry dicts, newest first.
    """
    if hours is None:
        hours = MAX_FEED_AGE_HOURS
    try:
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat() + "Z"
        rows = db.select(FEED_TABLE, {
            "select": "task_id,old_state,new_state,account,detail,created_at",
            "created_at": f"gte.{cutoff}",
            "order": "created_at.desc",
            "limit": str(limit),
        }) or []
        return rows
    except Exception as exc:
        log.warning("get_recent_feed error: %s", exc)
        return []


def build_summary(feed_entries):
    """Build a summary of state transitions from feed entries.

    Returns dict with counts per transition type.
    """
    summary = {}
    try:
        for entry in (feed_entries or []):
            transition = f"{entry.get('old_state', '?')} -> {entry.get('new_state', '?')}"
            summary[transition] = summary.get(transition, 0) + 1
    except Exception:
        pass
    return summary
