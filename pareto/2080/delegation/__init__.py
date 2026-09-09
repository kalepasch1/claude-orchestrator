"""delegation — the P2 delegation firewall for the 2080 autonomy stack.

Public surface. Importing this package gives a caller the entry points it needs
without having to know the sys.path convention the modules below use.

'2080' is not a valid Python identifier, so `pareto.2080.delegation` is
unspellable. `pareto/__init__.py` registers this package as `pareto.delegation`
so the dotted import works; the sys.path insert below is what lets the sibling
modules keep importing each other by bare name, which is the convention already
used by pareto/2080/household_legal/ and pareto/2080/contracts/.

Every public entry point degrades gracefully: it returns a safe default rather
than raising, because this package sits between untrusted inbound mail and a
budget that can spend the holder's money.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from intake import (  # noqa: E402
    InboundItem,
    classify,
    parse_inbound,
)
from authority import (  # noqa: E402
    DEFAULT_CAP_USD,
    Decision,
    authorize,
)
from negotiate import (  # noqa: E402
    NegotiationProposal,
    PeriodObservation,
    detect_subscription_creep,
    propose,
    settle,
)
from disputes import (  # noqa: E402
    DRAFT_FOOTER,
    DRAFT_HEADER,
    GROUNDS,
    DisputeDraft,
    draft,
    render,
)

__all__ = [
    "DisputeDraft",
    "draft",
    "render",
    "DRAFT_HEADER",
    "DRAFT_FOOTER",
    "GROUNDS",
    "InboundItem",
    "classify",
    "parse_inbound",
    "Decision",
    "authorize",
    "DEFAULT_CAP_USD",
    "NegotiationProposal",
    "PeriodObservation",
    "detect_subscription_creep",
    "propose",
    "settle",
]
