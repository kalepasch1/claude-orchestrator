#!/usr/bin/env python3
"""
fleet_config_event_publisher.py - event enrichment and fan-out for fleet_config changes.

Receives raw change notifications (old/new rows, change_type) from
FleetConfigWatcher (or directly from fleet_config_dao's change hook), enriches
them with risk classification and approval status, stores a rolling buffer of
recent events (polling API), and fans out to registered subscriber callbacks
(event subscription API).

Duplicate suppression: consecutive publishes for the same key with the same
value emit exactly one event — subsequent identical publishes are silently
dropped.

Usage (polling):
    import fleet_config_event_publisher as pub
    events = pub.get_events(since_timestamp="2026-07-09T00:00:00+00:00", limit=50)

Usage (event subscription):
    def on_change(event):
        print(event["key"], event["change_type"])

    pub.subscribe(on_change)
    # ... later ...
    pub.unsubscribe(on_change)
"""
import os, sys, uuid, datetime, threading
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import legal_filter

MAX_EVENTS = int(os.environ.get("FLEET_CONFIG_EVENT_BUFFER", "500") or 500)

# Keys that contain credential markers must never be applied fleet-wide
# (mirrors fleet_control._DENY_MARKERS).
_DENY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL")


def _has_credential_marker(key):
    ku = str(key or "").upper()
    return any(m in ku for m in _DENY_MARKERS)


def _classify_risk(key, value):
    """Return 'unsafe_key' | 'legal_review' | 'safe'."""
    if _has_credential_marker(key):
        return "unsafe_key"
    blob = f"{key} {value}"
    if legal_filter.requires_owner_approval(text=blob):
        return "legal_review"
    return "safe"


def _approval_status(risk):
    if risk == "unsafe_key":
        return "blocked"
    if risk == "legal_review":
        return "requires_review"
    return "auto_approved"


class FleetConfigEventPublisher:
    """Enriches fleet_config change events and delivers them to subscribers."""

    def __init__(self, max_events=None):
        self._lock = threading.Lock()
        self._events = deque(maxlen=max_events or MAX_EVENTS)
        self._subscribers = []
        self._last_value = {}   # key -> last emitted value (duplicate suppression)

    def publish(self, old, new, change_type):
        """Enrich and emit a fleet_config change event.

        old:         previous row dict, or None for creates
        new:         new row dict, or None for deletes
        change_type: 'created' | 'updated' | 'deleted'

        Returns the event dict, or None if the event was suppressed as a duplicate.
        """
        key = str((new or old or {}).get("key") or "")
        new_val = (new or {}).get("value") if new else None

        with self._lock:
            if change_type != "deleted":
                if key in self._last_value and self._last_value[key] == new_val:
                    return None   # identical value: suppress duplicate
                self._last_value[key] = new_val
            else:
                self._last_value.pop(key, None)   # deletion resets suppression state

        risk = _classify_risk(key, new_val or "")
        approval = _approval_status(risk)

        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "key": key,
            "old_value": old,
            "new_value": new,
            "change_type": change_type,
            "risk_classification": risk,
            "approval_status": approval,
        }

        with self._lock:
            self._events.append(event)
            subs = list(self._subscribers)

        for cb in subs:
            try:
                cb(event)
            except Exception:
                pass

        return event

    def get_events(self, since_timestamp=None, limit=100):
        """Polling API: return stored events, optionally filtered by ISO timestamp.

        since_timestamp: ISO 8601 string; events with timestamp >= this value are returned
        limit:           maximum number of events to return (most recent N)
        """
        with self._lock:
            evts = list(self._events)
        if since_timestamp:
            evts = [e for e in evts if e["timestamp"] >= since_timestamp]
        return evts[-limit:] if limit and len(evts) > limit else evts

    def subscribe(self, callback):
        """Register a callable that receives each new event dict in real time."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback):
        """Remove a previously registered callback. No-op if not registered."""
        with self._lock:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

    def clear(self):
        """Reset all state. Used in tests to isolate cases."""
        with self._lock:
            self._events.clear()
            self._subscribers.clear()
            self._last_value.clear()


# ---------------------------------------------------------------------------
# Module-level singleton and convenience functions
# ---------------------------------------------------------------------------
_publisher = FleetConfigEventPublisher()


def publish(old, new, change_type):
    return _publisher.publish(old=old, new=new, change_type=change_type)


def get_events(since_timestamp=None, limit=100):
    return _publisher.get_events(since_timestamp=since_timestamp, limit=limit)


def subscribe(callback):
    _publisher.subscribe(callback)


def unsubscribe(callback):
    _publisher.unsubscribe(callback)


def clear():
    _publisher.clear()
