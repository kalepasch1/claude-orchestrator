"""Estate continuity: keep documents and beneficiary designations current.

An estate goes stale quietly. A will names a beneficiary who is no longer in
the household, a document passes its review date, and nothing surfaces it
until it matters. This module makes both conditions queryable.

FAILS CLOSED on authority: only a member with a `guardian_of` edge to the
estate's owner may record a change. Reads are open; writes are gated.
Malformed documents are skipped with a warning, never raised.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from passport import has_authority_over

log = logging.getLogger(__name__)

#: A document older than this many days is stale.
DEFAULT_REVIEW_DAYS = 365

_SECONDS_PER_DAY = 86400.0


@dataclass
class EstateDocument:
    """One estate document and who it names."""
    doc_id: str = ""
    owner_id: str = ""
    kind: str = "will"  # will, trust, poa, directive, beneficiary_designation
    beneficiaries: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)
    review_days: int = DEFAULT_REVIEW_DAYS

    def is_stale(self, now: float | None = None) -> bool:
        """True if the document is past its review window."""
        try:
            now = time.time() if now is None else float(now)
            window = float(self.review_days or DEFAULT_REVIEW_DAYS) * _SECONDS_PER_DAY
            return (now - float(self.updated_at or 0.0)) > window
        except (TypeError, ValueError):
            log.warning("estate: %s has an unreadable date; treating as stale", self.doc_id)
            return True


def _valid_doc(doc: Any) -> bool:
    """True for a document with a usable doc_id and beneficiary list."""
    if doc is None:
        return False
    doc_id = getattr(doc, "doc_id", None)
    if not isinstance(doc_id, str) or not doc_id.strip():
        return False
    return isinstance(getattr(doc, "beneficiaries", None), (list, tuple))


def stale_documents(
    documents: Iterable[Any], now: float | None = None
) -> list[Any]:
    """Documents past their review window. Malformed entries are skipped."""
    out: list[Any] = []
    try:
        candidates = list(documents or [])
    except TypeError:
        log.warning("estate: documents not iterable; treating as empty")
        return []

    for doc in candidates:
        if not _valid_doc(doc):
            log.warning("estate: skipping malformed document %r", doc)
            continue
        try:
            if doc.is_stale(now):
                out.append(doc)
        except Exception as exc:
            log.warning("estate: staleness check failed for %r (%s); treating as stale", doc, exc)
            out.append(doc)
    return out


def orphaned_beneficiaries(
    documents: Iterable[Any], known_member_ids: Iterable[str]
) -> dict[str, list[str]]:
    """``doc_id -> beneficiaries who are no longer household members``.

    This is the drift that makes an estate wrong: the document is current, but
    the person it names has left the mesh.
    """
    try:
        known = {m.strip() for m in (known_member_ids or []) if isinstance(m, str) and m.strip()}
    except TypeError:
        log.warning("estate: member ids not iterable; treating as empty")
        known = set()

    out: dict[str, list[str]] = {}
    for doc in list(documents or []):
        if not _valid_doc(doc):
            log.warning("estate: skipping malformed document %r", doc)
            continue
        missing = sorted(
            b.strip() for b in doc.beneficiaries
            if isinstance(b, str) and b.strip() and b.strip() not in known
        )
        if missing:
            out[doc.doc_id.strip()] = missing
    return out


def sync_beneficiaries(
    passports: Iterable[Any],
    doc: Any,
    actor_id: str,
    beneficiaries: Iterable[str],
    now: float | None = None,
) -> tuple[Any, str]:
    """Rewrite ``doc``'s beneficiaries. Returns ``(doc, reason)``.

    FAILS CLOSED: the document is returned UNCHANGED unless ``actor_id`` is the
    owner or holds a `guardian_of` edge to the owner.
    """
    try:
        if not _valid_doc(doc):
            return doc, "denied: malformed document"
        if not isinstance(actor_id, str) or not actor_id.strip():
            return doc, "denied: no actor identified"

        actor = actor_id.strip()
        owner = (getattr(doc, "owner_id", "") or "").strip()
        if not owner:
            return doc, "denied: document has no owner"

        if actor != owner and not has_authority_over(passports, actor, owner):
            log.warning("estate: %s may not edit %s's estate; denying", actor, owner)
            return doc, f"denied: {actor} has no authority over {owner}"

        cleaned = []
        for b in list(beneficiaries or []):
            if isinstance(b, str) and b.strip() and b.strip() not in cleaned:
                cleaned.append(b.strip())

        doc.beneficiaries = cleaned
        doc.updated_at = time.time() if now is None else float(now)
        return doc, f"granted: {actor} synced {len(cleaned)} beneficiaries on {doc.doc_id}"
    except Exception as exc:
        log.warning("estate: sync failed (%s); denying", exc)
        return doc, f"denied: sync errored ({exc})"


def continuity_report(
    documents: Iterable[Any],
    known_member_ids: Iterable[str],
    now: float | None = None,
) -> dict[str, Any]:
    """Everything an operator needs to know about estate drift."""
    docs = list(documents or [])
    stale = stale_documents(docs, now)
    orphaned = orphaned_beneficiaries(docs, known_member_ids)
    return {
        "documents": len(docs),
        "stale": sorted(d.doc_id for d in stale),
        "orphaned_beneficiaries": orphaned,
        "current": not stale and not orphaned,
    }
