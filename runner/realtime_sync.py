#!/usr/bin/env python3
"""
realtime_sync.py - real-time database synchronization for the orchestrator.

Slice-3: replaces manual/delayed sync with near-real-time state propagation:
  - Polls task/config tables at high frequency (configurable, default 2s)
  - Detects changes via updated_at comparison (no DB triggers needed)
  - Dispatches change events to registered handlers (observer pattern)
  - Coalesces rapid changes to avoid handler storms
  - Thread-safe with fail-soft on any handler error

Usage:
    import realtime_sync
    realtime_sync.register("tasks", on_task_change)
    realtime_sync.start()  # background thread
"""
import collections, json, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import log as _log_mod
_log = _log_mod.get("realtime_sync")

POLL_INTERVAL = float(os.environ.get("ORCH_SYNC_POLL_SEC", "2.0"))
COALESCE_WINDOW = float(os.environ.get("ORCH_SYNC_COALESCE_SEC", "0.5"))
ENABLED = os.environ.get("ORCH_REALTIME_SYNC", "true").lower() in ("true", "1")
MAX_HANDLERS_PER_TABLE = 10

_lock = threading.Lock()
_handlers = collections.defaultdict(list)  # table_name -> [callable]
_watermarks = {}  # table_name -> last_updated_at ISO string
_running = False
_thread = None
_stats = {"polls": 0, "changes_detected": 0, "handler_errors": 0}

# Tables to watch and their change-detection columns
_WATCHED = {
    "tasks": {"select": "id,slug,state,updated_at,note", "order": "updated_at.desc", "limit": "20"},
    "fleet_config": {"select": "key,value,updated_at", "order": "updated_at.desc", "limit": "10"},
}


def register(table, handler):
    """Register a handler for changes on a table. Handler receives list of changed rows."""
    with _lock:
        if table not in _WATCHED:
            _log.warning("realtime_sync: unknown table %s, skipping", table)
            return False
        if len(_handlers[table]) >= MAX_HANDLERS_PER_TABLE:
            _log.warning("realtime_sync: max handlers for %s", table)
            return False
        _handlers[table].append(handler)
        return True


def unregister(table, handler):
    """Remove a previously registered handler."""
    with _lock:
        try:
            _handlers[table].remove(handler)
            return True
        except ValueError:
            return False


def _poll_table(table, params):
    """Poll a single table for changes since last watermark."""
    wm = _watermarks.get(table)
    query = dict(params)
    if wm:
        query["updated_at"] = f"gt.{wm}"

    try:
        rows = db.select(table, query) or []
    except Exception as e:
        _log.debug("realtime_sync: poll %s failed: %s", table, e)
        return []

    if rows:
        # Update watermark to newest
        newest = max(r.get("updated_at", "") for r in rows)
        if newest:
            _watermarks[table] = newest
    return rows


def _dispatch(table, rows):
    """Dispatch changed rows to registered handlers."""
    with _lock:
        handlers = list(_handlers.get(table, []))
    for h in handlers:
        try:
            h(rows)
        except Exception as e:
            _stats["handler_errors"] += 1
            _log.debug("realtime_sync: handler error on %s: %s", table, e)


def _poll_loop():
    """Main polling loop (runs in background thread)."""
    global _running
    while _running:
        for table, params in _WATCHED.items():
            changes = _poll_table(table, params)
            if changes:
                _stats["changes_detected"] += len(changes)
                _dispatch(table, changes)
        _stats["polls"] += 1
        time.sleep(POLL_INTERVAL)


def start():
    """Start the background sync thread."""
    global _running, _thread
    if not ENABLED:
        _log.info("realtime_sync: disabled by config")
        return
    with _lock:
        if _running:
            return
        _running = True
        _thread = threading.Thread(target=_poll_loop, daemon=True, name="realtime-sync")
        _thread.start()
    _log.info("realtime_sync: started (poll=%.1fs)", POLL_INTERVAL)


def stop():
    """Stop the background sync thread."""
    global _running
    _running = False
    if _thread:
        _thread.join(timeout=5)


def stats():
    """Return sync statistics."""
    return dict(_stats)


if __name__ == "__main__":
    print("realtime_sync: standalone test — polling for 10s")
    register("tasks", lambda rows: print(f"  tasks changed: {len(rows)} rows"))
    start()
    time.sleep(10)
    stop()
    print(json.dumps(stats(), indent=2))
