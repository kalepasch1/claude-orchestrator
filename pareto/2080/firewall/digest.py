"""The monthly one-card digest.

One card, plain language, no jargon — the whole point of the P2 firewall is that a
household reads one thing a month instead of a stack of mail. So this module is
deliberately austere about what it reports: what came in, what was acted on, what it
saved, and what is still waiting on a human click.

Blocked items are reported FIRST and are never omitted, even when the digest is
otherwise empty. A digest that quietly drops the things the firewall could not do
would make an under-provisioned budget look like a quiet month.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

from negotiate import verify_receipt


@dataclass
class MonthlyDigest:
    """A month of firewall activity, summarised for one card."""
    period: str = ""
    items_seen: int = 0
    items_parsed: int = 0
    negotiations_attempted: int = 0
    disputes_drafted: int = 0
    total_saved: float = 0.0
    awaiting_approval: int = 0
    receipts: List[Any] = field(default_factory=list)
    blocked: List[str] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)

    def render(self) -> str:
        """The card, as plain text."""
        return "\n".join(self.lines)


def _reason_line(result: Any) -> str:
    decision = getattr(result, "decision", None)
    reason = getattr(decision, "reason", "") if decision is not None else ""
    kind = getattr(result, "item_kind", "") or getattr(result, "reason", "")
    vendor = getattr(result, "vendor", "") or "an unnamed vendor"
    return f"{kind or 'item'} from {vendor}: {reason or 'not actioned'}"


def build(items: Any = None, negotiations: Any = None, disputes: Any = None,
          period: str = "") -> MonthlyDigest:
    """Assemble the digest. Never raises — a digest that fails is a month unreported."""
    digest = MonthlyDigest(period=period)
    items = list(items or [])
    negotiations = list(negotiations or [])
    disputes = list(disputes or [])

    digest.items_seen = len(items)
    digest.items_parsed = sum(1 for i in items if getattr(i, "parsed", False))

    for result in negotiations:
        if getattr(result, "attempted", False):
            digest.negotiations_attempted += 1
            digest.total_saved += float(getattr(result, "amount_saved", 0.0) or 0.0)
            receipt = getattr(result, "receipt", None)
            if receipt is not None:
                digest.receipts.append(receipt)
        else:
            decision = getattr(result, "decision", None)
            if decision is not None and getattr(decision, "requires_approval", False):
                digest.awaiting_approval += 1
            digest.blocked.append(_reason_line(result))

    for letter in disputes:
        if getattr(letter, "drafted", False):
            digest.disputes_drafted += 1
            receipt = getattr(letter, "receipt", None)
            if receipt is not None:
                digest.receipts.append(receipt)
        else:
            decision = getattr(letter, "decision", None)
            if decision is not None and getattr(decision, "requires_approval", False):
                digest.awaiting_approval += 1
            digest.blocked.append(_reason_line(letter))

    digest.total_saved = round(digest.total_saved, 2)

    header = f"Your {period} summary" if period else "Your monthly summary"
    digest.lines = [
        header,
        f"We looked at {digest.items_seen} item(s) and understood {digest.items_parsed}.",
        f"We negotiated {digest.negotiations_attempted} and drafted "
        f"{digest.disputes_drafted} dispute letter(s).",
        f"Expected saving: ${digest.total_saved:.2f}.",
    ]
    if digest.awaiting_approval:
        digest.lines.append(
            f"{digest.awaiting_approval} item(s) are waiting for your approval before "
            f"we can act.")
    if digest.blocked:
        digest.lines.append("Not actioned:")
        digest.lines.extend(f"  - {line}" for line in digest.blocked)
    return digest


def verify_all(digest: MonthlyDigest) -> bool:
    """True when every receipt in the digest carries a valid signature.

    An unsigned or tampered receipt in a month's digest means the saving it claims
    cannot be relied on, so this is all-or-nothing rather than a count.
    """
    receipts = getattr(digest, "receipts", []) or []
    return all(verify_receipt(r) for r in receipts)
