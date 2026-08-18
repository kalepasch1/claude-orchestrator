"""Outbound adapter for processed inbox items.

The gateway is the seam between the domain and whatever external system
consumes its output (a queue, an HTTP sink, a file drop). Sinks are registered
at boot; with none registered the gateway degrades to a no-op rather than
raising, so an unconfigured environment still runs.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)

#: Retry attempts per sink before the delivery is recorded as failed.
ORCH_GATEWAY_MAX_ATTEMPTS = int(os.environ.get("ORCH_GATEWAY_MAX_ATTEMPTS", "2"))

Sink = Callable[[Dict[str, Any]], Any]


class InboxGateway:
    """Thread-safe fan-out of domain results to registered sinks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sinks: List[Tuple[str, Sink]] = []
        self._delivered = 0
        self._failed = 0

    def register(self, name: str, sink: Sink) -> bool:
        """Register an outbound sink. Fail-soft: bad input returns False."""
        if not name or not callable(sink):
            logger.warning("inbox_gateway: refusing to register %r", name)
            return False
        with self._lock:
            self._sinks = [(n, s) for (n, s) in self._sinks if n != name]
            self._sinks.append((name, sink))
        return True

    def unregister(self, name: str) -> bool:
        with self._lock:
            before = len(self._sinks)
            self._sinks = [(n, s) for (n, s) in self._sinks if n != name]
            return len(self._sinks) != before

    def dispatch(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Send `result` to every sink. Never raises; reports per-sink outcome."""
        if not isinstance(result, dict):
            logger.warning("inbox_gateway: non-dict result %r; not dispatched", type(result))
            return {"dispatched": 0, "failed": 0, "outcomes": {}}

        with self._lock:
            sinks = list(self._sinks)
        if not sinks:
            logger.debug("inbox_gateway: no sinks registered; no-op dispatch")
            return {"dispatched": 0, "failed": 0, "outcomes": {}}

        outcomes: Dict[str, str] = {}
        dispatched = failed = 0
        for name, sink in sinks:
            last_error = None
            for _ in range(max(1, ORCH_GATEWAY_MAX_ATTEMPTS)):
                try:
                    sink(result)
                    outcomes[name] = "ok"
                    dispatched += 1
                    last_error = None
                    break
                except Exception as exc:  # fail-soft: one bad sink never blocks others
                    last_error = exc
            if last_error is not None:
                logger.error("inbox_gateway: sink %s failed: %s", name, last_error)
                outcomes[name] = "failed: %s" % last_error
                failed += 1

        with self._lock:
            self._delivered += dispatched
            self._failed += failed
        return {"dispatched": dispatched, "failed": failed, "outcomes": outcomes}

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "sinks": len(self._sinks),
                "delivered": self._delivered,
                "failed": self._failed,
            }

    def clear(self) -> None:
        with self._lock:
            self._sinks = []
            self._delivered = 0
            self._failed = 0


# Module-level singleton + delegating functions (repo convention).
_gateway = InboxGateway()


def register(name: str, sink: Sink) -> bool:
    return _gateway.register(name, sink)


def unregister(name: str) -> bool:
    return _gateway.unregister(name)


def dispatch(result: Dict[str, Any]) -> Dict[str, Any]:
    return _gateway.dispatch(result)


def stats() -> Dict[str, int]:
    return _gateway.stats()


def clear() -> None:
    _gateway.clear()
