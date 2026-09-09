"""Auto-negotiation bots for bills, rates, fees and subscription creep.

Every negotiation runs in SIMULATION and produces a signed `Receipt`. Nothing here
sends anything or moves money; `simulate()` returns the draft and the receipt, and a
caller that wants to act on it does so behind its own gate.

The authority gate is checked BEFORE the negotiation is simulated, not after. Checking
afterwards would mean the work is done and the only thing standing between a denied
budget and a sent letter is the caller remembering to look at a boolean.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any, List, Optional

from _contracts import make_receipt
from authority import AuthorityDecision, authorize
from intake import KIND_BILL, KIND_FEE, KIND_RATE_CHANGE, KIND_SUBSCRIPTION, InboundItem

#: Expected savings rate per item kind, from what these negotiations typically recover.
#: Deliberately conservative — a simulation that promises more than it delivers is how
#: an autonomy stack loses the trust the ratchet is supposed to be measuring.
SAVINGS_RATE = {
    KIND_FEE: 1.00,           # a wrongly-applied fee is usually reversed in full
    KIND_RATE_CHANGE: 0.50,   # rate increases are commonly halved or deferred
    KIND_SUBSCRIPTION: 0.30,  # retention offers cluster around a third off
    KIND_BILL: 0.15,          # a standard bill has the least give
}

#: Signing key for receipts. A real deployment injects a per-household secret; the
#: default is a fixed, obviously-not-secret string so tests are deterministic and so
#: an unconfigured deployment produces verifiable-but-clearly-unsigned receipts
#: rather than silently unsigned ones.
DEFAULT_SIGNING_KEY = b"pareto-2080-firewall-unconfigured"


@dataclass
class NegotiationResult:
    """What a simulated negotiation produced."""
    attempted: bool = False
    item_kind: str = ""
    vendor: str = ""
    original_usd: float = 0.0
    proposed_usd: float = 0.0
    amount_saved: float = 0.0
    draft: str = ""
    receipt: Any = None
    decision: Optional[AuthorityDecision] = None
    notes: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.attempted)


def sign_receipt(receipt: Any, key: bytes = DEFAULT_SIGNING_KEY) -> str:
    """A deterministic HMAC over the receipt's meaningful fields.

    The timestamp is included: two otherwise-identical negotiations of the same bill
    are different events, and a signature that could not tell them apart would let one
    receipt stand in for the other.
    """
    payload = "|".join([
        str(getattr(receipt, "action", "")),
        str(getattr(receipt, "explanation", "")),
        f"{float(getattr(receipt, 'amount_saved', 0.0)):.2f}",
        f"{float(getattr(receipt, 'timestamp', 0.0)):.6f}",
    ]).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_receipt(receipt: Any, key: bytes = DEFAULT_SIGNING_KEY) -> bool:
    """True when the receipt's signature matches its contents.

    Constant-time compare: a receipt signature is an authorisation artefact, and
    `==` on a hex digest leaks it a character at a time.
    """
    claimed = str(getattr(receipt, "signature", "") or "")
    if not claimed:
        return False
    return hmac.compare_digest(claimed, sign_receipt(receipt, key=key))


def _draft_for(item: InboundItem, proposed: float) -> str:
    vendor = item.vendor or "your team"
    if item.kind == KIND_FEE:
        return (f"Hello {vendor},\n\nI'm writing about a fee of "
                f"${item.amount_usd:.2f} on my account. I've been a customer in good "
                f"standing and would like to request this fee be waived.\n\n"
                f"Thank you for reviewing.")
    if item.kind == KIND_RATE_CHANGE:
        return (f"Hello {vendor},\n\nI received notice of a rate increase to "
                f"${item.amount_usd:.2f}. I'd like to discuss keeping my rate closer "
                f"to ${proposed:.2f}, or what options exist to offset the increase.\n\n"
                f"Thank you.")
    if item.kind == KIND_SUBSCRIPTION:
        return (f"Hello {vendor},\n\nI'm reviewing my recurring subscriptions and am "
                f"considering cancelling this one at ${item.amount_usd:.2f}. Before I "
                f"do, is there a retention rate available closer to "
                f"${proposed:.2f}?\n\nThank you.")
    return (f"Hello {vendor},\n\nI'm reviewing an invoice for "
            f"${item.amount_usd:.2f}. Could you confirm the charges and let me know "
            f"whether any adjustment or payment plan is available?\n\nThank you.")


def simulate(item: InboundItem, budget: Any, approved: bool = False,
             signing_key: bytes = DEFAULT_SIGNING_KEY) -> NegotiationResult:
    """Simulate negotiating one item. Never sends anything.

    Returns `attempted=False` with the denying decision attached whenever authority
    is refused, so a caller cannot mistake "not permitted" for "nothing to save".
    """
    kind = getattr(item, "kind", "")
    result = NegotiationResult(item_kind=kind, vendor=getattr(item, "vendor", ""))

    if not getattr(item, "parsed", False):
        result.notes.append("item did not parse; nothing to negotiate")
        return result
    if not getattr(item, "negotiable", False):
        result.notes.append(f"no negotiation play for kind '{kind}'")
        return result

    amount = getattr(item, "amount_usd", None)
    if amount is None:
        result.notes.append("no amount on the item; cannot quantify a saving")
        return result

    # Authority first. The exposure being gated is the amount at stake.
    decision = authorize(budget, amount_usd=amount, approved=approved)
    result.decision = decision
    result.original_usd = float(amount)
    if not decision.permitted:
        result.notes.append(f"authority denied: {decision.reason}")
        return result

    saved = round(float(amount) * SAVINGS_RATE.get(kind, 0.0), 2)
    proposed = round(float(amount) - saved, 2)
    draft = _draft_for(item, proposed)

    receipt = make_receipt(
        explanation=(f"Simulated negotiation on a {kind.replace('_', ' ')} from "
                     f"{result.vendor or 'an unnamed vendor'}: proposed "
                     f"${proposed:.2f} against ${float(amount):.2f}, "
                     f"an expected saving of ${saved:.2f}."),
        amount_saved=saved,
        action=f"negotiate:{kind}",
    )
    receipt.signature = sign_receipt(receipt, key=signing_key)

    result.attempted = True
    result.proposed_usd = proposed
    result.amount_saved = saved
    result.draft = draft
    result.receipt = receipt
    return result


def simulate_batch(items: Any, budget: Any, approved: bool = False,
                   signing_key: bytes = DEFAULT_SIGNING_KEY) -> List[NegotiationResult]:
    """Simulate a whole inbox. One bad item never costs the others."""
    out: List[NegotiationResult] = []
    for item in (items or []):
        try:
            out.append(simulate(item, budget, approved=approved, signing_key=signing_key))
        except Exception as exc:  # noqa: BLE001 - fail soft across the batch
            failed = NegotiationResult(item_kind=getattr(item, "kind", ""))
            failed.notes.append(f"negotiation fault: {type(exc).__name__}: {exc}")
            out.append(failed)
    return out
