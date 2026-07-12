"""Sustainable Barks nonprofit ops — shared contracts module.

Pure dataclasses, TypedDicts, and protocol signatures that every SB engine builds against.
No implementation bodies — only contracts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# ORCH_-prefixed config constants (env-var based, no secrets)
# ---------------------------------------------------------------------------
ORCH_SB_MAX_PICKUP_STOPS = int(os.environ.get("ORCH_SB_MAX_PICKUP_STOPS", "50"))
ORCH_SB_DEFAULT_SHIFT_HOURS = int(os.environ.get("ORCH_SB_DEFAULT_SHIFT_HOURS", "4"))
ORCH_SB_QUARTER_MONTHS = int(os.environ.get("ORCH_SB_QUARTER_MONTHS", "3"))

# ---------------------------------------------------------------------------
# Fail-soft Result wrapper
# ---------------------------------------------------------------------------
@dataclass
class Result:
    """Fail-soft wrapper. Defaults to failure (ok=False)."""
    ok: bool = False
    value: Any = None
    error: str = ""

# ---------------------------------------------------------------------------
# Human gate enum — fail-CLOSED default of PENDING
# ---------------------------------------------------------------------------
class HumanGate(Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------
@dataclass
class Hotel:
    id: str = ""
    name: str = ""
    address: str = ""
    contact_email: str = ""
    sponsorship_tier: str = "basic"

@dataclass
class Sponsor:
    id: str = ""
    name: str = ""
    hotel_id: str = ""
    amount_cents: int = 0

@dataclass
class VolunteerShift:
    id: str = ""
    volunteer_name: str = ""
    date: str = ""
    start_hour: int = 0
    duration_hours: int = ORCH_SB_DEFAULT_SHIFT_HOURS
    location: str = ""

@dataclass
class PickupRun:
    id: str = ""
    stops: List[tuple] = field(default_factory=list)  # list of (lat, lon) tuples
    distance_km: float = 0.0

@dataclass
class ShelterSupplyMatch:
    shelter_id: str = ""
    supply_type: str = ""
    quantity: int = 0
    matched: bool = False

@dataclass
class ImpactReceipt:
    hotel_id: str = ""
    quarter: str = ""
    toys_distributed: int = 0
    shelter_hours: float = 0.0
    press_mentions: int = 0
    signature: str = ""

@dataclass
class OutreachDraft:
    recipient: str = ""
    subject: str = ""
    body: str = ""

@dataclass
class GrantApplication:
    id: str = ""
    organization: str = ""
    amount_requested_cents: int = 0
    status: str = "draft"

@dataclass
class HumanGateTask:
    id: str = ""
    description: str = ""
    gate: HumanGate = HumanGate.PENDING

# ---------------------------------------------------------------------------
# Engine protocols
# ---------------------------------------------------------------------------
@runtime_checkable
class DispatchEngine(Protocol):
    def create_shift_payload(self, shift: VolunteerShift) -> Result: ...
    def build_pickup_route(self, coordinates: List[tuple]) -> Result: ...
    def match_supplies(self, supplies: List[dict], needs: List[dict]) -> Result: ...
    def approve_weekly_plan(self, plan: Any) -> Result: ...

@runtime_checkable
class OnboardingFlow(Protocol):
    def start(self, hotel: Hotel) -> Result: ...
    def sign_sponsorship(self, hotel_id: str) -> Result: ...
    def ship_starter_kit(self, hotel_id: str) -> Result: ...
    def generate_qr_tags(self, hotel_id: str, toy_count: int) -> Result: ...
    def report_distribution(self, hotel_id: str, counts: Dict[str, int]) -> Result: ...

@runtime_checkable
class ImpactReportAssembler(Protocol):
    def assemble_receipt(self, hotel_id: str, quarter: str, metrics: Dict[str, Any]) -> Result: ...
    def check_renewal(self, hotel_id: str) -> Result: ...

@runtime_checkable
class EsgTargetingEngine(Protocol):
    def score_hotel(self, hotel: Hotel) -> Result: ...
    def recommend_targets(self, hotels: List[Hotel]) -> Result: ...

@runtime_checkable
class GrantAutopilot(Protocol):
    def draft_application(self, organization: str, amount_cents: int) -> Result: ...
    def submit_application(self, application: GrantApplication) -> Result: ...
