"""Shared family contracts for hisanta modules.

This is the module every consumer imports (`hisanta.grandma.rail`,
`hisanta.gifting.protocol`, `hisanta.kindness.mint`, `hisanta.school.classroom`,
and all three test modules). A parallel copy of the quest/gift vocabulary grew
under `hisanta/hisanta/contracts/family.py` and the two drifted: the consumers
here import names — GiftLane, GrandmaStorySlot, MilestoneReaction,
PII_FREE_FIELDS, Quest, QuestKind, RewardSchedule — that only ever existed over
there, so `hisanta/grandma/rail.py` and two of the three test modules could not
even be imported.

This file is now the single definition point for the whole vocabulary. Nothing
was removed: every symbol that was here before is still here, with the same
name and the same meaning, and the parallel module is left untouched for its
own importers.

Where the two copies defined the SAME dataclass with different fields, the
fields are unioned rather than replaced, so neither side's callers break:
ParentApproval keeps `status` (read by gifting.protocol) and gains `approved`;
CoppaConsent keeps `granted` (read by school.classroom) and gains `consented`.

One deliberate behaviour change, called out because it is a safety gate rather
than a refactor: the consent/approval dataclasses used to default to
granted/APPROVED. Both modules that read them document themselves as
fail-closed, so a bare `CoppaConsent()` or `ParentApproval()` defaulting to
"yes" is a hole — an object nobody filled in would clear a COPPA check or a
purchase gate. Nothing in the tree constructs either without arguments, so the
defaults are now un-granted / un-approved and the fail-closed reading in
`school/classroom.py` and `gifting/protocol.py` is actually fail-closed.
"""
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
import time


# ── Quests & mastery ─────────────────────────────────────────────────────────

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
    """How a reward is paid out.

    `variable_ratio_coupled_to_purchase` is the one field here that is a policy
    control rather than a setting. A variable-ratio schedule is the slot-machine
    reinforcement pattern; coupling it to a purchase is what turns a children's
    reward loop into a gambling loop. It defaults to False so the dangerous
    configuration is never what you get by accident — it has to be typed out
    deliberately by a caller who can be held to it.
    """
    schedule_type: str = "fixed"
    variable_ratio_coupled_to_purchase: bool = False


@dataclass
class MasteryEfficacyMetric:
    subject: str
    score: float = 0.0
    attempts: int = 0


# ── Constitution ─────────────────────────────────────────────────────────────

class ConstitutionVerdict(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"


# `ConstitutionAction` was this module's original name for the same three-valued
# verdict and is imported by `hisanta.gifting.protocol`. It is an ALIAS, not a
# second enum: `ConstitutionAction.ESCALATE is ConstitutionVerdict.ESCALATE`, so
# existing equality checks in protocol.py keep working against verdicts returned
# by the updated `constitution_check`. Two separate enums with equal `.value`
# would compare False and silently break that gate.
ConstitutionAction = ConstitutionVerdict


#: Actions refused outright — charging a child, or open-ended chat with one.
_DENY_ACTIONS = frozenset({"charge_child", "open_ended_child_chat"})

#: Actions that need a human. The gift/purchase set was already escalated here;
#: `loot` and `ai_message` come from the parallel module's rule set. The union is
#: deliberate — dropping either side's entries would un-gate actions that one of
#: the two callers already believed were gated.
_ESCALATE_ACTIONS = frozenset({
    "gift", "purchase", "advent_gift", "earned_reward", "match_jar",
    "loot", "ai_message",
})


def constitution_check(action_type: str) -> ConstitutionVerdict:
    """Classify an action. Deny beats escalate; everything else is allowed."""
    if action_type in _DENY_ACTIONS:
        return ConstitutionVerdict.DENY
    if action_type in _ESCALATE_ACTIONS:
        return ConstitutionVerdict.ESCALATE
    return ConstitutionVerdict.ALLOW


# ── Grandma rail ─────────────────────────────────────────────────────────────

@dataclass
class GrandmaStorySlot:
    story_id: str
    duration_seconds: int = 120
    recorded: bool = False


@dataclass
class MilestoneReaction:
    """A reaction to a child's milestone. `child_name` is PII."""
    milestone_id: str
    reaction_text: str
    child_name: str = ""  # PII — excluded from PII_FREE_FIELDS below
    approved: bool = False


#: Fields safe to forward off-device. `child_name` is deliberately absent; this
#: set is an allowlist, so a new PII field is excluded until someone adds it.
PII_FREE_FIELDS = frozenset({"milestone_id", "reaction_text", "approved"})


# ── Gifting ──────────────────────────────────────────────────────────────────

class GiftLane(Enum):
    AD_HOC = "AD_HOC"
    ADVENT = "ADVENT"
    EARNED_REWARD = "EARNED_REWARD"


@dataclass
class MatchJar:
    balance: float = 0.0
    lane: GiftLane = GiftLane.AD_HOC


# ── Approvals & consent (fail-closed) ────────────────────────────────────────

class ApprovalStatus(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"


@dataclass
class ParentApproval:
    """Parent approval gate for purchase/gift actions.

    Defaults to PENDING / not approved: `gifting.protocol` treats a missing or
    non-approved value as a refusal, and a default-approved object would walk
    straight through that check.
    """
    approved: bool = False
    status: ApprovalStatus = ApprovalStatus.PENDING
    parent_id: str = ""
    child_id: str = ""
    action_id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ParentVerificationReceipt:
    """Receipt from a parent verifying a child's real-world kindness act."""
    verified: bool = False
    parent_id: str = ""
    child_id: str = ""
    quest_id: str = ""
    description: str = ""
    signature: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class CoppaConsent:
    """COPPA consent record for a child in a school context.

    `granted` is read by `school.classroom` as its fail-closed gate; `consented`
    is the newer name for the same fact. Both default to False so an
    unpopulated record never admits a child.
    """
    consented: bool = False
    granted: bool = False
    parent_id: str = ""
    child_id: str = ""
    school_id: str = ""
    timestamp: float = field(default_factory=time.time)


# ── Rewards ──────────────────────────────────────────────────────────────────

@dataclass
class RewardCoin:
    """A single minted coin, optionally carrying the receipt that earned it."""
    amount: int = 1
    receipt: Optional[ParentVerificationReceipt] = None


@dataclass
class RewardCoins:
    """Reward coins minted for completing kindness quests.

    Kept alongside the singular `RewardCoin`: `hisanta.kindness.mint` constructs
    this by keyword with child/quest attribution, which `RewardCoin` does not
    carry.
    """
    amount: int = 0
    child_id: str = ""
    quest_id: str = ""
    source: str = "kindness_mint"


# ── School ───────────────────────────────────────────────────────────────────

@dataclass
class SchoolQuest:
    quest: Optional[Quest] = None
    classroom: str = ""


@dataclass
class ClassroomCohort:
    name: str
    members: List[str] = field(default_factory=list)
