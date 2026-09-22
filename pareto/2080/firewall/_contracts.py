"""Shared, guarded access to `pareto/2080/contracts/autonomy.py`.

'2080' is not a valid Python identifier, so this package cannot be reached by dotted
path. Follows the repo convention (mesh/passport.py, household_legal/regime_consumer.py):
put the contracts directory on sys.path and import by bare name, guarded, with a
duck-typed fallback so the firewall stays usable in a stripped environment.

Centralised here rather than repeated in five modules: the sibling packages each carry
their own copy of this loader, and a loader that drifts between modules in one package
is how two files end up disagreeing about whether contracts were available.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


def _load_contracts_module():
    """Import the autonomy contracts module, or return None."""
    try:
        contracts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts"
        )
        if contracts_dir not in sys.path:
            sys.path.insert(0, contracts_dir)
        import autonomy  # noqa: PLC0415  (deliberately late and guarded)

        return autonomy
    except Exception as exc:  # pragma: no cover - import-environment specific
        log.warning("firewall: contracts unavailable (%s); degrading to duck-typing", exc)
        return None


contracts = _load_contracts_module()


# --- Duck-typed shims, used only when the real contracts cannot be imported ---

@dataclass
class _ShimAuthorityBudget:
    tier: Any = "approval_only"
    cap_usd: float = 0.0
    holder_id: str = ""
    description: str = ""


@dataclass
class _ShimReceipt:
    explanation: str = ""
    amount_saved: float = 0.0
    action: str = ""
    timestamp: float = 0.0
    signature: str = ""


def _tier_value(name: str, fallback: str) -> str:
    """Read a tier's value off the real enum when present.

    Hard-coding the strings would leave this package silently comparing against stale
    values after a rename in contracts — and a stale comparison in an authority check
    fails OPEN, which is the one direction this package must never fail.
    """
    tier_enum = getattr(contracts, "AuthorityTier", None) if contracts else None
    member = getattr(tier_enum, name, None) if tier_enum is not None else None
    return getattr(member, "value", fallback)


TIER_APPROVAL_ONLY = _tier_value("APPROVAL_ONLY", "approval_only")
TIER_CAPPED = _tier_value("CAPPED", "capped")
TIER_UNLIMITED = _tier_value("UNLIMITED_WITH_RECEIPTS", "unlimited_with_receipts")

#: The $500 cap the P2 spec names as the default for the capped tier.
DEFAULT_CAP_USD = 500.0


def tier_of(budget: Any) -> str:
    """The tier of a budget as a plain string, whether it is an Enum or a shim.

    Comparing an enum member against a string across an import boundary that may or
    may not have loaded evaluates False without raising — which in an authority check
    means an unrecognised tier. Every decision in this package normalises first.
    """
    tier = getattr(budget, "tier", None)
    return str(getattr(tier, "value", tier) or "")


def make_budget(tier: str = TIER_APPROVAL_ONLY, cap_usd: float = 0.0,
                holder_id: str = "", description: str = "") -> Any:
    """An AuthorityBudget from contracts, or a duck-typed equivalent."""
    if contracts is not None and hasattr(contracts, "AuthorityBudget"):
        tier_enum = getattr(contracts, "AuthorityTier", None)
        resolved: Any = tier
        if tier_enum is not None:
            for member in tier_enum:
                if member.value == tier:
                    resolved = member
                    break
        return contracts.AuthorityBudget(
            tier=resolved, cap_usd=cap_usd, holder_id=holder_id, description=description
        )
    return _ShimAuthorityBudget(
        tier=tier, cap_usd=cap_usd, holder_id=holder_id, description=description
    )


def make_receipt(explanation: str = "", amount_saved: float = 0.0, action: str = "",
                 timestamp: float = 0.0, signature: str = "") -> Any:
    """A Receipt from contracts, or a duck-typed equivalent."""
    import time as _time

    stamp = timestamp or _time.time()
    if contracts is not None and hasattr(contracts, "Receipt"):
        return contracts.Receipt(
            explanation=explanation, amount_saved=amount_saved, action=action,
            timestamp=stamp, signature=signature,
        )
    return _ShimReceipt(
        explanation=explanation, amount_saved=amount_saved, action=action,
        timestamp=stamp, signature=signature,
    )
