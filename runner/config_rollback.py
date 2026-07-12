#!/usr/bin/env python3
"""
config_rollback.py - Automatic rollback for config changes on error spikes.

Snapshots config state before changes. If error_monitor detects a spike
after the grace period, rolls back to previous value automatically.

Env:
    ORCH_CONFIG_ROLLBACK_ENABLED   (default "true")
    ORCH_ROLLBACK_GRACE_SEC        (default "120")
    ORCH_ROLLBACK_ERROR_THRESHOLD  (default "3")
"""
import os, sys, time, threading, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ENABLED = os.environ.get("ORCH_CONFIG_ROLLBACK_ENABLED", "true").lower() in ("true", "1")
_GRACE = int(os.environ.get("ORCH_ROLLBACK_GRACE_SEC", "120"))
_ERR_THRESH = int(os.environ.get("ORCH_ROLLBACK_ERROR_THRESHOLD", "3"))

_lock = threading.Lock()
_snapshots: dict = {}
_rollback_log: list = []


def snapshot_config(key: str, old_value: str) -> None:
    """Record config state before a change. Fail-soft."""
    if not _ENABLED:
        return
    try:
        with _lock:
            _snapshots[key] = {"old_value": old_value, "changed_at": time.time()}
    except Exception:
        pass


def check_and_rollback() -> list:
    """Evaluate recent config changes against error rates. Auto-rollback if needed.
    Returns list of rollback actions. Fail-soft."""
    if not _ENABLED:
        return []
    actions = []
    try:
        import error_monitor
        status = error_monitor.check_and_alert()
        if status.get("ok", True):
            return []
        now = time.time()
        with _lock:
            candidates = {k: v for k, v in _snapshots.items()
                          if now - v["changed_at"] > _GRACE}
        if not candidates:
            return []
        import db
        for key, snap in candidates.items():
            if status.get("error_count", 0) >= _ERR_THRESH:
                try:
                    db.upsert("fleet_config", {"key": key, "value": snap["old_value"]},
                              on_conflict="key")
                    os.environ[key] = str(snap["old_value"])
                    action = {"action": "rolled_back", "key": key,
                              "to_value": snap["old_value"],
                              "reason": f"error spike ({status['error_count']} errors)"}
                    actions.append(action)
                    _rollback_log.append({**action, "timestamp": now})
                    with _lock:
                        _snapshots.pop(key, None)
                except Exception:
                    pass
    except Exception:
        pass
    return actions


def clear_snapshot(key: str) -> None:
    """Remove a snapshot after confirmed stability."""
    with _lock:
        _snapshots.pop(key, None)


def stats() -> dict:
    """Return rollback module state."""
    with _lock:
        return {"enabled": _ENABLED, "pending_snapshots": len(_snapshots),
                "rollbacks_performed": len(_rollback_log),
                "recent_rollbacks": _rollback_log[-5:]}
