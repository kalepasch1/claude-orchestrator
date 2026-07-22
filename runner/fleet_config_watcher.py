#!/usr/bin/env python3
"""
fleet_config_watcher.py - real-time change detection for the fleet_config table.

Polls fleet_config every FLEET_CONFIG_POLL_INTERVAL seconds (default 0.5 s) to
stay within the < 1 s latency target. Detects creates, updates, and deletes by
diffing against an in-memory snapshot, then routes changes to a publisher.

The DAO's _change_hook provides an immediate fast path for writes made through
fleet_config_dao.set_value; this watcher catches out-of-band DB changes (direct
SQL, Supabase dashboard, other processes).
"""
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_POLL_INTERVAL = float(os.environ.get("FLEET_CONFIG_POLL_INTERVAL", "0.5") or 0.5)


class FleetConfigWatcher:
    """Polls fleet_config and emits change events to a publisher."""

    def __init__(self, poll_interval=None):
        self._poll_interval = poll_interval if poll_interval is not None else _POLL_INTERVAL
        self._lock = threading.Lock()
        self._snapshot = {}    # key -> row dict
        self._publisher = None
        self._running = False
        self._thread = None

    def set_publisher(self, publisher):
        """Attach the publisher that receives (old, new, change_type) calls."""
        self._publisher = publisher

    def start(self):
        """Start background polling. Idempotent — safe to call multiple times."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._snapshot = self._fetch_current()
        t = threading.Thread(target=self._loop, daemon=True,
                             name="fleet-config-watcher")
        with self._lock:
            self._thread = t
        t.start()

    def stop(self):
        """Signal the background thread to stop and wait for it to exit."""
        with self._lock:
            self._running = False
            t = self._thread
        if t:
            t.join(timeout=5)
        with self._lock:
            self._thread = None

    def _fetch_current(self):
        """Return {key: row} for all fleet_config rows. Empty dict on error."""
        try:
            rows = db.select("fleet_config", {"select": "*"}) or []
            return {r["key"]: r for r in rows if r.get("key")}
        except Exception:
            return {}

    def detect_changes(self, current):
        """Diff current state against the in-memory snapshot.

        Returns a list of (change_type, old_row, new_row) tuples where
        change_type is 'created' | 'updated' | 'deleted'.
        Does NOT update the snapshot — caller is responsible for that.
        """
        with self._lock:
            snap = dict(self._snapshot)
        changes = []
        for key, row in current.items():
            if key not in snap:
                changes.append(("created", None, row))
            elif row.get("value") != snap[key].get("value"):
                changes.append(("updated", snap[key], row))
        for key, row in snap.items():
            if key not in current:
                changes.append(("deleted", row, None))
        return changes

    def _loop(self):
        while True:
            with self._lock:
                if not self._running:
                    break
            try:
                current = self._fetch_current()
                changes = self.detect_changes(current)
                with self._lock:
                    self._snapshot = current
                pub = self._publisher
                if pub:
                    for change_type, old, new in changes:
                        try:
                            pub.publish(old=old, new=new, change_type=change_type)
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(self._poll_interval)

    def get_snapshot(self):
        """Return a copy of the current in-memory snapshot."""
        with self._lock:
            return dict(self._snapshot)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_watcher = None
_watcher_lock = threading.Lock()


def start_monitoring(publisher, poll_interval=None):
    """Start the global watcher singleton. Returns the watcher instance."""
    global _watcher
    with _watcher_lock:
        if _watcher is None:
            _watcher = FleetConfigWatcher(poll_interval=poll_interval)
        _watcher.set_publisher(publisher)
        _watcher.start()
        return _watcher


def stop_monitoring():
    """Stop the global watcher singleton."""
    global _watcher
    with _watcher_lock:
        w = _watcher
        _watcher = None
    if w:
        w.stop()


def get_snapshot():
    """Return the current snapshot from the global watcher (empty dict if not running)."""
    with _watcher_lock:
        w = _watcher
    return w.get_snapshot() if w else {}
