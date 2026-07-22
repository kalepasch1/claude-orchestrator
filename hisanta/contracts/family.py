"""Shared family contracts for hisanta modules."""
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import time


class ApprovalStatus(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"


@dataclass
class ParentVerificationReceipt:
    """Receipt from a parent verifying a child's real-world kindness act."""
    parent_id: str
    child_id: str
    quest_id: str
    description: str
    timestamp: float = field(default_factory=time.time)
    verified: bool = True
    signature: str = ""


@dataclass
class ParentApproval:
    """Parent approval gate for purchase/gift actions."""
    parent_id: str
    child_id: str
    action_id: str
    status: ApprovalStatus = ApprovalStatus.APPROVED
    timestamp: float = field(default_factory=time.time)


@dataclass
class CoppaConsent:
    """COPPA consent record for a child in a school context."""
    child_id: str
    parent_id: str
    school_id: str
    granted: bool = True
    timestamp: float = field(default_factory=time.time)


@dataclass
class RewardCoins:
    """Reward coins minted for completing kindness quests."""
    amount: int
    child_id: str
    quest_id: str
    source: str = "kindness_mint"


class ConstitutionAction(Enum):
    ALLOW = "allow"
    ESCALATE = "escalate"
    DENY = "deny"


def constitution_check(action_type: str) -> ConstitutionAction:
    """F1 escalation: gift actions ESCALATE via constitution_check."""
    gift_actions = {"gift", "purchase", "advent_gift", "earned_reward", "match_jar"}
    if action_type in gift_actions:
        return ConstitutionAction.ESCALATE
    return ConstitutionAction.ALLOW
