"""negotiate — decide whether to negotiate a bill, and compose the terms.

SCOPE LIMIT — THIS MODULE DOES NOT SEND ANYTHING.
------------------------------------------------
This is the DECISION layer. It reads an `InboundItem`, weighs it against an
`AuthorityBudget`, and composes proposed terms plus draft message text. It
stops there. There is no email client, no HTTP call, no dialer, no third-party
API, and no import of any module that could provide one.

That is a deliberate architectural boundary, not an oversight. Composing a
message and transmitting it are separate concerns; wiring a real send path
touches the owner-only legal gate (custody / transmission) named in this
project's pipeline contract, and belongs to the operator rather than to a
coding agent. The seam is `NegotiationProposal.draft_message` — an operator
hands that string to whatever send path they have reviewed and approved.

`tests/test_negotiate.py` asserts the absence of network primitives in this
module's namespace, so a future edit that quietly adds one fails the suite.
"""
from __future__ import annotations

import os
import statistics
import sys
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
_STACK_DIR = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_STACK_DIR, "contracts"), _STACK_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from authority import Decision, authorize  # noqa: E402
from autonomy import NegotiationOutcome  # noqa: E402
from intake import BILL, NOTICE, STATEMENT, classify  # noqa: E402

__all__ = [
    "NegotiationProposal",
    "PeriodObservation",
    "propose",
    "detect_subscription_creep",
    "settle",
    "MIN_TARGET_REDUCTION_USD",
    "CREEP_MIN_PERIODS",
]

#: Below this, a negotiation costs more attention than it returns.
MIN_TARGET_REDUCTION_USD = 5.0

#: Consecutive rising periods before a rise is called subscription creep.
CREEP_MIN_PERIODS = 3

#: Fraction of the overage we aim to claw back on an above-baseline bill.
_TARGET_FRACTION = 0.5


@dataclass
class PeriodObservation:
    """One historical amount billed by an issuer, for baseline comparison."""

    issuer: str = ""
    amount_usd: float = 0.0
    period: str = ""


@dataclass
class NegotiationProposal:
    """A proposed negotiation. Composed, never sent.

    `requires_approval` mirrors the `authority.Decision` this proposal was
    checked against. A proposal the budget does not permit still comes back
    fully composed — the holder may want to send it themselves — but it is
    never marked `accepted`.
    """

    issuer: str = ""
    should_negotiate: bool = False
    target_reduction_usd: float = 0.0
    current_amount_usd: Optional[float] = None
    baseline_usd: Optional[float] = None
    justification: str = ""
    draft_message: str = ""
    requires_approval: bool = True
    accepted: bool = False
    creep_detected: bool = False
    decision: Optional[Decision] = None
    notes: List[str] = field(default_factory=list)


def _amounts(history: Any) -> List[float]:
    """Usable amounts from a history sequence, in order. Never raises."""
    out: List[float] = []
    try:
        for row in list(history or []):
            raw = getattr(row, "amount_usd", None)
            if raw is None and isinstance(row, dict):
                raw = row.get("amount_usd")
            if raw is None and isinstance(row, (int, float)) and not isinstance(row, bool):
                raw = row
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            value = float(raw)
            if value != value or value in (float("inf"), float("-inf")):  # NaN/inf
                continue
            out.append(value)
    except TypeError:
        return []
    return out


def detect_subscription_creep(history: Sequence[Any], min_periods: int = CREEP_MIN_PERIODS) -> bool:
    """True when the same issuer's amount rises across consecutive periods.

    Strictly rising, and only over at least `min_periods` observations. A flat
    series is not creep, and neither is a single jump inside an otherwise flat
    series — one-off charges are normal and flagging them trains the holder to
    ignore the flag.
    """
    amounts = _amounts(history)
    if len(amounts) < max(2, int(min_periods or CREEP_MIN_PERIODS)):
        return False
    return all(later > earlier for earlier, later in zip(amounts, amounts[1:]))


def _baseline(history: Sequence[Any]) -> Optional[float]:
    """Representative prior amount. Median resists a single outlier month."""
    amounts = _amounts(history)
    if not amounts:
        return None
    return float(statistics.median(amounts))


def _compose_message(issuer: str, current: float, baseline: Optional[float],
                     target: float, creep: bool) -> str:
    """Compose the draft. Template language only; no legal assertion.

    Returned as a string for a human to review and send. Nothing in this
    module transmits it.
    """
    lines = [
        f"To: {issuer or 'the billing department'}",
        "Subject: Request to review a recent increase",
        "",
        f"I am writing about my current charge of ${current:,.2f}.",
    ]
    if baseline is not None:
        lines.append(
            f"My typical prior amount has been about ${baseline:,.2f}."
        )
    if creep:
        lines.append(
            "The amount has increased in each of the last several billing periods."
        )
    lines += [
        f"I would like to request a reduction of approximately ${target:,.2f}, "
        "or to be moved to a plan that matches my usage.",
        "",
        "Please let me know what options are available.",
        "",
        "-- DRAFT: composed automatically, not sent. Review before use. --",
    ]
    return "\n".join(lines)


