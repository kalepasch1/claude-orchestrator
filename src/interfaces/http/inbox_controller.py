"""REST controller for the legal-radar inbox.

Transport-shaped in, transport-shaped out. The controller owns request
validation and the error envelope; the domain owns the actual processing.

Fail-soft contract: `handle_request` NEVER raises. Bad input yields a 400
envelope, an unexpected domain error yields a 500 envelope with the reason
recorded — the caller (a web framework, a queue worker, a test) always gets a
well-formed dict back.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Mapping, Optional

from legal_radar_v2.inbox_processor import process_inbox_item

logger = logging.getLogger(__name__)

#: Largest accepted payload, in top-level keys. Guards against a pathological
#: request wedging the processor. Fleet-pushable.
ORCH_INBOX_MAX_FIELDS = int(os.environ.get("ORCH_INBOX_MAX_FIELDS", "256"))

#: Required keys on an inbound inbox item.
REQUIRED_FIELDS = ("id",)


def _envelope(status: int, body: Any, error: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": status, "body": body}
    if error:
        payload["error"] = error
    return payload


class InboxController:
    """Thread-safe controller over `process_inbox_item`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handled = 0
        self._rejected = 0

    # -- request handling ---------------------------------------------------

    def handle(self, payload: Any) -> Dict[str, Any]:
        """Process one inbox request. Never raises."""
        problem = self.validate(payload)
        if problem:
            with self._lock:
                self._rejected += 1
            logger.info("inbox_controller: rejected request (%s)", problem)
            return _envelope(400, None, problem)

        try:
            result = process_inbox_item(dict(payload))
        except Exception as exc:  # fail-soft: never wedge the caller
            logger.error("inbox_controller: domain error: %s", exc)
            with self._lock:
                self._rejected += 1
            return _envelope(500, None, "processing failed: %s" % exc)

        with self._lock:
            self._handled += 1
        return _envelope(200, result)

    # -- validation ---------------------------------------------------------

    @staticmethod
    def validate(payload: Any) -> Optional[str]:
        """Return a human-readable problem, or None when the payload is fine."""
        if payload is None:
            return "missing payload"
        if not isinstance(payload, Mapping):
            return "payload must be an object, got %s" % type(payload).__name__
        if not payload:
            return "empty payload"
        if len(payload) > ORCH_INBOX_MAX_FIELDS:
            return "payload has %d fields (max %d)" % (len(payload), ORCH_INBOX_MAX_FIELDS)
        missing = [field for field in REQUIRED_FIELDS if field not in payload]
        if missing:
            return "missing required field(s): %s" % ", ".join(missing)
        return None

    # -- observability ------------------------------------------------------

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"handled": self._handled, "rejected": self._rejected}

    def reset(self) -> None:
        with self._lock:
            self._handled = 0
            self._rejected = 0


# Module-level singleton + delegating function (repo convention).
_controller = InboxController()


def handle_request(payload: Any) -> Dict[str, Any]:
    """Module-level entry point delegating to the shared controller."""
    return _controller.handle(payload)


def stats() -> Dict[str, int]:
    return _controller.stats()


def reset() -> None:
    _controller.reset()
