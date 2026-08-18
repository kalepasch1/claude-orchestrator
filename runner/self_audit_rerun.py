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


# ─── Rank-3: bounded, demote-only re-audit of the standing MERGED backlog ──────
#
# Re-checks MERGED rows that carry no fresh containment evidence, using the
# rank-1 producer as the gate. ANTI-LOSS by construction: an unproven row is
# demoted to PHANTOM_UNVERIFIED (recoverable, re-verifiable) — NEVER deleted,
# NEVER auto-promoted, NEVER enqueued. dry_run defaults True (report only);
# real state changes happen only when a caller opts in and are recorded as one
# bulk_state_change_audit row. Bounded per run so it cannot storm the plane.


@dataclass
class ReauditReport:
    scanned: int
    skipped_evidenced: int
    kept: int
    demoted: int
    dry_run: bool
    demoted_ids: List[str] = field(default_factory=list)


def reaudit_merged_containment(
    merged_records: Sequence[Mapping[str, object]],
    containment_gate: Callable[[Mapping[str, object]], object],
    *,
    cap: int = 200,
    dry_run: bool = True,
    is_evidenced: Callable[[Mapping[str, object]], bool] = None,
    demote: Callable[[Mapping[str, object]], None] = None,
    audit_writer: Callable[[Mapping[str, object]], None] = None,
) -> ReauditReport:
    """Sort MERGED rows into proven (keep) vs unproven (demote-only).

    containment_gate(record) -> object with .evaluable and .contains_task_paths
    (differential_gate.verify_commit_contains_task). is_evidenced(record)->bool
    lets already-proven rows be skipped so re-runs are idempotent."""
    scanned = 0
    skipped = 0
    kept = 0
    demoted_ids: List[str] = []

    for rec in merged_records or []:
        if is_evidenced is not None:
            try:
                if is_evidenced(rec):
                    skipped += 1
                    continue
            except Exception:
                pass
        if scanned >= cap:
            break
        scanned += 1
        try:
            ev = containment_gate(rec)
            proven = bool(getattr(ev, "evaluable", False)) and bool(
                getattr(ev, "contains_task_paths", False)
            )
        except Exception:
            proven = False  # cannot prove -> unproven; we DEMOTE, never delete
        if proven:
            kept += 1
        else:
            demoted_ids.append(
                str(rec.get("task_id") or rec.get("id") or rec.get("slug") or "")
            )
            if not dry_run and demote is not None:
                try:
                    demote(rec)  # -> PHANTOM_UNVERIFIED (recoverable)
                except Exception:
                    pass

    if not dry_run and demoted_ids and audit_writer is not None:
        try:
            audit_writer({
                "op": "reaudit_demote_unproven_merged",
                "from_state": "MERGED",
                "to_state": "PHANTOM_UNVERIFIED",
                "row_count": len(demoted_ids),
                "task_ids": list(demoted_ids),
                "note": "reaudit: MERGED lacking containment evidence -> demoted for "
                        "re-verification (NOT deleted, NOT enqueued)",
            })
        except Exception:
            pass

    return ReauditReport(
        scanned=scanned,
        skipped_evidenced=skipped,
        kept=kept,
        demoted=len(demoted_ids),
        dry_run=dry_run,
        demoted_ids=demoted_ids,
    )
