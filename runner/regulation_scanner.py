"""Consent-driven regulation source scanner with deterministic change detection."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


@dataclass(frozen=True)
class RegulationChange:
    source: str
    content_hash: str
    detected_at: str
    changed: bool


class PredictiveRegulationScanner:
    """Fetch is injected so production controls decide which public sources may be accessed."""
    def __init__(self, fetch: Callable[[str], str] | None = None) -> None:
        self.fetch = fetch
        self._fingerprints: dict[str, str] = {}

    def scan(self, sources: list[str]) -> list[RegulationChange]:
        if self.fetch is None:
            raise RuntimeError("scanner requires an approved fetch adapter")
        changes = []
        for source in sources:
            text = self.fetch(source)
            digest = hashlib.sha256(text.encode()).hexdigest()
            changed = source in self._fingerprints and self._fingerprints[source] != digest
            self._fingerprints[source] = digest
            changes.append(RegulationChange(source, digest, datetime.now(timezone.utc).isoformat(), changed))
        return changes
