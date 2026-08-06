#!/usr/bin/env python3
"""
persona_registry.py - the single place persona definitions and their reliability
scores live. Implements the PersonaRegistry Protocol from v4_contracts.

Why this exists (v4 global pass, cross-app coordination):
every app was carrying its own copy of "which reviewer archetypes exist and how
much do we trust them". That meant calibration learned in one app was thrown away
by the next. Here the definitions are declared once, reliability is derived from
the SAME calibration tables the committees already write to
(committee_scoreboard + seat_calibration), and outcomes recorded by any app
compound portfolio-wide.

Read path is cached and degrades to the static defaults when the DB is down, so
importing this module never blocks a caller.
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_RELIABILITY = float(os.environ.get("PERSONA_DEFAULT_RELIABILITY", "0.5"))
CACHE_TTL_SECONDS = int(os.environ.get("PERSONA_REGISTRY_TTL", "300"))
# Outcomes are folded in with a decaying weight so a persona with a long history
# is not flipped by one bad call, but a new persona calibrates quickly.
PRIOR_STRENGTH = float(os.environ.get("PERSONA_PRIOR_STRENGTH", "4.0"))


# --- persona definitions: declared ONCE, consumed everywhere -----------------
# id -> definition. `committee`/`seat` link a persona to the calibration rows
# the committees already produce, so reliability is observed, not asserted.
_DEFINITIONS = {
    "risk_officer": {
        "id": "risk_officer",
        "label": "Risk Officer",
        "committee": "risk",
        "seat": "risk_officer",
        "brief": "Downside, tail exposure, and whether the loss is bounded.",
    },
    "compliance_counsel": {
        "id": "compliance_counsel",
        "label": "Compliance Counsel",
        "committee": "legal",
        "seat": "compliance_counsel",
        "brief": "Licensing, registration, custody, transmission, advice gates.",
    },
    "security_reviewer": {
        "id": "security_reviewer",
        "label": "Security Reviewer",
        "committee": "security",
        "seat": "security_reviewer",
        "brief": "Authn/authz, secret handling, injection and data-exfil paths.",
    },
    "product_owner": {
        "id": "product_owner",
        "label": "Product Owner",
        "committee": "product",
        "seat": "product_owner",
        "brief": "Does this move the user-visible outcome, and is scope honest.",
    },
    "staff_engineer": {
        "id": "staff_engineer",
        "label": "Staff Engineer",
        "committee": "engineering",
        "seat": "staff_engineer",
        "brief": "Correctness, blast radius, and the smallest mergeable diff.",
    },
    "operator": {
        "id": "operator",
        "label": "Operator",
        "committee": "operations",
        "seat": "operator",
        "brief": "Can it be run, observed and rolled back at 3am.",
    },
}


def _clamp01(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return DEFAULT_RELIABILITY
    if value != value:  # NaN
        return DEFAULT_RELIABILITY
    return max(0.0, min(1.0, value))


class _Registry:
    """Concrete PersonaRegistry. Use the module-level singleton `registry`."""

    def __init__(self, definitions=None, default_reliability=DEFAULT_RELIABILITY):
        self._definitions = dict(definitions or _DEFINITIONS)
        self.default_reliability = _clamp01(default_reliability)
        self._lock = threading.RLock()
        self._scores = {}      # persona_id -> reliability
        self._observations = {}  # persona_id -> effective sample count
        self._loaded_at = 0.0

    # -- definitions ---------------------------------------------------------
    def personas(self):
        return sorted(self._definitions)

    def get(self, persona_id):
        definition = self._definitions.get(persona_id)
        return dict(definition) if definition else None

    # -- reliability ---------------------------------------------------------
    def reliability(self, persona_id):
        if persona_id not in self._definitions:
            return self.default_reliability
        self._refresh_if_stale()
        with self._lock:
            return self._scores.get(persona_id, self.default_reliability)

    def reliabilities(self):
        """All personas -> reliability. One refresh, not N."""
        self._refresh_if_stale()
        with self._lock:
            return {p: self._scores.get(p, self.default_reliability)
                    for p in self.personas()}

    def record_outcome(self, persona_id, correct, weight=1.0):
        """Fold one observed outcome in. Unknown personas are ignored on purpose:
        an app must declare a persona here before it can calibrate it, otherwise
        typos silently become new personas."""
        if persona_id not in self._definitions:
            return self.default_reliability
        try:
            weight = max(0.0, float(weight))
        except (TypeError, ValueError):
            weight = 1.0
        self._refresh_if_stale()
        with self._lock:
            prior = self._scores.get(persona_id, self.default_reliability)
            n = self._observations.get(persona_id, 0.0) + PRIOR_STRENGTH
            observed = 1.0 if correct else 0.0
            updated = (prior * n + observed * weight) / (n + weight)
            updated = _clamp01(updated)
            self._scores[persona_id] = updated
            self._observations[persona_id] = \
                self._observations.get(persona_id, 0.0) + weight
            return updated

    # -- calibration load ----------------------------------------------------
    def _refresh_if_stale(self, force=False):
        if not force and (time.time() - self._loaded_at) < CACHE_TTL_SECONDS:
            return
        loaded = self._load_calibration()
        with self._lock:
            for persona_id, (score, n) in loaded.items():
                # Locally recorded outcomes are never discarded by a refresh;
                # they are blended with whatever the tables now say.
                if persona_id in self._observations:
                    continue
                self._scores[persona_id] = score
                self._observations[persona_id] = n
            for persona_id in self._definitions:
                self._scores.setdefault(persona_id, self.default_reliability)
            self._loaded_at = time.time()

    def refresh(self):
        """Force a reload from the calibration tables."""
        self._refresh_if_stale(force=True)

    def _load_calibration(self):
        """Derive reliability from the tables the committees already write.

        Returns {persona_id: (reliability, effective_n)}. Never raises: a DB
        outage must degrade to defaults, not break every consumer.
        """
        try:
            import db  # local import: keeps module import cheap and testable
        except Exception:
            return {}

        try:
            scoreboard = db.select("committee_scoreboard", {
                "select": "committee,seat,accuracy,calls",
                "entity_type": "eq.seat",
            }) or []
        except Exception:
            scoreboard = []
        try:
            calibration = db.select("seat_calibration", {
                "select": "committee,seat,weight,n",
            }) or []
        except Exception:
            calibration = []

        by_seat = {}
        for row in scoreboard:
            key = (row.get("committee") or "", row.get("seat") or "")
            by_seat[key] = {
                "accuracy": row.get("accuracy"),
                "n": row.get("calls") or 0,
            }
        for row in calibration:
            key = (row.get("committee") or "", row.get("seat") or "")
            entry = by_seat.setdefault(key, {"accuracy": None, "n": 0})
            if entry.get("accuracy") is None:
                # seat_calibration.weight is a multiplier around 1.0; map it into
                # [0,1] so a weight of 1.0 reads as the default reliability.
                weight = row.get("weight")
                if weight is not None:
                    entry["accuracy"] = _clamp01(
                        self.default_reliability * float(weight))
            entry["n"] = max(entry.get("n") or 0, row.get("n") or 0)

        out = {}
        for persona_id, definition in self._definitions.items():
            key = (definition.get("committee", ""), definition.get("seat", ""))
            entry = by_seat.get(key)
            if not entry or entry.get("accuracy") is None:
                continue
            out[persona_id] = (_clamp01(entry["accuracy"]),
                               float(entry.get("n") or 0))
        return out


registry = _Registry()


# -- module-level convenience API (what other apps import) --------------------
def personas():
    return registry.personas()


def get(persona_id):
    return registry.get(persona_id)


def reliability(persona_id):
    return registry.reliability(persona_id)


def reliabilities():
    return registry.reliabilities()


def record_outcome(persona_id, correct, weight=1.0):
    return registry.record_outcome(persona_id, correct, weight=weight)


def refresh():
    registry.refresh()


if __name__ == "__main__":
    import json
    print(json.dumps({
        "personas": personas(),
        "reliability": reliabilities(),
    }, indent=2, sort_keys=True))
