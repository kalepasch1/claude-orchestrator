"""disputes — draft a dispute letter from an inbound item. DRAFTING ONLY.

WHAT THIS MODULE WILL NOT DO
----------------------------
This is consumer-facing correspondence that can carry legal consequence, so
the boundaries are hard ones, not preferences:

  * It does NOT send, file, or queue anything. No network, no send path — the
    same rule as negotiate.py, and the test suite enforces it the same way.
  * It does NOT assert a legal position, cite a statute as applicable to the
    holder's situation, or promise a remedy. Template language only, with the
    facts from the item interpolated. Naming a statute is how a draft stops
    being a draft and starts being advice.
  * Every letter carries a visible header marking it a draft for human review,
    and `review_required` is True on every path including the happy one.

THE OWNER-ONLY LEGAL GATE
-------------------------
Anything that would constitute advice, or that needs a secret or credential,
stops at the owner-only legal gate named in this project's pipeline contract.
`OWNER_GATE_SEAM` below documents where an operator picks the draft up. That
seam is a string handed back to a caller — deliberately inert. Crossing it is
the operator's decision, not a coding agent's.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_STACK_DIR = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_STACK_DIR, "contracts"), _STACK_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from intake import InboundItem  # noqa: E402

__all__ = [
    "DisputeDraft",
    "draft",
    "render",
    "DRAFT_HEADER",
    "DRAFT_FOOTER",
    "GROUNDS",
    "OWNER_GATE_SEAM",
]

#: Stamped at the top of every rendered body. `render()` re-applies it, so a
#: caller cannot strip it by editing `body` and rendering again.
DRAFT_HEADER = (
    "*** DRAFT FOR HUMAN REVIEW — NOT SENT, NOT FILED, NOT REVIEWED BY COUNSEL ***"
)

DRAFT_FOOTER = (
    "*** END DRAFT — a person must read, edit and send this. "
    "It asserts no legal position and is not legal advice. ***"
)

#: Where an operator, not this module, takes over.
OWNER_GATE_SEAM = (
    "owner-only legal gate: transmission, filing, and any statement of legal "
    "position are out of scope for this module and require operator review."
)

#: grounds code -> the neutral, factual sentence used for it.
#: Descriptive of what the holder observed. No statute, no entitlement claim.
GROUNDS = {
    "not_mine": "I do not recognise this charge and do not believe this account is mine.",
    "amount_wrong": "The amount billed does not match what I expected for this period.",
    "already_paid": "I believe this amount was already paid.",
    "duplicate": "This appears to duplicate a charge I have already been billed for.",
    "service_not_received": "I was billed for a service or item I did not receive.",
    "cancelled": "I had cancelled this service before the period covered by this charge.",
    "rate_change_unnotified": "The rate changed without notice that I received.",
    "unauthorized": "I did not authorise this charge.",
}

_UNKNOWN_GROUNDS = (
    "I am disputing this charge. The specific reason is recorded separately "
    "and should be completed before this letter is used."
)


@dataclass
class DisputeDraft:
    """One drafted dispute letter. Always a draft.

    `review_required` is not a parameter and has no code path that clears it.
    """

    subject: str = ""
    body: str = ""
    enclosures: List[str] = field(default_factory=list)
    review_required: bool = True
    issuer: Optional[str] = None
    amount_usd: Optional[float] = None
    account_ref: Optional[str] = None
    grounds: str = ""
    grounds_recognised: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Belt and braces: even a caller who constructs this directly with
        # review_required=False gets it forced back on.
        self.review_required = True


def _fmt_amount(amount: Any) -> Optional[float]:
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return None
    value = float(amount)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _strip_existing_markers(text: str) -> str:
    """Drop any header/footer already present, so render() cannot double-stamp."""
    lines = [
        line for line in str(text or "").splitlines()
        if line.strip() not in (DRAFT_HEADER, DRAFT_FOOTER)
    ]
    return "\n".join(lines).strip("\n")


def render(draft_or_body: Any) -> str:
    """Render a draft's body with the review markers applied. Never raises.

    Idempotent and non-strippable: existing markers are removed and re-applied,
    so a round-trip through this function always yields exactly one header and
    one footer, whatever the caller did to `body` in between.
    """
    try:
        body = getattr(draft_or_body, "body", None)
        if body is None:
            body = draft_or_body
        core = _strip_existing_markers(body)
        return f"{DRAFT_HEADER}\n\n{core}\n\n{DRAFT_FOOTER}"
    except Exception:                                            # fail-soft
        return f"{DRAFT_HEADER}\n\n{DRAFT_FOOTER}"


def _compose_body(issuer, amount, account_ref, grounds_sentence, holder, received) -> str:
    lines = [
        f"To: {issuer or 'the billing department'}",
        "",
        "To whom it may concern,",
        "",
    ]
    identifiers = []
    if account_ref:
        identifiers.append(f"account reference {account_ref}")
    if amount is not None:
        identifiers.append(f"a charge of ${amount:,.2f}")
    if identifiers:
        lines.append(
            "I am writing about " + " and ".join(identifiers) + "."
        )
    else:
        lines.append("I am writing about a recent charge on my account.")

    if received:
        lines.append(f"The notice I received is dated {received}.")

    lines += [
        "",
        grounds_sentence,
        "",
        "Please review this charge and let me know what you find. I am happy to "
        "provide any further information that would help.",
        "",
        "Thank you for your time.",
        "",
        f"{holder or '[holder name]'}",
    ]
    return "\n".join(lines)


def draft(item, grounds, holder="") -> DisputeDraft:
    """Draft a dispute letter for `item` on the stated `grounds`. Never raises.

    An unrecognised grounds code does not raise and does not block the draft:
    it produces a letter with a placeholder reason, flagged in `notes`, that
    still requires review. The reviewer is the safeguard, so the useful
    behaviour is to hand them something to correct rather than nothing.
    """
    out = DisputeDraft()
    try:
        issuer = getattr(item, "issuer", None)
        amount = _fmt_amount(getattr(item, "amount_usd", None))
        account_ref = getattr(item, "account_ref", None)
        received = getattr(item, "due_date", None)

        out.issuer = issuer
        out.amount_usd = amount
        out.account_ref = account_ref

        key = grounds if isinstance(grounds, str) else ""
        key = key.strip().lower()
        out.grounds = key
        sentence = GROUNDS.get(key)
        if sentence is None:
            sentence = _UNKNOWN_GROUNDS
            out.grounds_recognised = False
            out.notes.append(
                f"unrecognised grounds code {grounds!r}; placeholder reason inserted "
                "— a reviewer must complete it before use"
            )
        else:
            out.grounds_recognised = True

        subject_bits = ["Dispute of a charge"]
        if account_ref:
            subject_bits.append(f"account {account_ref}")
        if amount is not None:
            subject_bits.append(f"${amount:,.2f}")
        out.subject = " — ".join(subject_bits)

        core = _compose_body(issuer, amount, account_ref, sentence, holder, received)
        out.body = render(core)

        out.enclosures = []
        if getattr(item, "raw_text", ""):
            out.enclosures.append("copy of the original notice as received")
        if account_ref:
            out.enclosures.append("proof of account ownership")

        out.notes.append(OWNER_GATE_SEAM)
        return out

    except Exception as exc:                                     # fail-soft
        out.subject = "Dispute of a charge"
        out.body = render("I am writing to dispute a recent charge on my account.")
        out.notes.append(
            f"draft degraded ({exc.__class__.__name__}); requires review"
        )
        out.notes.append(OWNER_GATE_SEAM)
        return out
