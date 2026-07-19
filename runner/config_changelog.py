#!/usr/bin/env python3
"""
config_changelog.py — Track config changes with audit trail.

Records every config mutation to a changelog table for debugging and rollback.
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def log_change(key, old_value, new_value, source="manual", actor="unknown"):
    """Record a config change to the audit log."""
    try:
        db.insert("config_changelog", {
            "config_key": key,
            "old_value": json.dumps(old_value, default=str) if old_value is not None else None,
            "new_value": json.dumps(new_value, default=str),
            "source": source,
            "actor": actor,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    except Exception:
        # Table may not exist yet; fail silently
        pass


def recent_changes(limit=20):
    """Fetch recent config changes."""
    try:
        return db.select("config_changelog", {
            "order": "created_at.desc",
            "limit": limit,
        }) or []
    except Exception:
        return []


def rollback_last(key):
    """Rollback the most recent change to a config key."""
    changes = []
    try:
        changes = db.select("config_changelog", {
            "config_key": f"eq.{key}",
            "order": "created_at.desc",
            "limit": 1,
        }) or []
    except Exception:
        return None

    if not changes:
        return None

    last = changes[0]
    old_val = last.get("old_value")
    if old_val is None:
        return None

    try:
        parsed = json.loads(old_val)
    except (json.JSONDecodeError, TypeError):
        parsed = old_val

    try:
        db.insert("fleet_config", {"key": key, "value": json.dumps(parsed, default=str)}, upsert=True)
        log_change(key, last.get("new_value"), old_val, source="rollback", actor="config_changelog")
        return {"key": key, "rolled_back_to": old_val}
    except Exception:
        return None
