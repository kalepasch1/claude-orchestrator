"""PersonaRegistry — persona definitions and reliability scores, stored once.

Implements the v4_contracts.PersonaRegistry Protocol. Every app reads and writes
the same personas here, so calibration compounds portfolio-wide instead of each
app keeping a private score that slowly diverges from everyone else's.

Storage is the existing `personas` table when it is reachable, with an in-memory
fallback so a DB outage degrades to "no cross-app memory this pass" rather than
wedging every caller. Fail-soft throughout: a registry that raises is worse than
a registry that briefly forgets.
"""
import threading
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from v4_contracts import (
    MAX_CALIBRATION_STEP,
    MIN_CALIBRATION_SAMPLES,
    NEUTRAL_RELIABILITY,
    Calibration,
    Persona,
    PersonaOutcome,
)

TABLE = "personas"

_lock = threading.Lock()
_memory: Dict[str, Persona] = {}


def _clamp01(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:                       # NaN
        return 0.0
    return max(0.0, min(1.0, number))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    """The db module, or None when unavailable. Never raises."""
    try:
        import db
        return db
    except Exception:
        return None


def _row_to_persona(row) -> Persona:
    return Persona(
        subject=str(row.get("subject") or ""),
        reliability=_clamp01(row.get("reliability", NEUTRAL_RELIABILITY)),
        samples=int(row.get("samples") or 0),
        contributors=list(row.get("contributors") or []),
        updated_at=row.get("updated_at"),
        detail=dict(row.get("detail") or {}),
    )


def _persona_to_row(persona: Persona) -> dict:
    return {
        "subject": persona.subject,
        "reliability": persona.reliability,
        "samples": persona.samples,
        "contributors": persona.contributors,
        "updated_at": persona.updated_at,
        "detail": persona.detail,
    }


def calibrate_from(persona: Persona, outcomes: Iterable[PersonaOutcome]) -> Calibration:
    """Pure calibration. Returns what WOULD be written; writes nothing.

    Refuses to conclude below MIN_CALIBRATION_SAMPLES, and caps any single pass
    at MAX_CALIBRATION_STEP so a long-lived persona cannot be rewritten by one
    bad week.
    """
    mine = [o for o in (outcomes or []) if o and o.subject == persona.subject]
    contributors = sorted({o.app for o in mine if o.app})

    weighted = total = 0.0
    for outcome in mine:
        weight = _clamp01(outcome.weight if outcome.weight is not None else 1.0)
        if weight == 0:
            continue
        total += weight
        if outcome.succeeded:
            weighted += weight

    observed_rate = (weighted / total) if total > 0 else 0.0
    samples = len(mine)

    if samples < MIN_CALIBRATION_SAMPLES:
        return Calibration(
            subject=persona.subject, observed_rate=observed_rate, samples=samples,
            contributors=contributors, proposed=persona.reliability, usable=False,
            reason=(f"insufficient evidence: {samples} outcome(s), "
                    f"need {MIN_CALIBRATION_SAMPLES}"))

    delta = observed_rate - persona.reliability
    capped = max(-MAX_CALIBRATION_STEP, min(MAX_CALIBRATION_STEP, delta))
    return Calibration(
        subject=persona.subject, observed_rate=observed_rate, samples=samples,
        contributors=contributors, proposed=_clamp01(persona.reliability + capped),
        usable=True,
        reason=(f"calibrated from {samples} outcome(s) across "
                f"{len(contributors)} app(s)"))


def apply_calibration(persona: Persona, calibration: Calibration) -> Persona:
    """Return a NEW persona with the calibration applied. Unusable => unchanged."""
    if not calibration.usable:
        return persona
    return Persona(
        subject=persona.subject,
        reliability=_clamp01(calibration.proposed),
        samples=persona.samples + calibration.samples,
        contributors=sorted(set(persona.contributors) | set(calibration.contributors)),
        updated_at=_now(),
        detail=dict(persona.detail),
    )


class InMemoryPersonaRegistry:
    """Reference implementation. Also the fallback when the DB is unreachable."""

    def __init__(self, store: Optional[Dict[str, Persona]] = None):
        self._store = store if store is not None else _memory

    def get(self, subject: str) -> Persona:
        with _lock:
            existing = self._store.get(subject)
        # An unknown subject reads NEUTRAL, never an error — a consuming app
        # must not have to special-case first contact.
        return existing or Persona(subject=subject)

    def upsert(self, persona: Persona) -> Persona:
        with _lock:
            self._store[persona.subject] = persona
        return persona

    def calibrate(self, subject: str, outcomes: Iterable[PersonaOutcome]) -> Calibration:
        return calibrate_from(self.get(subject), outcomes)

    def record_outcomes(self, outcomes: Iterable[PersonaOutcome]) -> Dict[str, Calibration]:
        grouped: Dict[str, List[PersonaOutcome]] = {}
        for outcome in outcomes or []:
            if outcome and outcome.subject:
                grouped.setdefault(outcome.subject, []).append(outcome)

        results: Dict[str, Calibration] = {}
        for subject, group in grouped.items():
            persona = self.get(subject)
            calibration = calibrate_from(persona, group)
            results[subject] = calibration
            if calibration.usable:
                self.upsert(apply_calibration(persona, calibration))
        return results

    def all(self) -> List[Persona]:
        with _lock:
            return list(self._store.values())


class DbPersonaRegistry(InMemoryPersonaRegistry):
    """DB-backed, degrading to the in-memory store when the DB is unreachable."""

    def get(self, subject: str) -> Persona:
        db = _db()
        if db is not None:
            try:
                rows = db.select(TABLE, {"subject": f"eq.{subject}", "limit": "1"}) or []
                if rows:
                    return _row_to_persona(rows[0])
            except Exception:
                pass                                   # fall through to memory
        return super().get(subject)

    def upsert(self, persona: Persona) -> Persona:
        db = _db()
        if db is not None:
            try:
                db.upsert(TABLE, _persona_to_row(persona))
            except Exception:
                pass                                   # memory still records it
        return super().upsert(persona)

    def all(self) -> List[Persona]:
        db = _db()
        if db is not None:
            try:
                rows = db.select(TABLE, {"limit": "5000"}) or []
                if rows:
                    return [_row_to_persona(r) for r in rows]
            except Exception:
                pass
        return super().all()


_default: Optional[InMemoryPersonaRegistry] = None


def registry() -> InMemoryPersonaRegistry:
    """The process-wide registry. Module-level functions delegate to it."""
    global _default
    if _default is None:
        _default = DbPersonaRegistry()
    return _default


def get(subject: str) -> Persona:
    return registry().get(subject)


def upsert(persona: Persona) -> Persona:
    return registry().upsert(persona)


def calibrate(subject: str, outcomes: Iterable[PersonaOutcome]) -> Calibration:
    return registry().calibrate(subject, outcomes)


def record_outcomes(outcomes: Iterable[PersonaOutcome]) -> Dict[str, Calibration]:
    return registry().record_outcomes(outcomes)


def all_personas() -> List[Persona]:
    return registry().all()


def reset_for_testing() -> None:
    """Drop process state so a test cannot leak into the next one."""
    global _default
    with _lock:
        _memory.clear()
    _default = None