def propose(item, budget, history: Optional[Sequence[Any]] = None, store=None) -> NegotiationProposal:
    """Decide whether to negotiate `item`, and compose the terms. Never raises.

    Every proposal is checked through `authority.authorize` before it may be
    called accepted. Nothing is transmitted.
    """
    proposal = NegotiationProposal()
    try:
        issuer = getattr(item, "issuer", None) or ""
        proposal.issuer = issuer

        current = getattr(item, "amount_usd", None)
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            proposal.justification = ""
            proposal.notes.append("no usable amount on the item; nothing to negotiate")
            return proposal
        current = float(current)
        if current != current or current <= 0:
            proposal.notes.append("amount is not a positive number; nothing to negotiate")
            return proposal
        proposal.current_amount_usd = current

        kind = classify(item)
        if kind not in (BILL, NOTICE, STATEMENT):
            proposal.notes.append(
                f"item classified {kind!r}; only bills, notices and statements are negotiated"
            )
            return proposal

        proposal.creep_detected = detect_subscription_creep(history or [])
        baseline = _baseline(history or [])
        proposal.baseline_usd = baseline

        if baseline is None:
            proposal.notes.append("no billing history; no baseline to negotiate against")
            return proposal

        overage = current - baseline
        if overage <= 0 and not proposal.creep_detected:
            proposal.notes.append(
                f"${current:,.2f} is at or below the ${baseline:,.2f} baseline"
            )
            return proposal

        target = round(max(overage, 0.0) * _TARGET_FRACTION, 2)
        if target < MIN_TARGET_REDUCTION_USD:
            proposal.notes.append(
                f"target reduction ${target:,.2f} is below the "
                f"${MIN_TARGET_REDUCTION_USD:,.2f} floor; not worth the holder's attention"
            )
            return proposal

        reasons = [
            f"Current charge ${current:,.2f} is ${overage:,.2f} above the "
            f"${baseline:,.2f} historical baseline for {issuer or 'this issuer'}."
        ]
        if proposal.creep_detected:
            reasons.append(
                "The amount has risen in every one of the last "
                f"{len(_amounts(history))} billing periods, which is the "
                "subscription-creep pattern."
            )
        proposal.justification = " ".join(reasons)

        proposal.should_negotiate = True
        proposal.target_reduction_usd = target
        proposal.draft_message = _compose_message(
            issuer, current, baseline, target, proposal.creep_detected
        )

        # The budget governs acting on the proposal, so it is checked against
        # the amount at stake.
        decision = authorize(budget, current, f"negotiate {issuer or 'bill'}", store=store)
        proposal.decision = decision
        proposal.requires_approval = bool(decision.requires_approval)
        proposal.accepted = False       # never auto-accepted at proposal time
        if decision.requires_approval:
            proposal.notes.append(f"budget requires approval: {decision.reason}")
        return proposal

    except Exception as exc:                                     # fail-soft
        proposal.should_negotiate = False
        proposal.accepted = False
        proposal.requires_approval = True
        proposal.notes.append(f"proposal failed ({exc.__class__.__name__}); requires approval")
        return proposal


def settle(proposal: NegotiationProposal, accepted: bool, counterparty_id: str = "",
           final_amount_usd: Optional[float] = None) -> NegotiationOutcome:
    """Record a settled result using the contract `NegotiationOutcome`.

    Called by an operator AFTER a real, human-reviewed exchange. This module
    does not conduct that exchange. A proposal still awaiting approval cannot
    be recorded as accepted.
    """
    outcome = NegotiationOutcome(
        deal_id=f"neg-{getattr(proposal, 'issuer', '') or 'unknown'}",
        accepted=False,
        counterparty_id=counterparty_id or getattr(proposal, "issuer", "") or "",
        terms="",
        amount=0.0,
    )
    try:
        if getattr(proposal, "requires_approval", True) and accepted:
            outcome.terms = (
                "cannot record acceptance: this proposal still requires holder approval"
            )
            return outcome
        outcome.accepted = bool(accepted)
        amount = final_amount_usd
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            amount = getattr(proposal, "target_reduction_usd", 0.0)
        outcome.amount = round(float(amount or 0.0), 2)
        outcome.terms = (
            f"reduction of ${outcome.amount:,.2f}" if outcome.accepted else "declined"
        )
    except Exception:                                            # fail-soft
        outcome.accepted = False
        outcome.terms = "outcome could not be recorded"
    return outcome
