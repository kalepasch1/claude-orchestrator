"""Dispute-letter drafting.

Drafts only. Nothing here sends, files, or asserts a legal position on the
household's behalf — a dispute letter is a document the holder reviews and sends,
and the authority gate is checked before one is even drafted so a denied budget
does not produce a ready-to-send artefact sitting in an outbox.

Deliberately posture-agnostic: the drafts state facts the holder supplies and make a
request. They do not cite statute, name a right, or promise an outcome, because this
package cannot know the holder's jurisdiction and a template that guesses is worse
than one that does not try.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from _contracts import make_receipt
from authority import AuthorityDecision, authorize
from intake import InboundItem

#: Why a charge is being disputed. Chooses the framing, not a legal theory.
REASON_UNAUTHORIZED = "unauthorized"
REASON_INCORRECT_AMOUNT = "incorrect_amount"
REASON_DUPLICATE = "duplicate"
REASON_NOT_RECEIVED = "not_received"
REASON_OTHER = "other"

_OPENERS = {
    REASON_UNAUTHORIZED: ("I did not authorise this charge and am writing to dispute "
                          "it."),
    REASON_INCORRECT_AMOUNT: ("The amount charged does not match what I understood to "
                              "be owed, and I am writing to dispute it."),
    REASON_DUPLICATE: ("This charge appears to duplicate one already paid, and I am "
                       "writing to dispute it."),
    REASON_NOT_RECEIVED: ("I was charged for goods or services I did not receive, and "
                          "I am writing to dispute this charge."),
    REASON_OTHER: "I am writing to dispute a charge on my account.",
}


@dataclass
class DisputeLetter:
    """A drafted dispute. `drafted` False means nothing was produced."""
    drafted: bool = False
    reason: str = REASON_OTHER
    vendor: str = ""
    amount_usd: float = 0.0
    body: str = ""
    receipt: Any = None
    decision: Optional[AuthorityDecision] = None
    notes: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.drafted)


def draft(item: InboundItem, budget: Any, reason: str = REASON_OTHER,
          approved: bool = False, holder_name: str = "",
          account_ref: str = "") -> DisputeLetter:
    """Draft a dispute letter for one item.

    The authority gate is consulted first and the amount at stake is the amount being
    disputed: drafting is cheap, but a drafted letter is one click from being sent,
    and the tier that requires a click is the tier that must be asked before there is
    anything to click on.
    """
    letter = DisputeLetter(reason=reason if reason in _OPENERS else REASON_OTHER,
                           vendor=getattr(item, "vendor", ""))

    if not getattr(item, "parsed", False):
        letter.notes.append("item did not parse; nothing to dispute")
        return letter

    amount = getattr(item, "amount_usd", None)
    if amount is None:
        letter.notes.append("no amount on the item; a dispute needs a figure")
        return letter
    letter.amount_usd = float(amount)

    decision = authorize(budget, amount_usd=amount, approved=approved)
    letter.decision = decision
    if not decision.permitted:
        letter.notes.append(f"authority denied: {decision.reason}")
        return letter

    vendor = letter.vendor or "Sir or Madam"
    ref = f"\nAccount reference: {account_ref}" if account_ref else ""
    signoff = holder_name or "Account holder"
    letter.body = (
        f"Dear {vendor},{ref}\n\n"
        f"{_OPENERS[letter.reason]} The charge in question is "
        f"${letter.amount_usd:.2f}"
        + (f", dated {item.due_date}" if getattr(item, "due_date", "") else "")
        + ".\n\n"
        "Please review this charge and confirm in writing what you find. If the "
        "charge is found to be in error, I ask that it be reversed and that any "
        "related fees be removed.\n\n"
        "I am happy to provide any further detail that would help your review.\n\n"
        f"Sincerely,\n{signoff}\n"
    )

    receipt = make_receipt(
        explanation=(f"Drafted a dispute letter to "
                     f"{letter.vendor or 'an unnamed vendor'} over ${letter.amount_usd:.2f} "
                     f"({letter.reason.replace('_', ' ')}). Draft only — not sent."),
        amount_saved=0.0,   # a draft has saved nothing yet; claiming otherwise would
                            # inflate the digest with money that has not moved
        action=f"dispute:{letter.reason}",
    )
    from negotiate import sign_receipt  # noqa: PLC0415 - avoids a circular import

    receipt.signature = sign_receipt(receipt)
    letter.receipt = receipt
    letter.drafted = True
    return letter
