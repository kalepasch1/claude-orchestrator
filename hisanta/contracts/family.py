<<<<<<< HEAD
"""Shared interfaces/types for the hisanta family domain — the ONE definition.
=======
"""Shared family contracts for hisanta modules.
>>>>>>> agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3

Interfaces and types only: no engine, no I/O, no policy beyond the constitution
table itself.

WHY THIS FILE IS THE CANONICAL ONE.  Two files both spelled the module
`hisanta.contracts.family` — this one and `hisanta/hisanta/contracts/family.py` —
with DIFFERENT definitions of ParentApproval, ParentVerificationReceipt,
CoppaConsent and constitution_check.  Which one a caller got depended on which
directory happened to be on sys.path, so an isinstance check or an enum identity
comparison could fail across the seam and three test modules died at collection.

Both branches that tried to fix it agreed on the shape of the union and
disagreed only about WHICH file should hold it; the tree was committed with the
conflict markers still in, so neither answer was in force.  The definitions live
HERE, in the directory `hisanta.contracts` resolves to first, because
`hisanta/hisanta/` is a packaging accident that should eventually be deleted and
canonical code must not live inside it.  The nested module is a re-export shim.

The union preserves both sets of callers: where the two copies named the same
fact differently (ParentApproval.approved/status, CoppaConsent.consented/granted)
both spellings are kept, and ConstitutionAction is an ALIAS of
ConstitutionVerdict rather than a second enum, so a verdict compares equal by
identity no matter which half of the codebase produced it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
<<<<<<< HEAD


# ── Mastery ──────────────────────────────────────────────────────────────────

=======
from typing import List, Optional
import time


class ApprovalStatus(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"


>>>>>>> agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3
class QuestKind(Enum):
    READING = "READING"
    MATH = "MATH"
    KINDNESS = "KINDNESS"


<<<<<<< HEAD
=======
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


>>>>>>> agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3
@dataclass
class Quest:
    kind: QuestKind
    description: str = ""
    completed: bool = False


@dataclass
class RewardSchedule:
    schedule_type: str = "fixed"
    # Deliberately False by default: coupling a variable-ratio reward schedule
    # to a purchase is the loot-box pattern, and it must never be the default.
    variable_ratio_coupled_to_purchase: bool = False


@dataclass
class MasteryEfficacyMetric:
    subject: str
    score: float = 0.0
    attempts: int = 0


# ── Constitution ─────────────────────────────────────────────────────────────

class ConstitutionVerdict(Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


#: Historical name used by the gifting stack. Same enum object, not a copy —
#: `ConstitutionAction.ESCALATE is ConstitutionVerdict.ESCALATE` holds, which is
#: what stops the two halves of the codebase disagreeing about a verdict.
ConstitutionAction = ConstitutionVerdict

#: Never permitted. A child never spends real money and never gets an
#: open-ended AI chat surface.
DENY_ACTIONS = frozenset({"charge_child", "open_ended_child_chat"})

#: Permitted only behind an adult. Every value-transfer lane is here.
ESCALATE_ACTIONS = frozenset({
    "loot",
    "gift",
    "ai_message",
    "purchase",
    "advent_gift",
    "earned_reward",
    "match_jar",
})


def constitution_check(action: str) -> ConstitutionVerdict:
    """Check an action against the constitution.

    DENY for the hard bright lines, ESCALATE for anything that moves value or
    speaks to a child, ALLOW otherwise. Unknown actions ALLOW by design: this
    is a routing table for named actions, not an authorization gate — the
    purchase seams fail closed on their own (see gifting.protocol).
    """
    if action in DENY_ACTIONS:
        return ConstitutionVerdict.DENY
    if action in ESCALATE_ACTIONS:
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
    """Milestone reaction data. child_name is a PII field."""
    milestone_id: str
    reaction_text: str
    child_name: str = ""  # PII field
    approved: bool = False


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


class ApprovalStatus(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"


@dataclass
class ParentApproval:
    """Parent approval gate for purchase/gift actions.

    Carries both spellings the codebase grew: `approved` (the boolean the
    mastery/contract tests read) and `status` (the tri-state the gifting
    protocol switches on). Every field is defaulted so `ParentApproval()` is
    constructible, which is what the contract tests assert.
    """
    approved: bool = False
    parent_id: str = ""
    child_id: str = ""
    action_id: str = ""
    status: ApprovalStatus = ApprovalStatus.APPROVED
    timestamp: float = field(default_factory=time.time)


@dataclass
class ParentVerificationReceipt:
    """Receipt from a parent verifying a child's real-world kindness act.

    A receipt only exists because a parent produced it, so `verified` defaults
    to True; the mint still refuses receipts with `verified=False` or missing
    ids, so the fail-closed path is enforced at the mint, not by this default.
    """
    verified: bool = True
    parent_id: str = ""
    child_id: str = ""
    quest_id: str = ""
    description: str = ""
    timestamp: float = field(default_factory=time.time)
    signature: str = ""


@dataclass
class RewardCoin:
    """A single earned coin. Minting requires a parent receipt."""
    amount: int = 1
    receipt: ParentVerificationReceipt | None = None


@dataclass
class RewardCoins:
    """A minted batch of coins for one completed kindness quest."""
    amount: int = 0
    child_id: str = ""
    quest_id: str = ""
    source: str = "kindness_mint"


# ── School ───────────────────────────────────────────────────────────────────

@dataclass
class SchoolQuest:
    quest: Quest | None = None
    classroom: str = ""


@dataclass
class ClassroomCohort:
    name: str
<<<<<<< HEAD
    members: list = field(default_factory=list)


@dataclass
class CoppaConsent:
    """COPPA consent record for a child in a school context.

    `consented` and `granted` are the two names the codebase grew for the same
    fact; both are kept so neither caller breaks.
    """
    consented: bool = False
    parent_id: str = ""
    child_id: str = ""
    school_id: str = ""
    granted: bool = True
    timestamp: float = field(default_factory=time.time)


__all__ = [
    "ApprovalStatus",
    "ClassroomCohort",
    "ConstitutionAction",
    "ConstitutionVerdict",
    "CoppaConsent",
    "DENY_ACTIONS",
    "ESCALATE_ACTIONS",
    "GiftLane",
    "GrandmaStorySlot",
    "MasteryEfficacyMetric",
    "MatchJar",
    "MilestoneReaction",
    "PII_FREE_FIELDS",
    "ParentApproval",
    "ParentVerificationReceipt",
    "Quest",
    "QuestKind",
    "RewardCoin",
    "RewardCoins",
    "RewardSchedule",
    "SchoolQuest",
    "constitution_check",
]
=======
    members: List = field(default_factory=list)
>>>>>>> agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3
