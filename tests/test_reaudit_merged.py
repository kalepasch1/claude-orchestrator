"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Proof for rank-3 demote-only re-audit (self_audit_rerun.reaudit_merged_containment).
ANTI-LOSS invariants under test: never delete, never demote in dry-run, demote
only to PHANTOM (via injected callback), exactly one audit row, idempotent, bounded.
"""
from types import SimpleNamespace

from runner.self_audit_rerun import reaudit_merged_containment


def _gate_factory(proven_ids):
    def gate(rec):
        tid = rec.get("task_id")
        if tid in proven_ids:
            return SimpleNamespace(evaluable=True, contains_task_paths=True)
        return SimpleNamespace(evaluable=True, contains_task_paths=False)
    return gate


RECS = [
    {"task_id": "proven", "artifact_commit": "a" * 40},
    {"task_id": "borrowed", "artifact_commit": "b" * 40},
    {"task_id": "evidenced", "artifact_commit": "c" * 40},
]


def test_dry_run_reports_but_changes_nothing():
    demoted_calls, audit_calls = [], []
    rep = reaudit_merged_containment(
        RECS, _gate_factory({"proven"}),
        is_evidenced=lambda r: r["task_id"] == "evidenced",
        demote=lambda r: demoted_calls.append(r),
        audit_writer=lambda s: audit_calls.append(s),
    )
    assert rep.skipped_evidenced == 1
    assert rep.scanned == 2
    assert rep.kept == 1
    assert rep.demoted == 1
    assert rep.dry_run is True
    assert demoted_calls == []   # ANTI-LOSS: dry-run mutates nothing
    assert audit_calls == []


def test_enabled_demotes_only_unproven_and_writes_one_audit_row():
    demoted_calls, audit_calls = [], []
    rep = reaudit_merged_containment(
        RECS, _gate_factory({"proven"}),
        dry_run=False,
        is_evidenced=lambda r: r["task_id"] == "evidenced",
        demote=lambda r: demoted_calls.append(r["task_id"]),
        audit_writer=lambda s: audit_calls.append(s),
    )
    assert demoted_calls == ["borrowed"]          # only the unproven one
    assert rep.demoted == 1 and rep.kept == 1
    assert len(audit_calls) == 1                  # exactly one bulk audit row
    assert audit_calls[0]["to_state"] == "PHANTOM_UNVERIFIED"
    assert audit_calls[0]["row_count"] == 1


def test_no_demotions_writes_no_audit_row():
    audit_calls = []
    rep = reaudit_merged_containment(
        [{"task_id": "proven", "artifact_commit": "a" * 40}],
        _gate_factory({"proven"}),
        dry_run=False,
        demote=lambda r: None,
        audit_writer=lambda s: audit_calls.append(s),
    )
    assert rep.demoted == 0
    assert audit_calls == []                       # nothing changed -> no audit noise


def test_cap_bounds_the_run():
    recs = [{"task_id": "t%d" % i, "artifact_commit": "d" * 40} for i in range(300)]
    rep = reaudit_merged_containment(recs, _gate_factory(set()), cap=200)
    assert rep.scanned == 200
    assert rep.demoted == 200                      # all unproven, but bounded to cap
