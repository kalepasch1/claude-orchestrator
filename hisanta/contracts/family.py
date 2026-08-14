"""Shared family contracts for hisanta modules.

CANONICAL MODULE. `hisanta/hisanta/contracts/family.py` is a second, older copy of
the same domain that drifted: it grew the quest/grandma/gifting/school types while
this file kept the approval/kindness types. Because `hisanta.contracts.family`
resolves HERE, every symbol that only existed in the nested copy was unimportable
and three test modules failed at collection.

The fix is a union, not a replacement: every symbol either file ever exported is
exported here, with each one's existing defaults and call sites preserved. Where
the two copies defined the same name with different shapes (ParentApproval,
CoppaConsent, ParentVerificationReceipt, constitution_check) the definition below
satisfies BOTH sets of callers rather than picking a winner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import time


class ApprovalStatus(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"


class QuestKind(Enum):
    READING = "READING"
    MATH = "MATH"
    KINDNESS = "KINDNESS"


class GiftLane(Enum):
    AD_HOC = "AD_HOC"
    ADVENT = "ADVENT"
    EARNED_REWARD = "EARNED_REWARD"


class ConstitutionVerdict(Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


# The gifting protocol (hisanta/hisanta/gifting/protocol.py) and its tests refer to
# this name. It is an ALIAS, not a second enum, so `ConstitutionAction.ESCALATE is
# ConstitutionVerdict.ESCALATE` and a single constitution_check can serve both.
ConstitutionAction = ConstitutionVerdict


# Actions that must never proceed.
DENY_ACTIONS = frozenset({"charge_child", "open_ended_child_chat"})

# F1 escalation: anything that spends money or speaks to a child goes to an adult.
# Union of the two prior escalate sets — dropping either would silently allow an
# action that one half of the codebase expects to be gated.
ESCALATE_ACTIONS = frozenset({
    "loot", "gift", "ai_message",
    "purchase", "advent_gift", "earned_reward", "match_jar",
})


def constitution_check(action_type: str) -> ConstitutionVerdict:
    """Gate an action. Fail-closed on the deny list, adult-gated on the escalate list."""
    if action_type in DENY_ACTIONS:
        return ConstitutionVerdict.DENY
    if action_type in ESCALATE_ACTIONS:
        return ConstitutionVerdict.ESCALATE
    return ConstitutionVerdict.ALLOW


@dataclass
class ParentVerificationReceipt:
    """Receipt from a parent verifying a child's real-world kindness act."""
    parent_id: str = ""
    child_id: str = ""
    quest_id: str = ""
    description: str = ""
    timestamp: float = field(default_factory=time.time)
    verified: bool = True
    signature: str = ""


@dataclass
class ParentApproval:
    """Parent approval gate for purchase/gift actions.

    Every field defaults so `ParentApproval()` is valid, while the positional
    parent_id/child_id/action_id call sites in the gifting protocol still work.
    """
    parent_id: str = ""
    child_id: str = ""
    action_id: str = ""
    status: ApprovalStatus = ApprovalStatus.APPROVED
    approved: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class CoppaConsent:
    """COPPA consent record for a child in a school context."""
    child_id: str = ""
    parent_id: str = ""
    school_id: str = ""
    granted: bool = True
    consented: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class RewardCoins:
    """Reward coins minted for completing kindness quests (kindness mint)."""
    amount: int = 0
    child_id: str = ""
    quest_id: str = ""
    source: str = "kindness_mint"


@dataclass
class RewardCoin:
    """A single coin, optionally backed by a parent verification receipt."""
    amount: int = 1
    receipt: Optional[ParentVerificationReceipt] = None


@dataclass
class Quest:
    kind: QuestKind
    description: str = ""
    completed: bool = False


@dataclass
class RewardSchedule:
    schedule_type: str = "fixed"
    variable_ratio_coupled_to_purchase: bool = False


@dataclass
class MasteryEfficacyMetric:
    subject: str
    score: float = 0.0
    attempts: int = 0


@dataclass
class GrandmaStorySlot:
    story_id: str
    duration_seconds: int = 120
    recorded: bool = False


@dataclass
class MilestoneReaction:
    """Milestone reaction data. child_name is a PII field."""
    milestone_id: str
    reaction_text: str
    child_name: str = ""  # PII field
    approved: bool = False


# Only these may leave the system for a milestone reaction. child_name is absent
# by construction, so a serializer built from this set cannot leak it.
PII_FREE_FIELDS = frozenset({"milestone_id", "reaction_text", "approved"})


@dataclass
class MatchJar:
    balance: float = 0.0
    lane: GiftLane = GiftLane.AD_HOC


@dataclass
class SchoolQuest:
    quest: Optional[Quest] = None
    classroom: str = ""


@dataclass
class ClassroomCohort:
    name: str
    members: List = field(default_factory=list)
