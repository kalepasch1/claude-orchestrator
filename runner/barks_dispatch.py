"""SB1 Agentic ops dispatch — implements DispatchEngine from barks_contracts.

Volunteer shift auto-posting, route-optimized pickup runs (nearest-neighbor),
shelter-supply matching. Weekly plan approval is fail-CLOSED (HumanGate.PENDING).
All public functions return Result, never raise.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from barks_contracts import (
    HumanGate, HumanGateTask, PickupRun, Result, ShelterSupplyMatch,
    VolunteerShift, ORCH_SB_MAX_PICKUP_STOPS,
)


@dataclass
class WeeklyPlan:
    shifts: List[dict] = field(default_factory=list)
    runs: List[dict] = field(default_factory=list)
    gate: HumanGate = HumanGate.PENDING


def _euclidean(a: tuple, b: tuple) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


class SBDispatchEngine:
    """Concrete implementation of DispatchEngine."""

    def create_shift_payload(self, shift: VolunteerShift) -> Result:
        """Produce a platform-agnostic shift payload."""
        try:
            if shift is None:
                return Result(ok=False, error="shift is None")
            payload = {
                "shift_id": shift.id,
                "volunteer": shift.volunteer_name,
                "date": shift.date,
                "start_hour": shift.start_hour,
                "duration_hours": shift.duration_hours,
                "location": shift.location,
            }
            return Result(ok=True, value=payload)
        except Exception as e:
            return Result(ok=False, error=str(e))

    def build_pickup_route(self, coordinates: List[tuple]) -> Result:
        """Nearest-neighbor route builder — pure, deterministic."""
        try:
            if coordinates is None:
                return Result(ok=False, error="coordinates is None")
            if len(coordinates) == 0:
                return Result(ok=True, value=PickupRun(id="empty", stops=[], distance_km=0.0))
            if len(coordinates) > ORCH_SB_MAX_PICKUP_STOPS:
                return Result(ok=False, error=f"exceeds max stops ({ORCH_SB_MAX_PICKUP_STOPS})")

            # Validate coordinates
            for c in coordinates:
                if not isinstance(c, (list, tuple)) or len(c) != 2:
                    return Result(ok=False, error=f"invalid coordinate: {c}")

            if len(coordinates) == 1:
                return Result(ok=True, value=PickupRun(id="single", stops=list(coordinates), distance_km=0.0))

            # Nearest-neighbor
            remaining = list(coordinates)
            route = [remaining.pop(0)]
            total_dist = 0.0
            while remaining:
                last = route[-1]
                nearest_idx = min(range(len(remaining)), key=lambda i: _euclidean(last, remaining[i]))
                total_dist += _euclidean(last, remaining[nearest_idx])
                route.append(remaining.pop(nearest_idx))

            return Result(ok=True, value=PickupRun(id="route", stops=route, distance_km=round(total_dist, 4)))
        except Exception as e:
            return Result(ok=False, error=str(e))

    def match_supplies(self, supplies: List[dict], needs: List[dict]) -> Result:
        """Match supplies to shelter needs. Greedy by type."""
        try:
            if supplies is None or needs is None:
                return Result(ok=False, error="supplies or needs is None")
            matches = []
            supply_pool: Dict[str, int] = {}
            for s in supplies:
                t = s.get("type", "")
                supply_pool[t] = supply_pool.get(t, 0) + s.get("quantity", 0)

            for need in needs:
                t = need.get("type", "")
                qty_needed = need.get("quantity", 0)
                available = supply_pool.get(t, 0)
                matched_qty = min(qty_needed, available)
                supply_pool[t] = available - matched_qty
                matches.append(ShelterSupplyMatch(
                    shelter_id=need.get("shelter_id", ""),
                    supply_type=t,
                    quantity=matched_qty,
                    matched=matched_qty > 0,
                ))
            return Result(ok=True, value=matches)
        except Exception as e:
            return Result(ok=False, error=str(e))

    def approve_weekly_plan(self, plan: Any) -> Result:
        """Fail-CLOSED: returns plan gated behind HumanGate defaulting to PENDING."""
        try:
            if plan is None:
                return Result(ok=False, error="plan is None")
            weekly = WeeklyPlan()
            if isinstance(plan, dict):
                weekly.shifts = plan.get("shifts", [])
                weekly.runs = plan.get("runs", [])
            # Gate is PENDING by default — nothing dispatches until APPROVED
            weekly.gate = HumanGate.PENDING
            return Result(ok=True, value=weekly)
        except Exception as e:
            return Result(ok=False, error=str(e))

    def dispatch_if_approved(self, plan: WeeklyPlan) -> Result:
        """Only dispatches if plan gate is APPROVED."""
        try:
            if plan is None:
                return Result(ok=False, error="plan is None")
            if plan.gate != HumanGate.APPROVED:
                return Result(ok=False, error=f"plan not approved (gate={plan.gate.value})")
            return Result(ok=True, value={"dispatched": True, "shifts": len(plan.shifts), "runs": len(plan.runs)})
        except Exception as e:
            return Result(ok=False, error=str(e))


# Module-level singleton
_engine = SBDispatchEngine()

def create_shift_payload(shift: VolunteerShift) -> Result:
    return _engine.create_shift_payload(shift)

def build_pickup_route(coordinates: List[tuple]) -> Result:
    return _engine.build_pickup_route(coordinates)

def match_supplies(supplies: List[dict], needs: List[dict]) -> Result:
    return _engine.match_supplies(supplies, needs)

def approve_weekly_plan(plan: Any) -> Result:
    return _engine.approve_weekly_plan(plan)
