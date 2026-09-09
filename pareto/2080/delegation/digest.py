"""digest — fold a period of receipts, proposals and drafts into ONE card.

The receipts contract exists so a person can audit an autonomous agent. A
digest that needs decoding defeats that, so the language here is deliberately
plain: "saved", "did", "waiting for you", "to read". No jargon, no tier names,
no field names leaking into the rendered card.

SHAPE REUSE
-----------
The period roll-up IS the contract `AuditBundle` from
`pareto/2080/contracts/autonomy.py`, held at `Digest.bundle`. It is not copied
into a parallel dataclass. `pareto/2080/audit/bundler.py` made the same call
and documented why: a local class also called `AuditBundle` is how a package
ends up looking like it speaks the shared contract while never touching it.
`tests/test_digest.py` asserts the type so a later refactor cannot silently
fork the shape.

Receipts are sourced ONLY through the `ReceiptStore` Protocol — this module
never reads a store's internals or touches a file.
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

from autonomy import AuditBundle, Receipt  # noqa: E402

__all__ = ["Digest", "build_digest", "render_card", "as_amount"]


def as_amount(value: Any) -> float:
    """Money as a float, rounded to cents. Anything unusable is 0.0.

    Same contract as `audit/bundler.as_amount`; duplicated rather than imported
    to avoid making the delegation package depend on the audit package for one
    four-line helper.
    """
    try:
        if isinstance(value, bool):
            return 0.0
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if amount != amount or amount in (float("inf"), float("-inf")):
        return 0.0
    return round(amount, 2)


@dataclass
class Digest:
    """One card. Four numbers and a few lines a person can read in a minute."""

    holder_id: str = ""
    period_start: str = ""
    period_end: str = ""

    total_saved_usd: float = 0.0
    actions_taken: int = 0
    awaiting_approval: int = 0
    drafts_pending_review: int = 0

    #: the contract roll-up — NOT a parallel shape
    bundle: Optional[AuditBundle] = None

    lines: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.bundle is None:
            self.bundle = AuditBundle(
                bundle_id=f"delegation-digest-{self.holder_id or 'unknown'}",
                receipts=[],
                period_start=self.period_start or "",
                period_end=self.period_end or "",
                notes="",
            )

    @property
    def is_empty(self) -> bool:
        return not (
            self.actions_taken or self.awaiting_approval or self.drafts_pending_review
        )

    def render(self) -> str:
        return render_card(self)


def _in_period(receipt: Any, start: Optional[float], end: Optional[float]) -> bool:
    """Keep a receipt whose timestamp falls in the window.

    An unparseable or absent timestamp is KEPT, not dropped: under-reporting an
    autonomous agent's spending is the worse failure, and a person reading the
    card would rather see one extra line than silently miss one.
    """
    ts = getattr(receipt, "timestamp", None)
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return True
    if ts != ts:
        return True
    if start is not None and ts < start:
        return False
    if end is not None and ts > end:
        return False
    return True


def _to_epoch(value: Any) -> Optional[float]:
    """Accept an epoch float or an ISO `YYYY-MM-DD`. None when unusable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if value != value else float(value)
    if isinstance(value, str) and value.strip():
        import datetime
        try:
            return datetime.datetime.strptime(value.strip()[:10], "%Y-%m-%d").timestamp()
        except (ValueError, OverflowError, OSError):
            return None
    return None


def _label(value: Any) -> str:
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _fetch(store: Any, holder_id: str) -> List[Any]:
    """Receipts via the ReceiptStore Protocol only. Never raises."""
    if store is None:
        return []
    lister = getattr(store, "list_all", None)
    if not callable(lister):
        return []
    try:
        return [r for r in list(lister(holder_id) or []) if r is not None]
    except Exception:                                            # fail-soft
        return []


