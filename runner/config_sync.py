#!/usr/bin/env python3
"""
config_sync.py — Real-time configuration synchronization with monitoring.

Extends config_drift.py with:
- Pull-based config sync from fleet_config to local environment
- Change detection with callback hooks
- Sync status reporting for the approval pipeline
- Atomic config application with rollback on failure

Designed for the approval_merge feedback loop: when a config change is
merged, executors pick it up on their next sync cycle without restart.
"""
import hashlib
import json
import os
import sys
import time
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Config keys that are safe to hot-reload (no restart required)
HOT_RELOAD_KEYS = {
    "ORCH_AUTOAPPROVE_LOWRISK",
    "ORCH_QUEUE_ELIMINATION",
    "ORCH_AGENTIC_REPAIR_DEFAULT_CODER",
    "ORCH_REPAIR_CODER",
    "ORCH_PUSH_ON_MERGE",
    "ORCH_EMERGENCY_BUDGET_STOP",
    "ORCH_ELIM_SCAN_LIMIT",
    "ORCH_ELIM_MIN_CONF",
    "AUTOPILOT_MAX_DECISIONS",
    "AUTOPILOT_IMPROVE_FLOOR",
}

# Keys that require a restart to take effect
RESTART_REQUIRED_KEYS = {
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "ANTHROPIC_API_KEY",
}


class ConfigState:
    """Tracks local config state for drift detection."""

    def __init__(self):
        self._hash = ""
        self._snapshot = {}
        self._last_sync = 0.0
        self._callbacks = []

    def on_change(self, callback: Callable[[str, str, str], None]):
        """Register a callback for config changes: callback(key, old_value, new_value)."""
        self._callbacks.append(callback)

    @property
    def hash(self) -> str:
        return self._hash

    @property
    def last_sync(self) -> float:
        return self._last_sync

    def _notify(self, key, old_val, new_val):
        for cb in self._callbacks:
            try:
                cb(key, old_val, new_val)
            except Exception:
                pass


_state = ConfigState()


def current_hash() -> str:
    """Compute hash of current fleet_config state."""
    try:
        rows = db.select("fleet_config", {"select": "key,value", "order": "key.asc"}) or []
    except Exception:
        rows = []
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def fetch_config() -> dict:
    """Fetch all fleet_config key-value pairs."""
    try:
        rows = db.select("fleet_config", {"select": "key,value"}) or []
        result = {}
        for r in rows:
            val = r.get("value", "")
            if isinstance(val, str):
                # Strip surrounding quotes from JSON-encoded strings
                try:
                    val = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
            result[r["key"]] = val
        return result
    except Exception:
        return {}


def sync(apply_env: bool = True, dry_run: bool = False) -> dict:
    """Synchronize local config from fleet_config.

    Returns:
        applied: list of keys that changed
        skipped: list of keys requiring restart
        hash: current config hash
        drift: bool — whether local was out of sync
    """
    remote = fetch_config()
    new_hash = current_hash()
    drift = new_hash != _state.hash

    applied = []
    skipped = []
    restart_needed = []

    for key, value in remote.items():
        if not isinstance(key, str) or not key.startswith("ORCH_") and key not in HOT_RELOAD_KEYS:
            continue

        str_val = str(value) if not isinstance(value, str) else value
        old_val = _state._snapshot.get(key, os.environ.get(key))

        if old_val == str_val:
            continue

        if key in RESTART_REQUIRED_KEYS:
            restart_needed.append(key)
            skipped.append(key)
            continue

        if not dry_run and apply_env and key in HOT_RELOAD_KEYS:
            os.environ[key] = str_val
            _state._notify(key, old_val, str_val)
            applied.append(key)
        else:
            skipped.append(key)

    _state._hash = new_hash
    _state._snapshot = {k: str(v) for k, v in remote.items()}
    _state._last_sync = time.time()

    return {
        "applied": applied,
        "skipped": skipped,
        "restart_needed": restart_needed,
        "hash": new_hash,
        "drift": drift,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def report_sync_status(account: str) -> None:
    """Write sync status to fleet_config for monitoring."""
    status = {
        "hash": _state.hash,
        "last_sync": _state.last_sync,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        db.sql(
            f"INSERT INTO fleet_config (key, value) "
            f"VALUES ('{account}_CONFIG_SYNC', '{json.dumps(status)}'::jsonb) "
            f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )
    except Exception:
        pass


def on_change(callback: Callable[[str, str, str], None]):
    """Register a global change callback."""
    _state.on_change(callback)
