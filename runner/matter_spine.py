#!/usr/bin/env python3
"""Wave C, Part 6 — matter spine, exposure-to-hedge flywheel, renewal annuity.

The spec's three pieces, all keyed to a single matter record:

* **Matter spine.**  Intake, triage, licensing, filings, video and newsletters
  are keyed to ONE matter, and the inbox, the portal and the exposure model are
  three VIEWS of that one truth -- not three stores that drift.  Each view is a
  projection, so a fact cannot be true in the inbox and false in the portal.
* **Exposure-to-hedge flywheel.**  The metric is the share of quantified
  expected loss that is hedgeable on Tomorrow, trending over time.  Exposure
  that is NOT hedgeable is the valuable half: it is the product gap, and it
  feeds the instrument foundry.
* **Renewal annuity engine.**  Every filing schedules its own renewal and
  reporting calendar, so an obligation cannot exist without the reminder that
  it exists.

Deliberately advisory and side-effect-free: it computes projections and due
dates.  It files nothing, sends nothing and hedges nothing -- those belong to
the systems that already own them.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VIEWS = ("inbox", "portal", "exposure")

#: Cadences a filing can carry.  Days, because months drift.
CADENCE_DAYS = {
    "annual": 365,
    "biennial": 730,
    "quarterly": 91,
    "monthly": 30,
}


class UnknownView(ValueError):
    """A view was requested that the spine does not project."""


class MatterIntegrityError(ValueError):
    """A record was attached to a matter that does not exist."""


@dataclass(frozen=True)
class Filing:
    filing_id: str
    matter_id: str
    kind: str
    filed_on: date
    cadence: Optional[str] = None      # None = one-off, no renewal
    jurisdiction: str = ""

    def renewal_due(self) -> Optional[date]:
        """A one-off filing has no renewal; inventing one would be noise."""
        if not self.cadence:
            return None
        days = CADENCE_DAYS.get(self.cadence)
        if days is None:
            raise ValueError(f"unknown cadence {self.cadence!r}")
        return self.filed_on + timedelta(days=days)


@dataclass(frozen=True)
class Exposure:
    exposure_id: str
    matter_id: str
    expected_loss_usd: float
    hedgeable: bool
    instrument: str = ""

    def __post_init__(self) -> None:
        if self.expected_loss_usd < 0:
            raise ValueError("expected_loss_usd cannot be negative")


@dataclass
class Matter:
    matter_id: str
    title: str = ""
    stage: str = "intake"
    filings: List[Filing] = field(default_factory=list)
    exposures: List[Exposure] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)

    def digest(self) -> str:
        payload = {"id": self.matter_id, "title": self.title, "stage": self.stage,
                   "filings": sorted(f.filing_id for f in self.filings),
                   "exposures": sorted(e.exposure_id for e in self.exposures)}
        return hashlib.blake2b(json.dumps(payload, sort_keys=True).encode(),
                               digest_size=12).hexdigest()


class MatterSpine:
    """One record per matter; every surface is a projection of it."""

    def __init__(self) -> None:
        self._matters: Dict[str, Matter] = {}

    def open_matter(self, matter_id: str, title: str = "") -> Matter:
        if not matter_id:
            raise ValueError("a matter needs an id")
        matter = self._matters.get(matter_id)
        if matter is None:
            matter = Matter(matter_id=matter_id, title=title)
            self._matters[matter_id] = matter
        return matter

    def get(self, matter_id: str) -> Matter:
        matter = self._matters.get(matter_id)
        if matter is None:
            raise MatterIntegrityError(f"unknown matter {matter_id!r}")
        return matter

    def attach_filing(self, filing: Filing) -> Filing:
        self.get(filing.matter_id).filings.append(filing)
        return filing

    def attach_exposure(self, exposure: Exposure) -> Exposure:
        self.get(exposure.matter_id).exposures.append(exposure)
        return exposure

    def attach_artifact(self, matter_id: str, kind: str, ref: str) -> Dict[str, Any]:
        """Video, newsletter, licence, correspondence -- all keyed to the matter."""
        artifact = {"kind": kind, "ref": ref}
        self.get(matter_id).artifacts.append(artifact)
        return artifact

    # -- projections -----------------------------------------------------
    def view(self, name: str, matter_id: str) -> Dict[str, Any]:
        """Three views, one truth.

        Each projection is derived from the same Matter, so they cannot
        disagree; the shared ``digest`` in every view makes that checkable
        rather than merely claimed.
        """
        if name not in VIEWS:
            raise UnknownView(f"{name!r} is not one of {VIEWS}")
        matter = self.get(matter_id)
        base = {"matter_id": matter.matter_id, "digest": matter.digest()}
        if name == "inbox":
            return {**base, "title": matter.title, "stage": matter.stage,
                    "open_items": len(matter.filings) + len(matter.exposures)}
        if name == "portal":
            return {**base, "title": matter.title,
                    "filings": [f.filing_id for f in matter.filings],
                    "artifacts": list(matter.artifacts)}
        return {**base, "total_expected_loss_usd": total_expected_loss(matter.exposures),
                "exposures": [e.exposure_id for e in matter.exposures]}

    def all_views(self, matter_id: str) -> Dict[str, Dict[str, Any]]:
        return {name: self.view(name, matter_id) for name in VIEWS}

    def views_agree(self, matter_id: str) -> bool:
        digests = {v["digest"] for v in self.all_views(matter_id).values()}
        return len(digests) == 1

    def matters(self) -> List[Matter]:
        return [self._matters[k] for k in sorted(self._matters)]


# -- exposure-to-hedge flywheel -----------------------------------------
def total_expected_loss(exposures: Iterable[Exposure]) -> float:
    return round(sum(e.expected_loss_usd for e in exposures), 2)


def hedgeable_share(exposures: Sequence[Exposure]) -> Dict[str, Any]:
    """Share of QUANTIFIED expected loss that is hedgeable on Tomorrow.

    With no quantified exposure the share is None, not 0.0 and not 1.0 —
    either number would be read as a finding when nothing was measured.
    """
    total = total_expected_loss(exposures)
    if total <= 0:
        return {"total_expected_loss_usd": total, "hedgeable_usd": 0.0,
                "share": None, "status": "no quantified exposure"}
    hedgeable = round(sum(e.expected_loss_usd for e in exposures if e.hedgeable), 2)
    return {"total_expected_loss_usd": total, "hedgeable_usd": hedgeable,
            "unhedgeable_usd": round(total - hedgeable, 2),
            "share": hedgeable / total, "status": "measured"}


def flywheel_trend(snapshots: Sequence[Tuple[str, Sequence[Exposure]]]) -> Dict[str, Any]:
    """The metric is the TREND, so a single point is explicitly not a trend."""
    points = []
    for label, exposures in snapshots:
        share = hedgeable_share(exposures)
        points.append({"label": label, "share": share["share"],
                       "status": share["status"]})
    measured = [p for p in points if p["share"] is not None]
    if len(measured) < 2:
        return {"points": points, "trend": None,
                "status": "insufficient points for a trend"}
    delta = measured[-1]["share"] - measured[0]["share"]
    return {"points": points, "trend": delta,
            "direction": "improving" if delta > 0 else "flat" if delta == 0 else "declining",
            "status": "measured"}


def foundry_feed(exposures: Sequence[Exposure]) -> List[Dict[str, Any]]:
    """Unhedgeable exposure IS the product gap; route it to the foundry.

    Ordered by size, because the biggest gap is the strongest demand signal.
    """
    gaps = [{"exposure_id": e.exposure_id, "matter_id": e.matter_id,
             "expected_loss_usd": e.expected_loss_usd}
            for e in exposures if not e.hedgeable and e.expected_loss_usd > 0]
    return sorted(gaps, key=lambda g: (-g["expected_loss_usd"], g["exposure_id"]))


# -- renewal annuity engine ---------------------------------------------
def renewal_calendar(filings: Sequence[Filing]) -> List[Dict[str, Any]]:
    """Every filing schedules its own renewal; one-offs are simply absent."""
    calendar = []
    for filing in filings:
        due = filing.renewal_due()
        if due is None:
            continue
        calendar.append({"filing_id": filing.filing_id, "matter_id": filing.matter_id,
                         "kind": filing.kind, "due_on": due.isoformat(),
                         "cadence": filing.cadence,
                         "jurisdiction": filing.jurisdiction})
    return sorted(calendar, key=lambda r: (r["due_on"], r["filing_id"]))


def due_within(filings: Sequence[Filing], as_of: date, days: int) -> List[Dict[str, Any]]:
    """What the ambient monitor should be surfacing right now."""
    if days < 0:
        raise ValueError("days must be non-negative")
    horizon = as_of + timedelta(days=days)
    return [row for row in renewal_calendar(filings)
            if as_of <= date.fromisoformat(row["due_on"]) <= horizon]


def overdue(filings: Sequence[Filing], as_of: date) -> List[Dict[str, Any]]:
    return [row for row in renewal_calendar(filings)
            if date.fromisoformat(row["due_on"]) < as_of]
