"""P5v2 Intergenerational mesh.

Household authority across generations: guardianship edges (`passport`), the
aging-parent reverse trust-ratchet (`takeover`), estate continuity (`estate`),
and child lanes graduating to their own accounts (`child_lanes`).

Every authority transition in this package FAILS CLOSED — insufficient
authority leaves state exactly as it was — and every parser FAILS SOFT on a
malformed graph, skipping the bad entry with a warning rather than raising.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from passport import (  # noqa: E402
    AUTHORITY_DEPENDENT,
    AUTHORITY_GUARDIAN,
    AUTHORITY_MEMBER,
    MAX_CHAIN_DEPTH,
    build_mesh,
    guardians_of,
    has_authority_over,
    make_passport,
    wards_of,
)
from takeover import (  # noqa: E402
    DEFAULT_CAPPED_USD,
    HouseholdReverseRatchet,
    graduated_takeover,
)
from estate import (  # noqa: E402
    DEFAULT_REVIEW_DAYS,
    EstateDocument,
    continuity_report,
    orphaned_beneficiaries,
    stale_documents,
    sync_beneficiaries,
)
from child_lanes import (  # noqa: E402
    STAGE_AGE_FLOOR,
    STAGE_ASSISTED,
    STAGE_INDEPENDENT,
    STAGE_SUPERVISED,
    ChildLane,
    graduate,
    lanes_ready_to_graduate,
    open_own_account,
)

__all__ = [
    # passport
    "AUTHORITY_DEPENDENT", "AUTHORITY_GUARDIAN", "AUTHORITY_MEMBER",
    "MAX_CHAIN_DEPTH", "build_mesh", "guardians_of", "has_authority_over",
    "make_passport", "wards_of",
    # takeover
    "DEFAULT_CAPPED_USD", "HouseholdReverseRatchet", "graduated_takeover",
    # estate
    "DEFAULT_REVIEW_DAYS", "EstateDocument", "continuity_report",
    "orphaned_beneficiaries", "stale_documents", "sync_beneficiaries",
    # child lanes
    "STAGE_AGE_FLOOR", "STAGE_ASSISTED", "STAGE_INDEPENDENT",
    "STAGE_SUPERVISED", "ChildLane", "graduate", "lanes_ready_to_graduate",
    "open_own_account",
]
