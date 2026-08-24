"""Re-export shim: the canonical family contracts live at hisanta/contracts/family.py.

This file used to be a second, independently-maintained copy of the same domain.
The two drifted: the nested copy grew the quest/grandma/gifting/school types
while the top-level one grew the approval/kindness types, and because every
consumer imports `hisanta.contracts.family` (absolute), the nested definitions
were unreachable dead code that still had to be kept in sync by hand.

The canonical module was already written to be the *union* — every symbol either
file ever exported is defined there, with a shape that satisfies both sets of
callers. So this module is now a pure re-export. Behaviour is preserved exactly:
`hisanta.hisanta.contracts.family.X is hisanta.contracts.family.X` for every X,
which means an isinstance check or an enum identity comparison cannot fail just
because a caller reached the domain by the nested path.

Same convention as the root `merged_diff_library.py` shim over
`runner/merged_diff_library.py`. Do not add definitions here — add them to
hisanta/contracts/family.py and extend the re-export list below.
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
