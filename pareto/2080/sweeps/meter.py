"""The live "paid for itself ×N" meter.

N is computed PURELY from stored receipts: total verified savings divided by what the
household paid for the subscription over the same period. Nothing is estimated,
projected, or carried over from a previous computation — if a saving is not in a
signed receipt, it does not count toward N.

That strictness is the point. This number is the product's central claim about its own
worth, so the two ways it could lie are both closed here:

  * an UNSIGNED or TAMPERED receipt is excluded, not trusted (`require_signature`,
    on by default). A meter that counted forged receipts would be self-certifying.
  * a ZERO subscription cost does not yield ×infinity. It yields `undefined`, because
    "paid for itself" is meaningless when nothing was paid.

`ReceiptStore` from contracts is a Protocol, so any object exposing `list_all` works;
a plain list of receipts works too, which is what the sweeps hand over.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from engine import verify_receipt


@dataclass
class MeterReading:
    """What the receipts say the product was worth."""
    total_saved: float = 0.0
    subscription_cost: float = 0.0
    multiple: Optional[float] = None      # None == undefined, not zero
    receipts_counted: int = 0
    receipts_rejected: int = 0
    period: str = ""
    rejected_reasons: List[str] = field(default_factory=list)

    @property
    def paid_for_itself(self) -> bool:
        """True only when a real multiple was computed and it reached 1x."""
        return self.multiple is not None and self.multiple >= 1.0

    def render(self) -> str:
        """The one-line meter, in plain language."""
        if self.multiple is None:
            return (f"Saved ${self.total_saved:.2f} so far. "
                    f"(No subscription cost recorded, so there is no multiple to show.)")
        if self.paid_for_itself:
            return (f"Paid for itself ×{self.multiple:.1f} — "
                    f"${self.total_saved:.2f} saved against "
                    f"${self.subscription_cost:.2f} paid.")
        return (f"${self.total_saved:.2f} saved against "
                f"${self.subscription_cost:.2f} paid — "
                f"×{self.multiple:.2f} so far.")


def _receipts_from(source: Any, holder_id: str = "") -> List[Any]:
    """Receipts out of a ReceiptStore, a SweepRun, or a plain list. Never raises."""
    if source is None:
        return []
    if hasattr(source, "list_all"):
        try:
            return list(source.list_all(holder_id) or [])
        except Exception:  # noqa: BLE001 - fail soft
            return []
    if hasattr(source, "receipts"):
        try:
            return list(getattr(source, "receipts") or [])
        except Exception:  # noqa: BLE001 - fail soft
            return []
    try:
        return list(source)
    except Exception:  # noqa: BLE001 - fail soft
        return []


def _amount(receipt: Any) -> Optional[float]:
    value = getattr(receipt, "amount_saved", None)
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")) or out < 0:
        return None
    return out


def compute(receipts: Any, subscription_cost: float = 0.0, holder_id: str = "",
            period: str = "", require_signature: bool = True,
            key: Optional[bytes] = None) -> MeterReading:
    """Compute the meter from stored receipts. Never raises."""
    reading = MeterReading(period=period)
    try:
        cost = float(subscription_cost)
        if cost != cost or cost < 0:
            cost = 0.0
    except (TypeError, ValueError):
        cost = 0.0
    reading.subscription_cost = round(cost, 2)

    for receipt in _receipts_from(receipts, holder_id=holder_id):
        amount = _amount(receipt)
        if amount is None:
            reading.receipts_rejected += 1
            reading.rejected_reasons.append("unusable amount_saved")
            continue
        if require_signature:
            ok = (verify_receipt(receipt, key=key) if key is not None
                  else verify_receipt(receipt))
            if not ok:
                reading.receipts_rejected += 1
                reading.rejected_reasons.append("missing or invalid signature")
                continue
        reading.total_saved += amount
        reading.receipts_counted += 1

    reading.total_saved = round(reading.total_saved, 2)
    # Undefined, not infinite: "paid for itself" says nothing when nothing was paid.
    reading.multiple = (round(reading.total_saved / reading.subscription_cost, 4)
                        if reading.subscription_cost > 0 else None)
    return reading
