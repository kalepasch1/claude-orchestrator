#!/usr/bin/env python3
"""Gates and evidence for the staged V15 fleet rollout.

This module is the *verification* half of the release, deliberately separated
from the *execution* half:

    it decides whether a capability may advance, and records why;
    it never deploys, never merges and never pushes.

That separation is the point.  The established release train performs staged
rollout, and a verification tool that can also deploy is a second deployment
path by another name -- which is exactly what the fleet already has one of.

Three rules are enforced here rather than left to judgement:

* **Promotion is per capability, never fleet-wide.**  :func:`promote` advances
  one capability one stage, and only when every gate passes.  A green average
  across ten capabilities can hide one that is broken.
* **Unsupported performance expectations are labelled, not repeated.**  The V15
  proposal advertises 50X-500X.  :func:`compare_to_baseline` reports the ratio
  it actually measured and marks anything not backed by a measurement as
  ``unverified``.  It will not convert a target into a result.
* **Evidence is immutable and hash-chained.**  :class:`EvidenceLog` appends
  records linked by digest, so a later edit is detectable rather than silent.

Gate order is correctness -> privacy -> safety -> cost -> tail latency, and a
failure at any of them stops the promotion with the reason recorded.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: The ten fleet apps plus the orchestrator, which must all be verified.
FLEET_APPS: Tuple[str, ...] = (
    "galop", "tomorrow", "smarter", "pareto", "apparently",
    "orchestrator", "vigil", "hisanta", "predictions", "trojun",
)

STAGES: Tuple[str, ...] = ("off", "canary", "rollout", "general")

#: Named in the proposal, never asserted by this module.
ADVERTISED_SPEEDUP_RANGE = (50.0, 500.0)


class PromotionRefused(RuntimeError):
    """A capability failed a gate and was not advanced."""


class DependenciesNotReady(RuntimeError):
    """Verification was attempted before its inputs were merged and green."""


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()


# -- evidence ------------------------------------------------------------
@dataclass(frozen=True)
class EvidenceRecord:
    seq: int
    kind: str
    subject: str
    payload: Dict[str, Any]
    at: float
    prev_hash: str
    digest: str

    def recompute(self) -> str:
        return _digest({"seq": self.seq, "kind": self.kind, "subject": self.subject,
                        "payload": self.payload, "at": self.at, "prev": self.prev_hash})


class EvidenceLog:
    """Append-only hash chain.  Tampering is detectable, not preventable."""

    GENESIS = "0" * 32

    def __init__(self) -> None:
        self._records: List[EvidenceRecord] = []

    def append(self, kind: str, subject: str, payload: Dict[str, Any],
               at: Optional[float] = None) -> EvidenceRecord:
        prev = self._records[-1].digest if self._records else self.GENESIS
        seq = len(self._records)
        at = at if at is not None else time.time()
        digest = _digest({"seq": seq, "kind": kind, "subject": subject,
                          "payload": payload, "at": at, "prev": prev})
        record = EvidenceRecord(seq, kind, subject, dict(payload), at, prev, digest)
        self._records.append(record)
        return record

    def records(self) -> List[EvidenceRecord]:
        return list(self._records)

    def verify(self) -> Dict[str, Any]:
        """Recompute every digest and every link."""
        broken: List[Dict[str, Any]] = []
        prev = self.GENESIS
        for record in self._records:
            if record.prev_hash != prev:
                broken.append({"seq": record.seq, "reason": "broken_link"})
            elif record.recompute() != record.digest:
                broken.append({"seq": record.seq, "reason": "payload_tampered"})
            prev = record.digest
        return {"records": len(self._records), "intact": not broken, "broken": broken}


# -- readiness -----------------------------------------------------------
@dataclass(frozen=True)
class Dependency:
    name: str
    merged: bool = False
    tests_green: bool = False


def readiness(dependencies: Sequence[Dependency]) -> Dict[str, Any]:
    """Every dependency must be BOTH merged and green before verification runs."""
    unmerged = sorted(d.name for d in dependencies if not d.merged)
    red = sorted(d.name for d in dependencies if d.merged and not d.tests_green)
    return {
        "total": len(dependencies),
        "ready": not unmerged and not red and bool(dependencies),
        "unmerged": unmerged,
        "failing": red,
    }


def require_ready(dependencies: Sequence[Dependency]) -> None:
    state = readiness(dependencies)
    if not state["ready"]:
        raise DependenciesNotReady(
            f"unmerged={state['unmerged']} failing={state['failing']}")


# -- coverage ------------------------------------------------------------
def coverage(verified_apps: Sequence[str]) -> Dict[str, Any]:
    """All ten apps plus the orchestrator, or the rollout is not verified."""
    seen = {a.strip().lower() for a in verified_apps}
    missing = sorted(set(FLEET_APPS) - seen)
    return {"required": len(FLEET_APPS), "verified": len(seen & set(FLEET_APPS)),
            "missing": missing, "complete": not missing}


# -- measurement ---------------------------------------------------------
def compare_to_baseline(baseline: Optional[float], measured: Optional[float]
                        ) -> Dict[str, Any]:
    """Report the measured ratio, and refuse to invent one.

    A missing baseline or a missing measurement yields ``unverified`` with a
    null ratio -- never a default of 1.0, which would read as "no regression"
    when in truth nothing was measured at all.
    """
    if baseline is None or measured is None or baseline <= 0 or measured <= 0:
        return {"baseline": baseline, "measured": measured, "ratio": None,
                "status": "unverified",
                "reason": "missing or non-positive baseline/measurement"}
    ratio = baseline / measured
    low, high = ADVERTISED_SPEEDUP_RANGE
    return {
        "baseline": baseline, "measured": measured, "ratio": ratio,
        "status": "measured",
        "meets_advertised_range": low <= ratio <= high,
        "advertised_range": list(ADVERTISED_SPEEDUP_RANGE),
        "note": ("the advertised 50X-500X figures are proposal TARGETS; this "
                 "reports the ratio observed here and makes no claim beyond it"),
    }


def label_unverified_claims(claims: Sequence[str],
                            measurements: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Mark every claim without a backing measurement as explicitly unverified."""
    out = []
    for claim in claims:
        measurement = measurements.get(claim)
        supported = bool(measurement) and measurement.get("status") == "measured"
        out.append({"claim": claim, "status": "measured" if supported else "unverified",
                    "measurement": measurement})
    return out


