"""Parse and classify inbound bills, mail and email.

FAILS SOFT, deliberately and in the opposite direction to `authority`. A malformed
document yields an InboundItem with `parsed=False` and whatever fields could be read,
never an exception: the firewall's job is to keep triaging the other ninety-nine items
in the inbox when the hundredth is a scanned PDF with no amount in it. Nothing here
grants authority to act — `authority.authorize` does that, and it fails closed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

#: What an inbound item is asking of the household.
KIND_BILL = "bill"
KIND_RATE_CHANGE = "rate_change"
KIND_FEE = "fee"
KIND_SUBSCRIPTION = "subscription"
KIND_DISPUTE = "dispute"
KIND_UNKNOWN = "unknown"

#: Ordered most-specific first: a "subscription renewal price increase" is a rate
#: change worth negotiating, not merely a subscription notice, and whichever pattern
#: is tested first decides. Ordering the table IS the classification policy.
_CLASSIFIERS = (
    (KIND_RATE_CHANGE, re.compile(
        r"\b(rate\s+(increase|change|adjust)|price\s+(increase|change)|"
        r"new\s+rate|going\s+up|increase\s+effective)\b", re.I)),
    (KIND_FEE, re.compile(
        r"\b(late\s+fee|overdraft|service\s+charge|maintenance\s+fee|"
        r"convenience\s+fee|penalty)\b", re.I)),
    (KIND_DISPUTE, re.compile(
        r"\b(dispute|unauthori[sz]ed|incorrect\s+charge|billing\s+error|chargeback)\b",
        re.I)),
    (KIND_SUBSCRIPTION, re.compile(
        r"\b(subscription|auto[-\s]?renew|renewal|membership|recurring)\b", re.I)),
    (KIND_BILL, re.compile(
        r"\b(invoice|bill|amount\s+due|statement|payment\s+due|balance\s+due)\b", re.I)),
)

#: Amounts like $1,234.56 / USD 89 / 45.00 dollars. Currency-symbol forms are matched
#: first so "$1,234.56" is not truncated to "1" by the bare-number pattern.
_AMOUNT_PATTERNS = (
    re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"),
    re.compile(r"\b(?:USD|usd)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"),
    re.compile(r"\b([0-9][0-9,]*\.[0-9]{2})\s*(?:dollars|USD)\b", re.I),
)

_DUE_PATTERNS = (
    re.compile(r"\bdue\s+(?:on\s+|by\s+)?([A-Z][a-z]+\s+\d{1,2},?\s*\d{0,4})"),
    re.compile(r"\bdue\s+(?:on\s+|by\s+)?(\d{4}-\d{2}-\d{2})"),
    re.compile(r"\bdue\s+(?:on\s+|by\s+)?(\d{1,2}/\d{1,2}/\d{2,4})"),
)

_VENDOR_PATTERNS = (
    re.compile(r"^\s*from:\s*(.+?)\s*$", re.I | re.M),
    re.compile(r"\b(?:from|by|billed\s+by)\s+([A-Z][\w&.\- ]{2,40}?)(?:\.|,|\n|$)"),
)


@dataclass
class InboundItem:
    """One parsed inbound document.

    `parsed` False means the text could not be read as a document at all (empty,
    non-text, or an unexpected parser fault). It does NOT mean "no amount found" —
    a rate-change notice legitimately has no amount, and conflating the two would
    make every such notice look like a parse failure.
    """
    raw: str = ""
    kind: str = KIND_UNKNOWN
    amount_usd: Optional[float] = None
    vendor: str = ""
    due_date: str = ""
    parsed: bool = True
    notes: List[str] = field(default_factory=list)

    @property
    def negotiable(self) -> bool:
        """Whether `negotiate` has a play for this kind of item."""
        return self.kind in (KIND_BILL, KIND_RATE_CHANGE, KIND_FEE, KIND_SUBSCRIPTION)


def _to_text(document: Any) -> Optional[str]:
    """Best-effort text from whatever the caller handed us."""
    if document is None:
        return None
    if isinstance(document, str):
        return document
    if isinstance(document, bytes):
        try:
            return document.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - fail soft
            return None
    if isinstance(document, dict):
        parts = [str(document.get(k, "")) for k in ("subject", "body", "text", "content")]
        joined = "\n".join(p for p in parts if p)
        return joined or None
    try:
        return str(document)
    except Exception:  # noqa: BLE001 - fail soft
        return None


def extract_amount(text: str) -> Optional[float]:
    """The first plausible currency amount, or None."""
    for pattern in _AMOUNT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            return float(match.group(1).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def classify(text: str) -> str:
    """Which kind of inbound item this is. Never raises."""
    for kind, pattern in _CLASSIFIERS:
        if pattern.search(text):
            return kind
    return KIND_UNKNOWN


def parse(document: Any) -> InboundItem:
    """Parse one inbound document. Never raises.

    Any unexpected fault is recorded on the item and returned, because the caller is
    a loop over an inbox and one bad document must not stop the other ninety-nine.
    """
    text = _to_text(document)
    if not text or not text.strip():
        return InboundItem(raw="", parsed=False, notes=["empty or unreadable document"])
    try:
        item = InboundItem(raw=text, kind=classify(text), amount_usd=extract_amount(text))
        for pattern in _DUE_PATTERNS:
            match = pattern.search(text)
            if match:
                item.due_date = match.group(1).strip().rstrip(",")
                break
        for pattern in _VENDOR_PATTERNS:
            match = pattern.search(text)
            if match:
                item.vendor = match.group(1).strip()
                break
        if item.amount_usd is None and item.kind in (KIND_BILL, KIND_FEE):
            item.notes.append("no amount found in a document classified as a charge")
        return item
    except Exception as exc:  # noqa: BLE001 - fail soft, by contract
        return InboundItem(raw=text, parsed=False,
                           notes=[f"parser fault: {type(exc).__name__}: {exc}"])


def parse_batch(documents: Any) -> List[InboundItem]:
    """Parse an inbox. A fault in one document never costs the others."""
    if not documents:
        return []
    try:
        iterator = list(documents)
    except Exception:  # noqa: BLE001 - fail soft
        return []
    return [parse(doc) for doc in iterator]
