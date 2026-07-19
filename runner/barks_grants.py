"""SB5 Grant/CSR autopilot — draft, gate, and submit grant applications."""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from barks_contracts import (
    GiftOpportunity,
    GrantApplication,
    HumanGateTask,
    Result,
)


class GrantAutopilot:
    """Drafts grant applications, manages human-review gates, and marks
    applications submittable only when every gate is APPROVED (fail-closed)."""

    def __init__(self, now: Optional[date] = None) -> None:
        self._now = now or date.today()

    # ------------------------------------------------------------------
    # Public API — every method returns Result, never raises
    # ------------------------------------------------------------------

    def draft_applications(
        self, opportunities: Optional[List[GiftOpportunity]]
    ) -> Result:
        """Auto-draft GrantApplication objects sorted by deadline (earliest first).

        None / empty input -> Result(ok=True, data=[]).
        """
        try:
            if not opportunities:
                return Result(ok=True, data=[])

            sorted_opps = sorted(opportunities, key=lambda o: o.deadline)
            applications: list[GrantApplication] = []
            for opp in sorted_opps:
                draft = self._generate_draft(opp)
                applications.append(
                    GrantApplication(
                        opportunity_name=opp.name,
                        deadline=opp.deadline,
                        draft_text=draft,
                    )
                )
            return Result(ok=True, data=applications)
        except Exception as exc:
            return Result(ok=False, error=str(exc))

    def add_gate(
        self, application: Optional[GrantApplication], description: str
    ) -> Result:
        """Append a HumanGateTask to *application*.gates."""
        try:
            if application is None:
                return Result(ok=False, error="application is None")
            if not description:
                return Result(ok=False, error="gate description is empty")
            gate = HumanGateTask(description=description)
            application.gates.append(gate)
            return Result(ok=True, data=gate)
        except Exception as exc:
            return Result(ok=False, error=str(exc))

    def check_submittable(self, application: Optional[GrantApplication]) -> bool:
        """Return True only when ALL gates are APPROVED (no gates -> True)."""
        if application is None:
            return False
        if not application.gates:
            return True
        return all(g.status == "APPROVED" for g in application.gates)

    def mark_submittable(
        self, application: Optional[GrantApplication]
    ) -> Result:
        """Set submittable=True if every gate is APPROVED; fail-closed otherwise."""
        try:
            if application is None:
                return Result(ok=False, error="application is None")

            for gate in application.gates:
                if gate.status == "DENIED":
                    return Result(ok=False, error="gate denied")
                if gate.status == "PENDING":
                    return Result(ok=False, error="gates pending")

            application.submittable = True
            return Result(ok=True, data=application)
        except Exception as exc:
            return Result(ok=False, error=str(exc))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_draft(self, opp: GiftOpportunity) -> str:
        reqs = ", ".join(opp.requirements) if opp.requirements else "none specified"
        return (
            f"Draft application for '{opp.name}' "
            f"(deadline {opp.deadline.isoformat()}). "
            f"Requirements: {reqs}."
        )