# -- gates ---------------------------------------------------------------
@dataclass
class GateResults:
    correctness: bool = False
    privacy: bool = False
    safety: bool = False
    cost_ok: bool = False
    tail_latency_ok: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)

    #: Order matters: a correctness failure is reported before a cost failure.
    ORDER = ("correctness", "privacy", "safety", "cost_ok", "tail_latency_ok")

    def failures(self) -> List[str]:
        return [name for name in self.ORDER if not getattr(self, name)]


def evaluate_gates(results: GateResults) -> Dict[str, Any]:
    failures = results.failures()
    return {"passed": not failures, "failed_gates": failures, "detail": results.detail}


def promote(capability: str, current_stage: str, results: GateResults,
            evidence: Optional[EvidenceLog] = None) -> Dict[str, Any]:
    """Advance ONE capability by ONE stage, only when every gate passes."""
    if current_stage not in STAGES:
        raise ValueError(f"unknown stage {current_stage!r}")
    gates = evaluate_gates(results)
    index = STAGES.index(current_stage)
    at_top = index >= len(STAGES) - 1
    advance = gates["passed"] and not at_top
    decision = {
        "capability": capability,
        "current_stage": current_stage,
        "next_stage": STAGES[index + 1] if advance else current_stage,
        "promoted": advance,
        "failed_gates": gates["failed_gates"],
        "at_final_stage": at_top,
        "note": "one capability, one stage, all gates; never a fleet-wide promotion",
    }
    if evidence is not None:
        evidence.append("promotion_decision", capability, decision)
    return decision


def require_promotable(capability: str, current_stage: str, results: GateResults) -> None:
    decision = promote(capability, current_stage, results)
    if not decision["promoted"]:
        raise PromotionRefused(
            f"{capability}: {decision['failed_gates'] or 'already at final stage'}")


# -- migrations ----------------------------------------------------------
def migration_plan(migrations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Only reviewed, idempotent migrations may go through the established path."""
    approved, rejected = [], []
    for migration in migrations:
        name = migration.get("name", "<unnamed>")
        reasons = []
        if not migration.get("reviewed"):
            reasons.append("not_reviewed")
        if not migration.get("idempotent"):
            reasons.append("not_idempotent")
        if migration.get("path") != "established":
            reasons.append("bypasses_established_migration_path")
        (approved if not reasons else rejected).append(
            {"name": name, "reasons": reasons} if reasons else {"name": name})
    return {"approved": approved, "rejected": rejected,
            "all_clear": not rejected,
            "note": "this plans migrations; applying them is the release train's job"}


def release_report(dependencies: Sequence[Dependency], verified_apps: Sequence[str],
                   evidence: EvidenceLog) -> Dict[str, Any]:
    """One place an operator can read the whole state of the rollout."""
    return {
        "readiness": readiness(dependencies),
        "coverage": coverage(verified_apps),
        "evidence": evidence.verify(),
        "deploys_performed": 0,
        "note": ("verification only: this module records and decides, it does not "
                 "deploy, merge or push; staged rollout runs on the existing train"),
    }
