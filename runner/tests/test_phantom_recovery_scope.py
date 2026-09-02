"""The reconciler could only see one slug prefix, so the fleet's evidence was unread.

phantom_recovery was written to recover OPERATOR improvements, and both of its
scans are scoped `slug like 'dropbox-%'`. That scope is right for the requeue
path, which regenerates work. It is wrong for artifact reconciliation, which
moves a row only on merge_truth's verdict about a real commit and regenerates
nothing.

Measured 2026-08-23, once phantom_triage started recording evidence: 188
PHANTOM_UNVERIFIED rows carried an exact artifact_commit and 2 of them had a
dropbox- slug. 186 had no reconciler at all — the evidence was found, written
down, and read by nobody.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import phantom_recovery


def _capture_selects(monkeypatch):
    calls = []

    def fake_select(table, params):
        calls.append(dict(params))
        return []

    monkeypatch.setattr(phantom_recovery.db, "select", fake_select)
    return calls


def test_the_evidenced_scan_is_not_slug_scoped(monkeypatch):
    calls = _capture_selects(monkeypatch)
    phantom_recovery._evidenced_phantom_rows(50)
    assert len(calls) == 1
    params = calls[0]
    assert "slug" not in params, "scoping this scan is what stranded the fleet"
    assert params["state"] == "eq.PHANTOM_UNVERIFIED"
    assert params["artifact_commit"] == "not.is.null"


def test_the_evidenced_scan_requires_evidence(monkeypatch):
    """It must never widen to rows with nothing to reconcile."""
    calls = _capture_selects(monkeypatch)
    phantom_recovery._evidenced_phantom_rows(50)
    assert calls[0]["artifact_commit"] == "not.is.null"


def test_the_requeue_scan_stays_narrow(monkeypatch):
    """The path that regenerates work keeps its operator scope."""
    calls = _capture_selects(monkeypatch)
    phantom_recovery._candidate_rows(50)
    assert calls[0]["slug"] == "like.dropbox-%"


def test_the_stranded_scan_stays_narrow(monkeypatch):
    calls = _capture_selects(monkeypatch)
    phantom_recovery._stranded_artifact_rows(50)
    assert calls[0]["slug"] == "like.dropbox-%"


def test_the_limit_is_honoured_and_floored(monkeypatch):
    calls = _capture_selects(monkeypatch)
    phantom_recovery._evidenced_phantom_rows(7)
    assert calls[0]["limit"] == "7"
    phantom_recovery._evidenced_phantom_rows(0)
    assert calls[1]["limit"] == "1", "a zero limit must not become an unbounded scan"


def test_a_general_row_is_reconciled_but_never_requeued(monkeypatch):
    """The safety property: hard evidence can move it; nothing can regenerate it."""
    general = {"id": "g1", "slug": "smarter-thing", "state": "PHANTOM_UNVERIFIED",
               "artifact_commit": "a" * 40, "prompt": "", "note": "", "project_id": "p"}
    monkeypatch.setattr(phantom_recovery, "_candidate_rows", lambda limit: [])
    monkeypatch.setattr(phantom_recovery, "_stranded_artifact_rows", lambda limit: [])
    monkeypatch.setattr(phantom_recovery, "_evidenced_phantom_rows", lambda limit: [general])

    reconciled, requeued = [], []
    monkeypatch.setattr(phantom_recovery, "_reconcile_artifact",
                        lambda row, now: (reconciled.append(row["id"]), "restored")[1])
    monkeypatch.setattr(phantom_recovery.db, "update",
                        lambda *a, **k: requeued.append(a))
    monkeypatch.setattr(phantom_recovery.db, "insert", lambda *a, **k: None)
    monkeypatch.setattr(phantom_recovery.db, "select", lambda *a, **k: [])

    phantom_recovery.recover(limit=10)
    assert reconciled == ["g1"], "the general row must reach reconciliation"
    assert requeued == [], "and must never reach the requeue path"


def test_a_row_seen_by_two_scans_is_reconciled_once(monkeypatch):
    dup = {"id": "d1", "slug": "dropbox-thing", "state": "PHANTOM_UNVERIFIED",
           "artifact_commit": "b" * 40, "prompt": "", "note": "", "project_id": "p"}
    monkeypatch.setattr(phantom_recovery, "_candidate_rows", lambda limit: [dict(dup)])
    monkeypatch.setattr(phantom_recovery, "_stranded_artifact_rows", lambda limit: [])
    monkeypatch.setattr(phantom_recovery, "_evidenced_phantom_rows", lambda limit: [dict(dup)])

    seen = []
    monkeypatch.setattr(phantom_recovery, "_reconcile_artifact",
                        lambda row, now: (seen.append(row["id"]), "restored")[1])
    monkeypatch.setattr(phantom_recovery.db, "update", lambda *a, **k: None)
    monkeypatch.setattr(phantom_recovery.db, "insert", lambda *a, **k: None)
    monkeypatch.setattr(phantom_recovery.db, "select", lambda *a, **k: [])

    phantom_recovery.recover(limit=10)
    assert seen == ["d1"], f"reconciled {len(seen)} times, expected once"
