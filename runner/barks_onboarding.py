"""SB2 Hotel self-serve onboarding — implements OnboardingFlow from barks_contracts.

Deterministic state machine: landing → e-sign → ship-kit → qr-tags → reporting.
Each transition is pure, returns Result. Invalid transitions fail-soft. QR tags are
deterministic (hash of hotel_id + toy_index).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from barks_contracts import Hotel, Result


class OnboardingStage(Enum):
    LANDING = "landing"
    ESIGN = "esign"
    SHIP_KIT = "ship_kit"
    QR_TAGS = "qr_tags"
    REPORTING = "reporting"
    COMPLETE = "complete"


# Valid transitions
_TRANSITIONS = {
    OnboardingStage.LANDING: OnboardingStage.ESIGN,
    OnboardingStage.ESIGN: OnboardingStage.SHIP_KIT,
    OnboardingStage.SHIP_KIT: OnboardingStage.QR_TAGS,
    OnboardingStage.QR_TAGS: OnboardingStage.REPORTING,
    OnboardingStage.REPORTING: OnboardingStage.COMPLETE,
}


@dataclass
class OnboardingState:
    hotel_id: str = ""
    stage: OnboardingStage = OnboardingStage.LANDING
    signed: bool = False
    kit_shipped: bool = False
    qr_tags: List[str] = field(default_factory=list)
    distribution_counts: Dict[str, int] = field(default_factory=dict)


def _generate_qr_tag(hotel_id: str, toy_index: int) -> str:
    """Deterministic QR tag: SHA-256 of hotel_id + toy_index."""
    return hashlib.sha256(f"{hotel_id}:{toy_index}".encode()).hexdigest()[:16]


class SBOnboardingFlow:
    """Concrete OnboardingFlow implementation."""

    def __init__(self):
        self._states: Dict[str, OnboardingState] = {}

    def _get_state(self, hotel_id: str) -> Optional[OnboardingState]:
        return self._states.get(hotel_id)

    def _advance(self, hotel_id: str, expected: OnboardingStage) -> Result:
        state = self._get_state(hotel_id)
        if state is None:
            return Result(ok=False, error=f"hotel {hotel_id} not started")
        if state.stage != expected:
            return Result(ok=False, error=f"expected stage {expected.value}, got {state.stage.value}")
        next_stage = _TRANSITIONS.get(state.stage)
        if next_stage is None:
            return Result(ok=False, error=f"no transition from {state.stage.value}")
        state.stage = next_stage
        return Result(ok=True, value=state)

    def start(self, hotel: Hotel) -> Result:
        try:
            if hotel is None:
                return Result(ok=False, error="hotel is None")
            if hotel.id in self._states:
                # Idempotent — replay returns current state
                return Result(ok=True, value=self._states[hotel.id])
            state = OnboardingState(hotel_id=hotel.id, stage=OnboardingStage.LANDING)
            self._states[hotel.id] = state
            return Result(ok=True, value=state)
        except Exception as e:
            return Result(ok=False, error=str(e))

    def sign_sponsorship(self, hotel_id: str) -> Result:
        try:
            r = self._advance(hotel_id, OnboardingStage.LANDING)
            if r.ok:
                r.value.signed = True
            return r
        except Exception as e:
            return Result(ok=False, error=str(e))

    def ship_starter_kit(self, hotel_id: str) -> Result:
        try:
            r = self._advance(hotel_id, OnboardingStage.ESIGN)
            if r.ok:
                r.value.kit_shipped = True
            return r
        except Exception as e:
            return Result(ok=False, error=str(e))

    def generate_qr_tags(self, hotel_id: str, toy_count: int) -> Result:
        try:
            if toy_count < 0:
                return Result(ok=False, error="negative toy_count")
            r = self._advance(hotel_id, OnboardingStage.SHIP_KIT)
            if r.ok:
                r.value.qr_tags = [_generate_qr_tag(hotel_id, i) for i in range(toy_count)]
            return r
        except Exception as e:
            return Result(ok=False, error=str(e))

    def report_distribution(self, hotel_id: str, counts: Dict[str, int]) -> Result:
        try:
            if counts is None:
                return Result(ok=False, error="counts is None")
            r = self._advance(hotel_id, OnboardingStage.QR_TAGS)
            if r.ok:
                r.value.distribution_counts = dict(counts)
            return r
        except Exception as e:
            return Result(ok=False, error=str(e))


# Module-level singleton
_flow = SBOnboardingFlow()

def start(hotel: Hotel) -> Result:
    return _flow.start(hotel)

def sign_sponsorship(hotel_id: str) -> Result:
    return _flow.sign_sponsorship(hotel_id)

def ship_starter_kit(hotel_id: str) -> Result:
    return _flow.ship_starter_kit(hotel_id)

def generate_qr_tags(hotel_id: str, toy_count: int) -> Result:
    return _flow.generate_qr_tags(hotel_id, toy_count)

def report_distribution(hotel_id: str, counts: Dict[str, int]) -> Result:
    return _flow.report_distribution(hotel_id, counts)
