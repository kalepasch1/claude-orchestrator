"""Shared interfaces/types for the hisanta family domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QuestKind(Enum):
    READING = "READING"
    MATH = "MATH"
    KINDNESS = "KINDNESS"


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


class ConstitutionVerdict(Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


def constitution_check(action: str) -> ConstitutionVerdict:
    """Check an action against the constitution rules.

    Denies: charge_child, open_ended_child_chat
    Escalates: loot, gift, ai_message
    Allows: everything else
    """
    deny_actions = {"charge_child", "open_ended_child_chat"}
    escalate_actions = {"loot", "gift", "ai_message"}

    if action in deny_actions:
        return ConstitutionVerdict.DENY
    if action in escalate_actions:
        return ConstitutionVerdict.ESCALATE
    return ConstitutionVerdict.ALLOW


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


PII_FREE_FIELDS = frozenset({"milestone_id", "reaction_text", "approved"})


class GiftLane(Enum):
    AD_HOC = "AD_HOC"
    ADVENT = "ADVENT"
    EARNED_REWARD = "EARNED_REWARD"


@dataclass
class MatchJar:
    balance: float = 0.0
    lane: GiftLane = GiftLane.AD_HOC


@dataclass
class ParentApproval:
    approved: bool = False
    parent_id: str = ""


@dataclass
class ParentVerificationReceipt:
    verified: bool = False
    parent_id: str = ""


@dataclass
class RewardCoin:
    amount: int = 1
    receipt: ParentVerificationReceipt | None = None


@dataclass
class SchoolQuest:
    quest: Quest | None = None
    classroom: str = ""


@dataclass
class ClassroomCohort:
    name: str
    members: list = field(default_factory=list)


@dataclass
class CoppaConsent:
    consented: bool = False
    parent_id: str = ""
