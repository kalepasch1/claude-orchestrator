"""Graduated-budget enforcement — the gate every firewall action passes through.

Three tiers, from the P2 spec and `contracts.autonomy.AuthorityTier`:

    APPROVAL_ONLY ($0)        every action needs a one-click approval
    CAPPED ($500 default)     spend up to the cap without asking
    UNLIMITED_WITH_RECEIPTS   no cap, but every action must produce a receipt

FAILS CLOSED, without exception. An action is permitted only when this module can
positively establish that it is within authority. Anything else — an unapproved
$0-tier action, an over-cap spend, a missing or malformed budget, an unrecognised
tier, an amount that will not parse — is DENIED.

That asymmetry is deliberate and is the whole point of the module. A parser that
fails soft returns a partial *description* of the world and the worst case is that
one bill is skipped. A gate that fails soft returns permission to spend somebody's
money, and the worst case is unbounded. `intake` fails soft; `authority` fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from _contracts import (
    DEFAULT_CAP_USD,
    TIER_APPROVAL_ONLY,
    TIER_CAPPED,
    TIER_UNLIMITED,
    make_budget,
    tier_of,
)

#: Every tier this module knows how to reason about. A budget carrying anything else
#: is not "probably fine" — it is unrecognised, and unrecognised is denied.
KNOWN_TIERS = (TIER_APPROVAL_ONLY, TIER_CAPPED, TIER_UNLIMITED)

DENY_NO_BUDGET = "no budget supplied"
DENY_UNKNOWN_TIER = "unrecognised authority tier"
DENY_BAD_AMOUNT = "amount is not a usable number"
DENY_UNAPPROVED = "approval-only tier requires a one-click approval"
DENY_OVER_CAP = "amount exceeds the tier cap"
DENY_NEGATIVE_CAP = "cap is negative"
ALLOW_APPROVED = "approved by holder"
ALLOW_WITHIN_CAP = "within cap"
ALLOW_UNLIMITED = "unlimited tier; receipt required"


@dataclass
class AuthorityDecision:
    """Why an action was permitted or refused.

    `permitted` is the only field callers should branch on, and it is False by
    default: a decision object that was constructed but never populated denies.
    """
    permitted: bool = False
    reason: str = DENY_NO_BUDGET
    tier: str = ""
    amount_usd: float = 0.0
    cap_usd: float = 0.0
    requires_receipt: bool = False
    requires_approval: bool = False

    def __bool__(self) -> bool:
        return bool(self.permitted)


def _coerce_amount(amount: Any) -> Optional[float]:
    """A finite, non-negative float, or None.

    None means "this cannot be evaluated", which the caller turns into a denial.
    Booleans are rejected explicitly: `isinstance(True, int)` is True in Python, so
    an accidental `authorize(budget, True)` would otherwise be read as $1.
    """
    if isinstance(amount, bool):
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return None
    if value < 0:
        return None
    return value


def authorize(budget: Any, amount_usd: Any = 0.0, approved: bool = False) -> AuthorityDecision:
    """Decide whether `budget` permits spending `amount_usd`.

    `approved` is the one-click approval. It is only consulted for the approval-only
    tier — an approval does not raise a capped tier above its cap, because a gate whose
    ceiling can be lifted by the same click that satisfies it has no ceiling.
    """
    if budget is None:
        return AuthorityDecision(permitted=False, reason=DENY_NO_BUDGET)

    tier = tier_of(budget)
    if tier not in KNOWN_TIERS:
        return AuthorityDecision(permitted=False, reason=DENY_UNKNOWN_TIER, tier=tier)

    value = _coerce_amount(amount_usd)
    if value is None:
        return AuthorityDecision(permitted=False, reason=DENY_BAD_AMOUNT, tier=tier)

    cap = _coerce_amount(getattr(budget, "cap_usd", 0.0))
    if cap is None:
        # A negative or unparseable cap is a malformed budget, not an unlimited one.
        return AuthorityDecision(permitted=False, reason=DENY_NEGATIVE_CAP, tier=tier,
                                 amount_usd=value)

    if tier == TIER_UNLIMITED:
        return AuthorityDecision(permitted=True, reason=ALLOW_UNLIMITED, tier=tier,
                                 amount_usd=value, cap_usd=cap, requires_receipt=True)

    if tier == TIER_APPROVAL_ONLY:
        if not approved:
            return AuthorityDecision(permitted=False, reason=DENY_UNAPPROVED, tier=tier,
                                     amount_usd=value, cap_usd=cap,
                                     requires_approval=True)
        return AuthorityDecision(permitted=True, reason=ALLOW_APPROVED, tier=tier,
                                 amount_usd=value, cap_usd=cap, requires_receipt=True,
                                 requires_approval=True)

    # CAPPED
    if value > cap:
        return AuthorityDecision(permitted=False, reason=DENY_OVER_CAP, tier=tier,
                                 amount_usd=value, cap_usd=cap, requires_approval=True)
    return AuthorityDecision(permitted=True, reason=ALLOW_WITHIN_CAP, tier=tier,
                             amount_usd=value, cap_usd=cap, requires_receipt=True)


def approval_only_budget(holder_id: str = "", description: str = "") -> Any:
    """A $0, one-click-required budget. The default posture for a new delegation."""
    return make_budget(tier=TIER_APPROVAL_ONLY, cap_usd=0.0, holder_id=holder_id,
                       description=description)


def capped_budget(holder_id: str = "", cap_usd: float = DEFAULT_CAP_USD,
                  description: str = "") -> Any:
    """A capped budget. Defaults to the $500 the P2 spec names."""
    safe_cap = _coerce_amount(cap_usd)
    return make_budget(tier=TIER_CAPPED, cap_usd=safe_cap if safe_cap is not None else 0.0,
                       holder_id=holder_id, description=description)


def unlimited_budget(holder_id: str = "", description: str = "") -> Any:
    """An unlimited tier. Every action under it must produce a receipt."""
    return make_budget(tier=TIER_UNLIMITED, cap_usd=0.0, holder_id=holder_id,
                       description=description)


@dataclass
class TrustRatchet:
    """Advance or reverse a holder's tier one step at a time.

    Satisfies `contracts.autonomy.TrustRatchet`. Advancing is deliberately one step
    per call and never skips the capped tier: the point of a ratchet is that trust is
    earned in increments, and a helper that took a holder from $0 to unlimited in one
    call would be a way around the tiers rather than an implementation of them.

    Reversal is not symmetric — it drops straight to approval-only. Trust is withdrawn
    because something went wrong, and stepping down one notch at a time would leave
    spending authority in place for exactly the holder it was just withdrawn from.
    """
    default_cap_usd: float = DEFAULT_CAP_USD
    history: list = field(default_factory=list)

    def advance(self, budget: Any) -> Any:
        tier = tier_of(budget)
        holder = getattr(budget, "holder_id", "")
        description = getattr(budget, "description", "")
        if tier == TIER_APPROVAL_ONLY:
            self.history.append(("advance", holder, TIER_CAPPED))
            return capped_budget(holder_id=holder, cap_usd=self.default_cap_usd,
                                 description=description)
        if tier == TIER_CAPPED:
            self.history.append(("advance", holder, TIER_UNLIMITED))
            return unlimited_budget(holder_id=holder, description=description)
        # Unlimited, or an unrecognised tier: nothing to advance to. Returning the
        # budget unchanged is the fail-closed answer for an unknown tier too.
        return budget

    def reverse(self, budget: Any) -> Any:
        holder = getattr(budget, "holder_id", "")
        description = getattr(budget, "description", "")
        self.history.append(("reverse", holder, TIER_APPROVAL_ONLY))
        return approval_only_budget(holder_id=holder, description=description)
