"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Periodic self-audit re-run.

Samples recent MERGED records, re-runs the identical DoD gate against each
recorded sha, and demotes+re-queues anything that no longer reproduces green.
Cheap durable defense against silent drift/regression. Pure; the re-run is
injected so it is unit-tested without a repo or test runner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Mapping, Sequence


@dataclass
class AuditOutcome:
    slug: str
    sha: str
    reproduced: bool
    action: str  # "keep" | "demote_and_requeue"


@dataclass
class AuditReport:
    total: int
    reproduced: int
    demoted: int
    outcomes: List[AuditOutcome] = field(default_factory=list)

    @property
    def drift_rate(self) -> float:
        return (self.demoted / self.total) if self.total else 0.0


def self_audit(
    merged_records: Sequence[Mapping[str, str]],
    rerun_gate: Callable[[Mapping[str, str]], bool],
) -> AuditReport:
    """merged_records: rows with at least {'slug','sha'}. rerun_gate(record)->bool
    True when the recorded merge still passes its identical gate."""
    outcomes: List[AuditOutcome] = []
    for rec in merged_records or []:
        try:
            ok = bool(rerun_gate(rec))
        except Exception:
            ok = False  # a gate that can't even run is not reproducible
        outcomes.append(
            AuditOutcome(
                slug=str(rec.get("slug", "")),
                sha=str(rec.get("sha", "")),
                reproduced=ok,
                action="keep" if ok else "demote_and_requeue",
            )
        )
    demoted = sum(1 for o in outcomes if not o.reproduced)
    return AuditReport(
        total=len(outcomes),
        reproduced=len(outcomes) - demoted,
        demoted=demoted,
        outcomes=outcomes,
    )
