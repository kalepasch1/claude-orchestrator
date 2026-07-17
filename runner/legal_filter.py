#!/usr/bin/env python3
"""
legal_filter.py - one narrow predicate for owner/counsel gates.

Owner policy: do not stop implementation for generic "regulatory" smell. Gate only when
the work would likely change the company's regulatory posture: forcing licensing,
registration, custody, transmission, regulated advice, underwriting, or a similar activity
that the current business model deliberately avoids.
"""
import re

POSITIONING_SAFE = re.compile(
    r"\b(avoid|without|not require|does not require|no license|no registration|"
    r"informational|educational|simulation|dry.?run|routing only|comparison only|"
    r"disclaimer|non.?custodial|no custody|no funds held|no recommendations|"
    r"internal tool|admin only|draft|research)\b",
    re.I,
)

REGULATED_ACTIVITY = re.compile(
    r"\b(money transmission|money transmitter|msb|kyc|aml|securities offering|"
    r"broker.?dealer|investment adviser|investment advisor|registered adviser|"
    r"insurance producer|insurance broker|reinsurance|lending license|loan origination|"
    r"underwriting (loan|credit|insurance)|take deposits|deposit taking|custodial|custody of"
    r"|hold customer funds|transmit funds|derivative|swap|futures|cftc|sec\b|finra|"
    r"hipaa|medical diagnosis|legal advice|tax advice)\b",
    re.I,
)

POSTURE_CHANGE = re.compile(
    r"\b(force|forces|forcing|trigger|triggers|required|requires|requirement|must|need to|"
    r"obtain|register|registration|license|licensed|licensing|permit|authorization|"
    r"become a|act as|offer|sell|issue|originate|underwrite|custody|custodian|"
    r"hold|transmit|advise|recommend|guarantee)\b",
    re.I,
)

EXTREME_LEGAL = re.compile(
    r"\b(subpoena|lawsuit|litigation|cease and desist|enforcement action|consent order|"
    r"criminal|fraud|sanction|ofac)\b",
    re.I,
)


def text_for(card=None, text=""):
    """Extract text content from a card dict or return the provided text fallback."""
    if isinstance(card, dict):
        parts = [card.get(k) for k in ("title", "why", "detail", "prebrief", "risk", "value")]
        text = " ".join(str(p or "") for p in parts) + " " + str(text or "")
    return str(text or "")


def requires_owner_approval(card=None, text="", kind="", radar_tag=""):
    blob = text_for(card, text)
    if not blob.strip():
        return False
    if EXTREME_LEGAL.search(blob):
        return True
    has_activity = bool(REGULATED_ACTIVITY.search(blob))
    has_posture_change = bool(POSTURE_CHANGE.search(blob))
    if not (has_activity and has_posture_change):
        return False
    # Safe-positioning language means the task is preserving the legal strategy, not changing it.
    if POSITIONING_SAFE.search(blob):
        return False
    return True


def trigger_excerpt(card=None, text=""):
    blob = text_for(card, text)
    for rx in (EXTREME_LEGAL, REGULATED_ACTIVITY, POSTURE_CHANGE):
        m = rx.search(blob)
        if m:
            return m.group(0)
    return ""
