"""H4 Family gifting protocol.

Unifies ad-hoc, advent, and earned-reward gift lanes under a single
parent-approval gate. Gift actions ESCALATE via constitution_check (F1).
Supports relative-funded MatchJars (e.g. grandma matches earned coins).
ALL purchase authority is adult-side — no lane may execute a purchase
without ParentApproval (fail-closed). Fail-soft on bad input.
"""
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from hisanta.contracts.family import (
    ParentApproval, ApprovalStatus, ConstitutionAction, constitution_check
)


class GiftLane(Enum):
    AD_HOC = "ad_hoc"
    ADVENT = "advent"
    EARNED_REWARD = "earned_reward"


@dataclass
class GiftRequest:
    lane: GiftLane
    child_id: str
    item_description: str
    amount: float = 0.0
    gift_id: str = ""


@dataclass
class GiftResult:
    success: bool
    message: str
    escalated: bool = False
    gift_id: str = ""


@dataclass
class MatchJar:
    """Relative-funded matching jar (e.g. grandma matches earned coins)."""
    funder_id: str
    funder_name: str
    child_id: str
    match_ratio: float = 1.0  # 1:1 match by default
    max_match: float = 100.0
    balance: float = 0.0

    def match(self, earned_amount: float, approval: Optional[ParentApproval] = None) -> float:
        """Match earned coins. Requires ParentApproval (fail-closed)."""
        try:
            if approval is None:
                return 0.0
            if not isinstance(approval, ParentApproval):
                return 0.0
            if approval.status != ApprovalStatus.APPROVED:
                return 0.0
            match_amount = min(earned_amount * self.match_ratio, self.max_match - self.balance)
            match_amount = max(0.0, match_amount)
            self.balance += match_amount
            return match_amount
        except Exception:
            return 0.0


def execute_gift(request: Optional[GiftRequest] = None,
                 approval: Optional[ParentApproval] = None) -> GiftResult:
    """Execute a gift through the unified protocol.

    All lanes require ParentApproval (fail-closed).
    All gift actions route through constitution_check as ESCALATE.
    Fail-soft on bad input (returns failure result, never raises).
    """
    try:
        if request is None or not isinstance(request, GiftRequest):
            return GiftResult(success=False, message="invalid request")

        if approval is None or not isinstance(approval, ParentApproval):
            return GiftResult(success=False, message="no parent approval (fail-closed)")

        if approval.status != ApprovalStatus.APPROVED:
            return GiftResult(success=False, message="parent approval denied")

        # F1 escalation: all gift actions go through constitution_check
        action_type = {
            GiftLane.AD_HOC: "gift",
            GiftLane.ADVENT: "advent_gift",
            GiftLane.EARNED_REWARD: "earned_reward",
        }.get(request.lane, "gift")

        check = constitution_check(action_type)
        if check == ConstitutionAction.DENY:
            return GiftResult(success=False, message="constitution denied")

        escalated = check == ConstitutionAction.ESCALATE

        return GiftResult(
            success=True,
            message=f"{request.lane.value} gift approved",
            escalated=escalated,
            gift_id=request.gift_id,
        )
    except Exception:
        return GiftResult(success=False, message="internal error (fail-soft)")
