#!/usr/bin/env python3
"""
config_sync_realtime.py — real-time configuration synchronization.

Improves on config_sync.py's polling model by adding mtime-based file
watching and DB change detection so config updates propagate within seconds
instead of waiting for the 300s polling interval.

Architecture:
  - Watches ~/.claude-orchestrator/config.local.json mtime every 2s
  - On change, immediately triggers sync_config() from config_sync
  - Watches fleet_config table for remote changes (via last-known hash)
  - Applies remote changes locally so all machines converge faster

Fail-soft: all errors logged, never raised. Thread-safe via _lock.
"""
import os
import sys
import json
import time
import hashlib
import logging
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("config_sync_realtime")

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
LOCAL_CONFIG = os.path.join(HOME, "config.local.json")
WATCH_INTERVAL_S = float(os.environ.get("ORCH_CONFIG_WATCH_INTERVAL_S", "2"))
REMOTE_POLL_INTERVAL_S = float(os.environ.get("ORCH_CONFIG_REMOTE_POLL_S", "10"))
ENABLED = os.environ.get("ORCH_CONFIG_REALTIME", "true").lower() == "true"

_lock = threading.Lock()
_stop_event = threading.Event()
_watcher_thread = None
_stats = {
    "local_changes_detected": 0,
    "remote_changes_detected": 0,
    "syncs_triggered": 0,
    "errors": 0,
}


def stats():
    with _lock:
        return dict(_stats)


def _file_mtime(path):
    """Get file mtime or 0 if missing."""
    try:
        return os.path.getmtime(path)
    except (OSError, FileNotFoundError):
        return 0


def _file_hash(path):
    """Get SHA-256 of file contents, or empty string if missing."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""


def _remote_config_hash():
    """Hash current fleet_config state for change detection."""
    try:
        import db
        rows = db.select("fleet_config", {"select": "key,value", "order": "key"}) or []
        blob = json.dumps([(r.get("key", ""), str(r.get("value", ""))) for r in rows],
                          sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()
    except Exception:
        return ""


def _apply_remote_to_local(remote_config):
    """Write remote fleet_config values into local config file for convergence.

    Only writes keys that pass the safety filter from config_sync.
    """
    try:
        from config_sync import _is_safe_key, _load_local_config
        local = _load_local_config()
        changed = False
        for k, v in remote_config.items():
            if not _is_safe_key(k):
                continue
            local_val = local.get(k)
            if local_val != str(v):
                local[k] = str(v)
                changed = True
        if changed:
            os.makedirs(HOME, exist_ok=True)
            with open(LOCAL_CONFIG, "w") as f:
                json.dump(local, f, indent=2)
        return changed
    except Exception as e:
        log.debug("apply_remote_to_local error: %s", e)
        return False


def _watch_loop():
    """Main watcher loop — runs in a background thread.

    Monitors local file mtime and remote config hash for changes.
    Triggers immediate sync when either changes.
    """
    last_mtime = _file_mtime(LOCAL_CONFIG)
    last_hash = _file_hash(LOCAL_CONFIG)
    last_remote_hash = ""
    last_remote_check = 0

    while not _stop_event.is_set():
        try:
            # Check local file for changes (fast — mtime + hash)
            current_mtime = _file_mtime(LOCAL_CONFIG)
            if current_mtime != last_mtime:
                current_hash = _file_hash(LOCAL_CONFIG)
                if current_hash != last_hash:
                    log.info("config_sync_realtime: local config changed, triggering sync")
                    with _lock:
                        _stats["local_changes_detected"] += 1
                    try:
                        from config_sync import sync_config
                        result = sync_config()
                        with _lock:
                            _stats["syncs_triggered"] += 1
                        if result.get("applied", 0) > 0:
                            log.info("realtime sync applied %d keys", result["applied"])
                    except Exception as e:
                        log.debug("realtime local sync error: %s", e)
                        with _lock:
                            _stats["errors"] += 1
                    last_hash = current_hash
                last_mtime = current_mtime


            # Check remote config periodically (slower — DB query)
            now = time.time()
            if now - last_remote_check >= REMOTE_POLL_INTERVAL_S:
                last_remote_check = now
                try:
                    current_remote_hash = _remote_config_hash()
                    if last_remote_hash and current_remote_hash != last_remote_hash:
                        log.info("config_sync_realtime: remote config changed, applying locally")
                        with _lock:
                            _stats["remote_changes_detected"] += 1
                        try:
                            import db
                            rows = db.select("fleet_config", {"select": "key,value"}) or []
                            remote = {r["key"]: r["value"] for r in rows if r.get("key")}
                            _apply_remote_to_local(remote)
                            with _lock:
                                _stats["syncs_triggered"] += 1
                        except Exception as e:
                            log.debug("realtime remote sync error: %s", e)
                            with _lock:
                                _stats["errors"] += 1
                    last_remote_hash = current_remote_hash
                except Exception:
                    pass

        except Exception as e:
            log.debug("watch_loop iteration error: %s", e)
            with _lock:
                _stats["errors"] += 1

        _stop_event.wait(WATCH_INTERVAL_S)


def start():
    """Start the real-time config watcher in a daemon thread."""
    global _watcher_thread
    if not ENABLED:
        log.debug("config_sync_realtime disabled via ORCH_CONFIG_REALTIME")
        return False
    with _lock:
        if _watcher_thread and _watcher_thread.is_alive():
            return False
        _stop_event.clear()
        _watcher_thread = threading.Thread(target=_watch_loop, daemon=True,
                                           name="config-sync-realtime")
        _watcher_thread.start()
        log.info("config_sync_realtime watcher started (interval=%.1fs)", WATCH_INTERVAL_S)
    return True


def stop():
    """Stop the watcher thread gracefully."""
    global _watcher_thread
    _stop_event.set()
    with _lock:
        if _watcher_thread:
            _watcher_thread.join(timeout=5)
            _watcher_thread = None
    log.info("config_sync_realtime watcher stopped")


def is_running():
    with _lock:
        return _watcher_thread is not None and _watcher_thread.is_alive()
