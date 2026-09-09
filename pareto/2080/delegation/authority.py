"""authority — graduated-budget enforcement for the P2 delegation firewall.

This is the module that decides whether an autonomous agent may spend the
holder's money without asking first. It is built ON TOP OF the contracts in
`pareto/2080/contracts/autonomy.py` and deliberately redefines none of them.

The single design rule: FAIL CLOSED. Every path that is not an explicit,
fully-understood permission ends in `requires_approval`. An unrecognised tier,
an amount that is negative or NaN, a missing receipt store, a budget object
that is the wrong shape — all of them route to a human rather than to a
payment. Being wrong in the direction of "ask the holder" costs a
notification; being wrong in the other direction spends money that was never
authorised.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from typing import Any, Optional

# Reach the contracts package by bare name, the convention used throughout
# pareto/2080/. contracts/ is a sibling of this package.
_HERE = os.path.dirname(os.path.abspath(__file__))
_STACK_DIR = os.path.dirname(_HERE)
_CONTRACTS_DIR = os.path.join(_STACK_DIR, "contracts")
for _p in (_CONTRACTS_DIR, _STACK_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from autonomy import (  # noqa: E402
    AuthorityBudget,
    AuthorityTier,
    Receipt,
)

__all__ = ["Decision", "authorize", "DEFAULT_CAP_USD"]

#: cap applied when a CAPPED budget carries no usable cap of its own
DEFAULT_CAP_USD = 500.0


@dataclass
class Decision:
    """The outcome of an authorization check.

    `allowed` and `requires_approval` are not simply inverse: a decision may
    be disallowed outright *and* escalatable, and callers must treat
    `requires_approval` as "do not act until a human says so" regardless of
    what `allowed` says. `allowed=True` with `requires_approval=True` is not
    a state this module ever emits.
    """

    allowed: bool = False
    requires_approval: bool = True
    reason: str = ""
    #: receipt actually written, when the tier requires one
    receipt: Optional[Receipt] = None


def _escalate(reason: str) -> Decision:
    """The only way to say no. Never allows."""
    return Decision(allowed=False, requires_approval=True, reason=reason)


def _valid_amount(amount_usd: Any) -> Optional[float]:
    """Return a usable non-negative float, or None if the amount is unusable.

    bool is rejected explicitly: `True` is an int in Python and an amount of
    `True` almost certainly means a caller passed the wrong variable.
    """
    if isinstance(amount_usd, bool) or not isinstance(amount_usd, (int, float)):
        return None
    value = float(amount_usd)
    if math.isnan(value) or math.isinf(value):
        return None
    if value < 0:
        return None
    return value


def _resolve_cap(budget: Any) -> Optional[float]:
    """Read cap_usd off a budget, falling back to the documented default."""
    raw = getattr(budget, "cap_usd", None)
    if raw is None:
        return DEFAULT_CAP_USD
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    cap = float(raw)
    if math.isnan(cap) or math.isinf(cap) or cap < 0:
        return None
    # A CAPPED budget left at the dataclass default of 0.0 has never been
    # configured. Treat it as the documented $500 rather than as a silent
    # $0 that would look like APPROVAL_ONLY by accident.
    return DEFAULT_CAP_USD if cap == 0.0 else cap


def _write_receipt(store: Any, action: str, amount_usd: float, holder_id: str) -> Optional[Receipt]:
    """Emit one receipt through the injected store. None if it did not land."""
    receipt = Receipt(
        explanation=(
            f"Auto-approved {action!r} for ${amount_usd:,.2f} under an "
            f"unlimited-with-receipts budget held by {holder_id or 'unknown holder'}."
        ),
        amount_saved=0.0,
        action=action,
    )
    try:
        store.store(receipt)
    except Exception:
        # A store that raises is a store we cannot prove wrote anything.
        return None
    return receipt


def authorize(budget, amount_usd, action, store=None) -> Decision:
    """Decide whether `action` costing `amount_usd` may proceed under `budget`.

    Returns a `Decision`; never raises. `store` is the `ReceiptStore` used by
    the UNLIMITED_WITH_RECEIPTS tier — that tier will not allow anything
    without one, because an unlimited budget whose spending leaves no trace is
    the exact failure this stack exists to prevent.
    """
    try:
        action_name = action if isinstance(action, str) and action.strip() else "<unnamed action>"

        if budget is None:
            return _escalate("no budget supplied; failing closed")

        amount = _valid_amount(amount_usd)
        if amount is None:
            return _escalate(
                f"amount {amount_usd!r} is not a usable non-negative number; failing closed"
            )

        tier = getattr(budget, "tier", None)
        holder_id = getattr(budget, "holder_id", "") or ""

        # An unknown tier is the case most likely to appear when the contracts
        # change underneath us. It must never fall through to an allow.
        if not isinstance(tier, AuthorityTier):
            return _escalate(f"unrecognised authority tier {tier!r}; failing closed")

        if tier is AuthorityTier.APPROVAL_ONLY:
            return _escalate(
                f"APPROVAL_ONLY budget never auto-allows (${amount:,.2f} for {action_name!r})"
            )

        if tier is AuthorityTier.CAPPED:
            cap = _resolve_cap(budget)
            if cap is None:
                return _escalate(
                    f"CAPPED budget has an unusable cap {getattr(budget, 'cap_usd', None)!r}; "
                    "failing closed"
                )
            if amount <= cap:
                return Decision(
                    allowed=True,
                    requires_approval=False,
                    reason=(
                        f"${amount:,.2f} is within the ${cap:,.2f} cap for {action_name!r}"
                    ),
                )
            # Explicitly NOT truncated to the cap. Partially paying a bill the
            # holder never approved is its own failure mode.
            return _escalate(
                f"${amount:,.2f} exceeds the ${cap:,.2f} cap for {action_name!r}; "
                "escalating in full, not truncating to the cap"
            )

        if tier is AuthorityTier.UNLIMITED_WITH_RECEIPTS:
            if store is None:
                return _escalate(
                    "UNLIMITED_WITH_RECEIPTS requires a ReceiptStore and none was "
                    "supplied; failing closed"
                )
            if not callable(getattr(store, "store", None)):
                return _escalate(
                    "supplied receipt store does not implement store(); failing closed"
                )
            receipt = _write_receipt(store, action_name, amount, holder_id)
            if receipt is None:
                return _escalate(
                    "receipt could not be written; refusing to allow an "
                    "unlimited-tier action that would leave no trace"
                )
            return Decision(
                allowed=True,
                requires_approval=False,
                reason=(
                    f"${amount:,.2f} allowed for {action_name!r} under "
                    "UNLIMITED_WITH_RECEIPTS; receipt recorded"
                ),
                receipt=receipt,
            )

        # Defensive: a new AuthorityTier member added upstream lands here.
        return _escalate(f"tier {tier!r} has no enforcement rule; failing closed")

    except Exception as exc:                                    # pragma: no cover
        # Absolute backstop. Any unforeseen error becomes an escalation.
        return _escalate(f"authorization check failed ({exc.__class__.__name__}); failing closed")
