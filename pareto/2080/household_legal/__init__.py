"""household_legal — regime-aware document updates for the P4 autonomy stack.

Reachable as `pareto.household_legal` (see pareto/__init__.py, which extends
__path__ over the 2080 stack because `2080` is not a valid Python identifier).

Everything here is fail-soft by contract: an oracle outage degrades to "no
events this pass", a failed update returns the ORIGINAL document untouched, and
an escalation is a recommendation a human acts on, never an automatic charge.
"""
import os as _os
import sys as _sys

# The modules import each other by bare name (the convention established by
# pareto/2080/contracts/test_contracts_smoke.py), so the package directory has
# to be importable in its own right.
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from regime_consumer import (  # noqa: E402
    NoOpRegimeOracle,
    consume_oracle_events,
    get_regime_oracle,
    normalize_regime_event,
    safe_consume_regime_event,
    safe_subscribe,
)
from doc_updater import DocumentUpdater  # noqa: E402
from subscription_tier import (  # noqa: E402
    SubscriptionTierMonitor,
    TierEvaluation,
    evaluate_tier,
)

__all__ = [
    "DocumentUpdater",
    "NoOpRegimeOracle",
    "SubscriptionTierMonitor",
    "TierEvaluation",
    "consume_oracle_events",
    "evaluate_tier",
    "get_regime_oracle",
    "normalize_regime_event",
    "safe_consume_regime_event",
    "safe_subscribe",
]
