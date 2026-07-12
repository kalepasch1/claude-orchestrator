#!/usr/bin/env python3
"""
realtime_config_sync.py - push fleet-wide config changes in real-time via polling.

Uses frequent polling of the fleet_config table with change detection (ETag/hash)
to apply configuration changes to all machines with minimal delay, reducing the
need for manual pushes.

Integrates with fleet_control.py's existing safe-key filtering. Config changes
are detected by comparing a hash of all config rows against the last known hash.

Usage:
    import realtime_config_sync
    realtime_config_sync.start()   # starts background thread
    realtime_config_sync.stop()    # stops it
    realtime_config_sync.stats()   # monitoring
"""
import os, sys, time, threading, hashlib, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("realtime_config_sync")

_ENABLED = os.environ.get("ORCH_REALTIME_CONFIG_SYNC", "true").lower() == "true"
_POLL_INTERVAL = float(os.environ.get("ORCH_CONFIG_POLL_INTERVAL", "5"))  # seconds
_MIN_INTERVAL = 2.0

_lock = threading.Lock()
_thread = None
_running = False
_last_hash = ""
_stats_data = {
    "syncs": 0,
    "changes_applied": 0,
    "errors": 0,
    "last_sync_ts": 0.0,
    "last_change_ts": 0.0,
}


def _config_hash(rows):
    """Compute a deterministic hash of config rows for change detection."""
    if not rows:
        return ""
    canonical = json.dumps(sorted(
        [(r.get("key", ""), r.get("value", "")) for r in rows]
    ), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _apply_config(rows):
    """Apply config rows to environment, using fleet_control's safe-key filter."""
    try:
        import fleet_control
    except ImportError:
        _log.warning("fleet_control not importable; skipping apply")
        return 0
    applied = 0
    for row in (rows or []):
        k = row.get("key", "")
        v = row.get("value", "")
        if fleet_control._safe_key(k):
            old = os.environ.get(k)
            if old != v:
                os.environ[k] = v
                applied += 1
                _log.info("realtime config applied: %s = %s", k, v[:50])
    return applied


def _poll_loop():
    """Background thread: poll fleet_config and apply changes."""
    global _last_hash, _running
    import db
    interval = max(_MIN_INTERVAL, _POLL_INTERVAL)
    while _running:
        try:
            rows = db.select("fleet_config", {"select": "key,value"}) or []
            h = _config_hash(rows)
            with _lock:
                _stats_data["syncs"] += 1
                _stats_data["last_sync_ts"] = time.time()
            if h != _last_hash and _last_hash:
                applied = _apply_config(rows)
                with _lock:
                    _stats_data["changes_applied"] += applied
                    if applied:
                        _stats_data["last_change_ts"] = time.time()
                _log.info("config change detected, applied %d keys", applied)
            _last_hash = h
        except Exception as exc:
            with _lock:
                _stats_data["errors"] += 1
            _log.warning("realtime config poll error: %s", exc)
        time.sleep(interval)


def start():
    """Start the background config sync thread."""
    global _thread, _running
    if not _ENABLED:
        _log.info("realtime config sync disabled")
        return
    with _lock:
        if _running:
            return
        _running = True
    _thread = threading.Thread(target=_poll_loop, daemon=True, name="realtime-config-sync")
    _thread.start()
    _log.info("realtime config sync started (interval=%.1fs)", _POLL_INTERVAL)


def stop():
    """Stop the background config sync thread."""
    global _running
    _running = False
    if _thread:
        _thread.join(timeout=10)
    _log.info("realtime config sync stopped")


def stats():
    """Return sync statistics."""
    with _lock:
        return dict(_stats_data)
