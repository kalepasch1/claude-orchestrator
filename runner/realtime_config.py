#!/usr/bin/env python3
"""realtime_config.py — Real-time fleet configuration via Supabase polling.

Provides a lightweight config watcher that detects fleet_config changes
and applies them immediately, rather than waiting for the next full loop tick.

Uses a change-detection approach: hashes the current config state and
re-applies only when a change is detected. This is cheaper than full
Supabase Realtime websocket but gives near-instant config propagation
(poll interval configurable, default 5s).

Integration: call realtime_config.start() from the runner's main init,
or call realtime_config.poll() from the main loop for synchronous mode.
"""
import hashlib
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

POLL_INTERVAL_S = float(os.environ.get("ORCH_REALTIME_POLL_S", "5"))
_state = {"hash": "", "running": False, "last_apply": 0.0}
_lock = threading.Lock()

# Only these prefixes are applied (mirrors fleet_control.py safety list)
_SAFE_PREFIXES = ("ORCH_", "MAX_PARALLEL", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_",
                  "RELEASE_", "QUEUE_", "CONT_", "JANITOR_", "REMEDIATION_",
                  "DEFAULT_TEST_CMD", "TASK_TIMEOUT", "ENABLE_", "SESSION_",
                  "ACCOUNT_COOLDOWN", "MERGE_", "DEPLOY_", "INTEGRATE_", "COST_")
_DENY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL")


def _safe_key(k):
    ku = k.upper()
    if any(m in ku for m in _DENY_MARKERS):
        return False
    return any(ku.startswith(p) for p in _SAFE_PREFIXES)


def _fetch_config():
    """Fetch all fleet_config rows, return sorted list of (key, value)."""
    try:
        rows = db.select("fleet_config", {"select": "key,value", "order": "key.asc"}) or []
        return [(r["key"], str(r.get("value", ""))) for r in rows if r.get("key")]
    except Exception:
        return []


def _config_hash(pairs):
    """Deterministic hash of config state for change detection."""
    raw = json.dumps(pairs, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()


def poll():
    """Check for config changes and apply if detected. Returns count of keys applied."""
    pairs = _fetch_config()
    h = _config_hash(pairs)

    with _lock:
        rows = db.sql("SELECT key, value FROM fleet_config") or []
        _cache = {r["key"]: r["value"] for r in rows}
        _cache_ts = time.time()

def force_refresh():
    """
    Forces an immediate refresh of the configuration cache from the database.
    This can be used to ensure the latest configuration is loaded without waiting for the TTL.
    """
    _refresh()
