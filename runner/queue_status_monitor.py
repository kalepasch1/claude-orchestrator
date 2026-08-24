"""Real-time queue status monitoring with event emission.

Tracks queue state changes and emits events via callbacks.
"""

import time
import logging
from typing import Dict, List, Any, Optional, Callable

log = logging.getLogger(__name__)


class QueueEvent:
    def __init__(self, event_type: str, change_id: str, data: Dict[str, Any]):
        self.event_type = event_type
        self.change_id = change_id
        self.data = data
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.event_type,
            "change_id": self.change_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class QueueStatusMonitor:
    def __init__(self):
        self._callbacks: List[Callable] = []
        self._history: List[QueueEvent] = []
        self._last_snapshot: Optional[Dict[str, int]] = None

    def on_change(self, callback: Callable):
        self._callbacks.append(callback)

    def _emit(self, event: QueueEvent):
        self._history.append(event)
        if len(self._history) > 5000:
            self._history = self._history[-2500:]
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception as e:
                log.warning("Callback error: %s", e)

    def update_snapshot(self, states: Dict[str, int], change_id: str = ""):
        """Record a snapshot and emit one event per changed state.

        Iterates the UNION of the previous and current keys. Iterating only the current
        snapshot meant a state that VANISHED — the queue drains and the producer stops
        emitting the key at all — never produced an event, so a real-time dashboard kept
        showing the last non-zero count indefinitely. A disappeared state is a drop to
        zero and is reported as one.
        """
        states = dict(states or {})
        if self._last_snapshot is not None:
            for state in sorted(set(states) | set(self._last_snapshot)):
                prev = self._last_snapshot.get(state, 0)
                count = states.get(state, 0)
                if count != prev:
                    self._emit(QueueEvent(
                        "state_change", change_id,
                        {"state": state, "prev": prev, "current": count,
                         "delta": count - prev},
                    ))
        self._last_snapshot = dict(states)

    def dashboard(self, history_limit: int = 20) -> Dict[str, Any]:
        """Point-in-time status surface: counts, movement, and recent events.

        `moving` answers the question a queue dashboard exists to answer — is work
        flowing, or is the queue frozen at the same numbers? Never raises; an
        un-primed monitor reports empty rather than None-shaped fields callers must
        special-case.
        """
        current = self.get_current() or {}
        recent = self.get_status_history(history_limit)
        deltas: Dict[str, int] = {}
        for event in recent:
            data = event.get("data") or {}
            state = data.get("state")
            if state is None:
                continue
            deltas[state] = deltas.get(state, 0) + int(data.get("delta") or 0)
        return {
            "states": current,
            "total": sum(current.values()),
            "deltas": deltas,
            "moving": any(deltas.values()),
            "event_count": self.event_count,
            "recent_events": recent,
            "primed": self._last_snapshot is not None,
        }

    def get_status_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._history[-limit:]]

    def get_current(self) -> Optional[Dict[str, int]]:
        return dict(self._last_snapshot) if self._last_snapshot else None

    @property
    def event_count(self) -> int:
        return len(self._history)
