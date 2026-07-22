#!/usr/bin/env python3
"""
fleet_config_dao.py - data access for the fleet_config table.

Thin CRUD wrapper around db.py. Does not apply config to env — use
fleet_control.load_config() for that.

An optional change hook (_change_hook) fires immediately after a successful
write so callers can get sub-millisecond notification (before the next watcher
poll cycle). The watcher is still the authoritative source for out-of-band DB
changes; the hook is purely a fast-path optimisation.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_change_hook = None   # callable(old, new, change_type) or None


def set_change_hook(hook):
    """Register a callback invoked immediately after every successful write."""
    global _change_hook
    _change_hook = hook


def get_all():
    """Return all fleet_config rows as a list of dicts."""
    try:
        return db.select("fleet_config", {"select": "*"}) or []
    except Exception:
        return []


def get(key):
    """Return the fleet_config row for key, or None."""
    try:
        rows = db.select("fleet_config",
                         {"select": "*", "key": f"eq.{key}", "limit": "1"}) or []
        return rows[0] if rows else None
    except Exception:
        return None


def set_value(key, value, note=None, updated_by=None):
    """Upsert key=value in fleet_config.

    Returns (old_row_or_None, new_row_or_None). Captures old value before the
    write so change-stream consumers get accurate before/after context.
    Fires _change_hook immediately after a successful write.
    """
    old = get(key)
    row = {
        "key": key,
        "value": str(value),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if note is not None:
        row["note"] = note
    if updated_by is not None:
        row["updated_by"] = updated_by
    try:
        db.upsert("fleet_config", row)
    except Exception:
        return old, None
    new = get(key)
    hook = _change_hook
    if hook and new is not None:
        change_type = "created" if old is None else "updated"
        try:
            hook(old=old, new=new, change_type=change_type)
        except Exception:
            pass
    return old, new