def _count(collection: Any, label: str, digest: "Digest") -> int:
    """Count a pending collection. Anything uncountable reports 0 and says so.

    A str or bytes is rejected rather than counted: `list("abc")` is 3, so a
    caller who passed a single id as a bare string would silently see three
    items waiting. On an audit card that is a wrong number presented as fact.
    """
    if collection is None:
        return 0
    if isinstance(collection, (str, bytes)):
        digest.notes.append(
            f"{label} arrived as text, not a collection; reported as 0"
        )
        return 0
    try:
        return len(list(collection))
    except TypeError:
        digest.notes.append(f"{label} were not countable; reported as 0")
        return 0


def build_digest(period_start, period_end, store, holder_id,
                 pending_approvals=None, pending_drafts=None) -> Digest:
    """Fold one period into a single card. Never raises.

    `pending_approvals` are decisions the agent could NOT take (sub-tasks 2/3)
    and `pending_drafts` are letters awaiting review (sub-task 4). Both are
    counted separately from `actions_taken` — a thing the agent decided not to
    do on its own authority is not an accomplishment, and folding the two
    together is precisely the flattery that makes an audit card useless.
    """
    digest = Digest(
        holder_id=_label(holder_id),
        period_start=_label(period_start),
        period_end=_label(period_end),
    )
    try:
        start = _to_epoch(period_start)
        end = _to_epoch(period_end)
        if end is not None and isinstance(period_end, str):
            end += 86_399          # an ISO end date means end-of-day

        receipts = [r for r in _fetch(store, digest.holder_id) if _in_period(r, start, end)]
        digest.bundle.receipts = receipts
        digest.actions_taken = len(receipts)
        digest.total_saved_usd = round(sum(as_amount(getattr(r, "amount_saved", 0.0))
                                           for r in receipts), 2)

        digest.awaiting_approval = _count(pending_approvals, "pending approvals", digest)
        digest.drafts_pending_review = _count(pending_drafts, "pending drafts", digest)

        digest.bundle.notes = (
            f"{digest.actions_taken} action(s) taken; "
            f"{digest.awaiting_approval} awaiting your approval; "
            f"{digest.drafts_pending_review} draft(s) to read."
        )
        digest.lines = _lines(digest, receipts)
        return digest

    except Exception as exc:                                     # fail-soft
        digest.notes.append(f"digest degraded ({exc.__class__.__name__})")
        digest.lines = _lines(digest, [])
        return digest


def _lines(digest: Digest, receipts: List[Any]) -> List[str]:
    """Plain-language body. One line per action, capped so the card stays a card."""
    out: List[str] = []
    if digest.total_saved_usd:
        out.append(f"I saved you ${digest.total_saved_usd:,.2f} this period.")
    else:
        out.append("I did not save you any money this period.")

    if digest.actions_taken:
        out.append(f"I did {digest.actions_taken} thing(s) on my own:")
        for receipt in receipts[:5]:
            text = _label(getattr(receipt, "explanation", "")).strip()
            out.append(f"  - {text or _label(getattr(receipt, 'action', '')) or 'an action'}")
        if len(receipts) > 5:
            out.append(f"  - ...and {len(receipts) - 5} more.")
    else:
        out.append("I did not do anything on my own this period.")

    if digest.awaiting_approval:
        out.append(
            f"{digest.awaiting_approval} thing(s) need your OK before I can act."
        )
    if digest.drafts_pending_review:
        out.append(
            f"{digest.drafts_pending_review} letter(s) are drafted and waiting for you to read."
        )
    if digest.is_empty:
        out.append("Nothing needed your attention this period.")
    return out


def render_card(digest: Digest) -> str:
    """The card as text. Never raises."""
    try:
        period = " to ".join(p for p in (digest.period_start, digest.period_end) if p)
        head = f"Your delegation summary{f' — {period}' if period else ''}"
        return "\n".join([head, "=" * len(head), *digest.lines])
    except Exception:                                            # fail-soft
        return "Your delegation summary\n=======================\nNothing to report."
