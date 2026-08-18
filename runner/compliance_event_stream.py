"""Low-latency typed compliance events with durable runner/evidence delivery."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

import events
import evidence_bus


class ComplianceEventType(str, Enum):
    FILING_SUBMITTED = "filing.submitted"
    FILING_CHANGED = "filing.changed"
    RISK_SCORE_CHANGED = "risk.score_changed"
    REGULATION_INGESTED = "regulation.ingested"
    INCIDENT_REPORTED = "incident.reported"
    REMEDIATION_PROPOSED = "remediation.proposed"
    REMEDIATION_APPLIED = "remediation.applied"


@dataclass(frozen=True)
class ComplianceEvent:
    kind: ComplianceEventType
    app_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = "default"
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


Subscriber = Callable[[ComplianceEvent], None]


class ComplianceEventStream:
    """Synchronous fan-out gives local consumers immediate delivery; failures are isolated."""
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._history: list[ComplianceEvent] = []
        self._lock = RLock()

    def subscribe(self, kind: ComplianceEventType | str, callback: Subscriber) -> Callable[[], None]:
        key = kind.value if isinstance(kind, ComplianceEventType) else str(kind)
        with self._lock:
            self._subscribers.setdefault(key, []).append(callback)
        def unsubscribe() -> None:
            with self._lock:
                callbacks = self._subscribers.get(key, [])
                if callback in callbacks:
                    callbacks.remove(callback)
        return unsubscribe

    def publish(self, event: ComplianceEvent) -> ComplianceEvent:
        with self._lock:
            self._history.append(event)
            callbacks = list(self._subscribers.get(event.kind.value, ())) + list(self._subscribers.get("*", ()))
        events.emit("compliance:" + event.kind.value, event_id=event.event_id, app=event.app_id,
                    tenant=event.tenant_id, payload=event.payload)
        evidence_bus.append(event.app_id, event.kind.value, event.event_id,
                            {"tenant_id": event.tenant_id, **event.payload})
        for callback in callbacks:
            try:
                callback(event)
            except Exception as exc:
                events.emit("compliance:subscriber_failed", event_id=event.event_id,
                            subscriber=repr(callback), error=str(exc)[:300])
        return event

    def recent(self, limit: int = 100, app_id: str | None = None) -> list[ComplianceEvent]:
        with self._lock:
            values = self._history if app_id is None else [e for e in self._history if e.app_id == app_id]
            return list(values[-max(0, limit):])
