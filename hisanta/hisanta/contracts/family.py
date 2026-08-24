"""Re-export shim: the canonical family contracts live at hisanta/contracts/family.py.

This file used to be a second, independently-maintained copy of the same domain.
The two drifted: the nested copy grew the quest/grandma/gifting/school types
while the top-level one grew the approval/kindness types, and because every
consumer imports `hisanta.contracts.family` (absolute), the two spellings
resolved to DIFFERENT ParentApproval / CoppaConsent / ConstitutionVerdict
objects depending on which directory happened to be on sys.path.

The canonical module is the *union* — every symbol either file ever exported is
defined there, with a shape that satisfies both sets of callers. So this module
is now a pure re-export:
`hisanta.hisanta.contracts.family.X is hisanta.contracts.family.X` for every X,
which means an isinstance check or an enum identity comparison cannot fail just
because a caller reached the domain by the nested path.

Do not add definitions here — add them to hisanta/contracts/family.py and extend
the re-export list below. `hisanta/tests/test_family_contract_single_source.py`
fails if this module ever declares anything of its own again.
"""

from __future__ import annotations

from hisanta.contracts.family import (  # noqa: F401  (re-export)
    ApprovalStatus,
    ClassroomCohort,
    ConstitutionAction,
    ConstitutionVerdict,
    CoppaConsent,
    DENY_ACTIONS,
    ESCALATE_ACTIONS,
    GiftLane,
    GrandmaStorySlot,
    MasteryEfficacyMetric,
    MatchJar,
    MilestoneReaction,
    PII_FREE_FIELDS,
    ParentApproval,
    ParentVerificationReceipt,
    Quest,
    QuestKind,
    RewardCoin,
    RewardCoins,
    RewardSchedule,
    SchoolQuest,
    constitution_check,
)

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
