#!/usr/bin/env python3
"""
v4_contracts.py - cross-app v4 Protocols.

These are the structural contracts that the v4 global pass requires to "live once"
so every app in the portfolio consumes the same shape instead of re-deriving it.
Protocols only: no I/O, no DB, no side effects. Implementations live in their own
modules (e.g. runner/persona_registry.py implements PersonaRegistry).
"""
from typing import Protocol, runtime_checkable, Iterable, Mapping, Optional, Any


@runtime_checkable
class PersonaRegistry(Protocol):
    """Single source of truth for persona definitions + their reliability scores.

    Contract:
      - Persona definitions are declared once and are read-only to consumers.
      - Reliability is a float in [0.0, 1.0]; consumers must treat an unknown
        persona as `default_reliability`, never as 0.0 (unknown != useless).
      - `record_outcome` is the ONLY mutation path, so calibration compounds
        portfolio-wide from real outcomes rather than per-app guesses.
    """

    def personas(self) -> Iterable[str]:
        """All known persona ids, stable order."""
        ...

    def get(self, persona_id: str) -> Optional[Mapping[str, Any]]:
        """Definition for one persona, or None if unknown."""
        ...

    def reliability(self, persona_id: str) -> float:
        """Calibrated reliability in [0.0, 1.0]."""
        ...

    def record_outcome(self, persona_id: str, correct: bool,
                       weight: float = 1.0) -> float:
        """Fold one observed outcome into the persona's reliability.

        Returns the persona's reliability AFTER the update.
        """
        ...
