"""intake — parse and classify inbound bills / mail / email into one record.

The delegation firewall acts on what this module says an item IS. A
solicitation misread as a bill is an autonomous payment of money that was
never owed, so the rules here are deliberately conservative: evidence of
being asked to *opt in* to something beats evidence of an amount being due,
and anything the rules cannot place comes back `unknown` rather than
guessing.

Deterministic and rule-based by contract. No network, no LLM, no secrets.
Nothing in here is allowed to raise: `parse_inbound` and `classify` return a
safe default on malformed input.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

#: the closed set `classify` may return
BILL = "bill"
STATEMENT = "statement"
NOTICE = "notice"
SOLICITATION = "solicitation"
DISPUTE_RESPONSE = "dispute_response"
UNKNOWN = "unknown"

CLASSES = (BILL, STATEMENT, NOTICE, SOLICITATION, DISPUTE_RESPONSE, UNKNOWN)


@dataclass
class InboundItem:
    """One normalized piece of inbound mail, post-parse.

    `raw_text` is retained verbatim: downstream dispute drafting quotes the
    source, and a lossy parse must never become the only surviving record.
    """

    source: str = ""
    raw_text: str = ""
    received_at: float = field(default_factory=time.time)

    # parsed fields — all optional, all None when the parse could not find them
    issuer: Optional[str] = None
    amount_usd: Optional[float] = None
    due_date: Optional[str] = None
    account_ref: Optional[str] = None


# ── parsing ─────────────────────────────────────────────────────────────────

_ISSUER_RE = re.compile(
    r"^\s*(?:from|issuer|biller|bill\s+from|statement\s+from)\s*[:\-]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# "$1,234.56" / "USD 1234.56" / "Amount due: 89.00"
_AMOUNT_RE = re.compile(
    r"(?:(?:amount|total|balance)[^\n:]*[:\s]\s*)?"
    r"(?:\$|USD\s*)\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

_AMOUNT_LABELLED_RE = re.compile(
    r"(?:amount\s+due|total\s+due|balance\s+due|amount|total\s+amount)"
    r"[^\n\d$]*(?:\$|USD\s*)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

_DUE_DATE_RE = re.compile(
    r"(?:due\s+(?:date|by|on)|payment\s+due)\s*[:\-]?\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)

_ACCOUNT_RE = re.compile(
    r"(?:account|acct|policy|member|reference|ref)\s*(?:number|no\.?|#|id)?\s*"
    r"[:\-#]\s*([A-Za-z0-9][A-Za-z0-9\-]{2,})",
    re.IGNORECASE,
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _norm_date(raw: str) -> Optional[str]:
    """Normalize a matched date to ISO `YYYY-MM-DD`, or None if implausible."""
    raw = raw.strip().rstrip(".,")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw

    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:                      # 2-digit year -> 20xx
            year += 2000
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
        return None

    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m:
        month = _MONTHS.get(m.group(1).lower())
        day, year = int(m.group(2)), int(m.group(3))
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _to_float(raw: str) -> Optional[float]:
    try:
        return float(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def parse_inbound(raw_text, source: str = "", received_at: Optional[float] = None) -> InboundItem:
    """Parse `raw_text` into an `InboundItem`. Never raises.

    Unparseable input yields an item whose parsed fields are all None — which
    `classify` then reports as `unknown`, so bad input fails closed rather
    than arriving downstream wearing a confident label.
    """
    item = InboundItem(source=source or "", raw_text="")
    if received_at is not None:
        item.received_at = received_at

    if not isinstance(raw_text, str) or not raw_text.strip():
        return item
    item.raw_text = raw_text

    try:
        m = _ISSUER_RE.search(raw_text)
        if m:
            item.issuer = m.group(1).strip() or None

        # A labelled amount ("Amount due: $120.50") beats a bare one, which may
        # be a marketing figure like "save $500!".
        m = _AMOUNT_LABELLED_RE.search(raw_text) or _AMOUNT_RE.search(raw_text)
        if m:
            item.amount_usd = _to_float(m.group(1))

        m = _DUE_DATE_RE.search(raw_text)
        if m:
            item.due_date = _norm_date(m.group(1))

        m = _ACCOUNT_RE.search(raw_text)
        if m:
            item.account_ref = m.group(1).strip() or None
    except Exception:
        # Defensive: a regex pathology must not take intake down. Whatever was
        # parsed before the failure stands; the rest stays None.
        pass

    return item


# ── classification ──────────────────────────────────────────────────────────

# Ordered most- to least-specific. First rule whose markers hit, wins.
_SOLICITATION_MARKERS = (
    "pre-approved", "preapproved", "you may qualify", "you could qualify",
    "apply now", "limited time offer", "special offer", "act now",
    "no obligation", "unsubscribe", "sign up today", "enroll today",
    "this is an advertisement", "promotional", "opt in", "opt-in",
    "consolidate your debt", "lower your rate today", "claim your",
)

_DISPUTE_MARKERS = (
    "in response to your dispute", "your dispute", "dispute resolution",
    "results of our investigation", "we have completed our investigation",
    "reinvestigation", "your billing inquiry", "billing error notice",
    "fair credit billing act", "we have reviewed your claim",
)

_NOTICE_MARKERS = (
    "final notice", "past due", "delinquent", "notice of", "shut-off",
    "shutoff", "disconnection", "collection", "legal action",
    "this is an attempt to collect", "cure or quit", "late fee assessed",
)

_STATEMENT_MARKERS = (
    "statement of account", "monthly statement", "account statement",
    "statement period", "closing date", "previous balance",
    "this is not a bill", "for your records", "year-end summary",
)

_BILL_MARKERS = (
    "amount due", "total due", "balance due", "payment due", "please pay",
    "invoice", "remit payment", "pay by", "minimum payment",
)


def _hits(haystack: str, markers) -> bool:
    return any(marker in haystack for marker in markers)


def classify(item) -> str:
    """Classify an `InboundItem` into one of `CLASSES`. Never raises.

    Order matters. A solicitation is checked first because solicitations
    imitate bills — that is the point of them — and the cost of paying one is
    strictly worse than the cost of a human glancing at a real bill we
    under-classified.
    """
    try:
        text = getattr(item, "raw_text", None)
        if not isinstance(text, str) or not text.strip():
            return UNKNOWN
        low = text.lower()

        # "This is not a bill" is an explicit self-declaration; honour it
        # before anything else that looks bill-shaped.
        if "this is not a bill" in low:
            return STATEMENT

        if _hits(low, _SOLICITATION_MARKERS):
            return SOLICITATION
        if _hits(low, _DISPUTE_MARKERS):
            return DISPUTE_RESPONSE
        if _hits(low, _NOTICE_MARKERS):
            return NOTICE
        # Bill BEFORE statement: a real utility bill routinely carries both
        # "Statement period:" and "Amount due:". Language that asserts a
        # payment obligation is the stronger signal, and the one case where a
        # statement must win — an explicit "this is not a bill" — is already
        # handled above.
        if _hits(low, _BILL_MARKERS):
            return BILL
        if _hits(low, _STATEMENT_MARKERS):
            return STATEMENT

        # No textual marker. An amount AND a due date together are enough to
        # call it a bill; either alone is not.
        amount = getattr(item, "amount_usd", None)
        due = getattr(item, "due_date", None)
        if amount is not None and due:
            return BILL

        return UNKNOWN
    except Exception:
        return UNKNOWN
