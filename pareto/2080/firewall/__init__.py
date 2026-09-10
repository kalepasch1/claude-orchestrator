"""P2v2 Delegation firewall.

The layer between a household's inbox and its money. Inbound bills, mail and email are
parsed and classified (`intake`), every action is gated by graduated authority
(`authority`), and the actions themselves — negotiation (`negotiate`) and dispute
drafting (`disputes`) — run in simulation and produce signed receipts. `digest` renders
the month as one card.

TWO FAILURE DIRECTIONS, ON PURPOSE
----------------------------------
`intake` and `digest` FAIL SOFT: a malformed document is skipped with a note and the
rest of the inbox is still processed, because the cost of a parse failure is one item
missed. `authority` FAILS CLOSED: anything it cannot positively establish as within
budget is denied, because the cost of a gate failure is unbounded spending. Nothing in
this package moves money or sends mail; every output is a draft plus a receipt.

'2080' is not a valid Python identifier, so this package is imported by putting its
own directory on sys.path — the convention the sibling `mesh` package already follows.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from authority import (  # noqa: E402
    KNOWN_TIERS,
    AuthorityDecision,
    TrustRatchet,
    approval_only_budget,
    authorize,
    capped_budget,
    unlimited_budget,
)
from digest import MonthlyDigest, build as build_digest, verify_all  # noqa: E402
from disputes import (  # noqa: E402
    REASON_DUPLICATE,
    REASON_INCORRECT_AMOUNT,
    REASON_NOT_RECEIVED,
    REASON_UNAUTHORIZED,
    DisputeLetter,
    draft as draft_dispute,
)
from intake import (  # noqa: E402
    KIND_BILL,
    KIND_DISPUTE,
    KIND_FEE,
    KIND_RATE_CHANGE,
    KIND_SUBSCRIPTION,
    KIND_UNKNOWN,
    InboundItem,
    classify,
    parse,
    parse_batch,
)
from negotiate import (  # noqa: E402
    NegotiationResult,
    simulate,
    simulate_batch,
    sign_receipt,
    verify_receipt,
)

__all__ = [
    "AuthorityDecision", "TrustRatchet", "KNOWN_TIERS", "authorize",
    "approval_only_budget", "capped_budget", "unlimited_budget",
    "InboundItem", "classify", "parse", "parse_batch",
    "KIND_BILL", "KIND_FEE", "KIND_RATE_CHANGE", "KIND_SUBSCRIPTION",
    "KIND_DISPUTE", "KIND_UNKNOWN",
    "NegotiationResult", "simulate", "simulate_batch",
    "sign_receipt", "verify_receipt",
    "DisputeLetter", "draft_dispute", "REASON_UNAUTHORIZED",
    "REASON_INCORRECT_AMOUNT", "REASON_DUPLICATE", "REASON_NOT_RECEIVED",
    "MonthlyDigest", "build_digest", "verify_all",
]
