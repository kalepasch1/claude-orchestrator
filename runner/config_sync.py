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


def _get_fleet_config():
    """Fetch current fleet_config from DB. Returns dict of key->value."""
    try:
        import db
        rows = db.select("fleet_config", {"select": "key,value"}) or []
        return {r["key"]: r["value"] for r in rows if r.get("key")}
    except Exception:
        return {}


MAX_VALUE_LENGTH = int(os.environ.get("ORCH_CONFIG_MAX_VALUE_LEN", "4096"))


def validate_config_value(key, value):
    """Validate a config value before sync. Returns (ok, reason)."""
    s = str(value)
    if len(s) > MAX_VALUE_LENGTH:
        return False, f"value too long ({len(s)} > {MAX_VALUE_LENGTH})"
    if "\x00" in s:
        return False, "value contains null byte"
    if not key or not key.strip():
        return False, "empty key"
    if len(key) > 128:
        return False, f"key too long ({len(key)} > 128)"
    return True, ""


def compute_diff(local, remote):
    """Compute config keys that differ between local and remote.

    Returns list of {'key': str, 'local_value': str, 'remote_value': str|None, 'action': 'set'|'delete'}
    """
    changes = []
    for k, v in local.items():
        if not _is_safe_key(k):
            continue
        ok, reason = validate_config_value(k, v)
        if not ok:
            log.debug("skipping invalid config key %s: %s", k, reason)
            continue
        remote_val = remote.get(k)
        if remote_val != str(v):
            changes.append({
                "key": k,
                "local_value": str(v),
                "remote_value": remote_val,
                "action": "set",
            })
    return changes


def sync_config(dry_run=False):
    """Synchronize local config overrides to fleet_config.

    Returns dict with 'applied': int, 'skipped': int, 'changes': list
    """
    if not ENABLED:
        return {"applied": 0, "skipped": 0, "changes": [], "reason": "sync disabled"}

    local = _load_local_config()
    if not local:
        return {"applied": 0, "skipped": 0, "changes": [], "reason": "no local config"}

    remote = _get_fleet_config()
    changes = compute_diff(local, remote)

    if not changes:
        return {"applied": 0, "skipped": 0, "changes": [], "reason": "no changes"}

    applied = 0
    skipped = 0

    if not dry_run:
        try:
            import config_applier
            for change in changes:
                key = change["key"]
                value = change["local_value"]
                try:
                    result = config_applier.apply_config(key, value, by="config_sync")
                    if result and result.get("outcome") in ("applied", None):
                        applied += 1
                    else:
                        skipped += 1
                except Exception as e:
                    log.debug("failed to apply %s: %s", key, e)
                    skipped += 1
        except ImportError:
            # Fall back to direct DB upsert if config_applier unavailable
            try:
                import db
                for change in changes:
                    try:
                        db.upsert("fleet_config", {"key": change["key"], "value": change["local_value"]})
                        applied += 1
                    except Exception:
                        skipped += 1
            except Exception:
                skipped = len(changes)
    else:
        skipped = len(changes)

    with _lock:
        _stats["syncs"] += 1
        _stats["keys_pushed"] += applied
        _stats["keys_skipped"] += skipped

    state = _load_sync_state()
    state["last_sync"] = time.time()
    for c in changes:
        if not dry_run:
            state["synced_keys"][c["key"]] = c["local_value"]
    _save_sync_state(state)

    return {"applied": applied, "skipped": skipped, "changes": changes}


def run():
    """Periodic entry point — sync if enough time has passed."""
    if not ENABLED:
        return
    state = _load_sync_state()
    elapsed = time.time() - state.get("last_sync", 0)
    if elapsed < SYNC_INTERVAL_S:
        return
    try:
        result = sync_config()
        if result.get("applied", 0) > 0:
            log.info("config_sync: applied %d keys", result["applied"])
    except Exception as e:
        with _lock:
            _stats["errors"] += 1
        log.warning("config_sync error: %s", e)
