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
        if self._last_snapshot is not None:
            for state, count in states.items():
                prev = self._last_snapshot.get(state, 0)
                if count != prev:
                    self._emit(QueueEvent(
                        "state_change", change_id,
                        {"state": state, "prev": prev, "current": count},
                    ))
        self._last_snapshot = dict(states)

    def get_status_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._history[-limit:]]

    def get_current(self) -> Optional[Dict[str, int]]:
        return dict(self._last_snapshot) if self._last_snapshot else None

    @property
    def event_count(self) -> int:
        return len(self._history)
