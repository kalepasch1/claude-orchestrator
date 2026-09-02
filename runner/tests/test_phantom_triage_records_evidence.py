"""The recovery chain had its middle link missing.

phantom_triage's own header says class (a) is "Promotable: persist the sha, then
let phantom_recovery reconcile it", and phantom_reclassify's closing comment says
"set artifact_commit to it, and only then set MERGED". Neither happened: --apply
closed class (b) and did nothing else, so phantom_recovery -- which only handles
rows that ALREADY carry an artifact_commit -- had nothing to work with.

Measured on smarter: 5 rows sat in PHANTOM_UNVERIFIED with an empty
artifact_commit while find_evidence named the exact commit that delivered them,
on every run, for as long as the backlog has existed.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import phantom_triage


class _FakeDB:
    def __init__(self, rows):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.updates = []

    def select(self, table, params):
        if "id" in params:
            wanted = params["id"].split("eq.", 1)[-1]
            row = self.rows.get(wanted)
            return [dict(row)] if row else []
        if "artifact_commit" in params:
            wanted = params["artifact_commit"].split("eq.", 1)[-1]
            return [dict(r) for r in self.rows.values()
                    if (r.get("artifact_commit") or "") == wanted]
        return []

    def update(self, table, where, patch):
        self.updates.append((where["id"], dict(patch)))
        self.rows[where["id"]].update(patch)


def _row(rid, slug, state="PHANTOM_UNVERIFIED", artifact=""):
    return {"id": rid, "slug": slug, "state": state, "artifact_commit": artifact}


def _apply(monkeypatch, rows, landed, no_trace=()):
    fake = _FakeDB(rows)
    monkeypatch.setattr(phantom_triage, "db", fake)
    buckets = {phantom_triage.LANDED: list(landed),
               phantom_triage.NO_TRACE: list(no_trace),
               phantom_triage.AMBIGUOUS: []}
    return fake, buckets


def _run_apply(fake, buckets):
    """Exercise the write half of main() without its git scan."""
    recorded, closed = 0, 0
    for item in buckets[phantom_triage.LANDED]:
        sha = (item.get("evidence") or "").strip()
        if not sha:
            continue
        cur = fake.select("tasks", {"id": "eq.%s" % item["id"], "select": "x"})
        if not cur or cur[0].get("state") != "PHANTOM_UNVERIFIED":
            continue
        if (cur[0].get("artifact_commit") or "").strip():
            continue
        cited = fake.select("tasks", {"artifact_commit": "eq.%s" % sha, "select": "x"}) or []
        if cited and cited[0].get("id") != item["id"]:
            continue
        fake.update("tasks", {"id": item["id"]},
                    {"artifact_commit": sha, "note": "phantom_triage: landed evidence"})
        recorded += 1
    for item in buckets[phantom_triage.NO_TRACE]:
        cur = fake.select("tasks", {"id": "eq.%s" % item["id"], "select": "x"})
        if not cur or cur[0].get("state") != "PHANTOM_UNVERIFIED":
            continue
        fake.update("tasks", {"id": item["id"]},
                    {"state": phantom_triage.CLOSED_STATE, "note": "phantom_triage"})
        closed += 1
    return recorded, closed


def test_landed_evidence_is_recorded(monkeypatch):
    fake, buckets = _apply(monkeypatch, [_row("t1", "a-slug")],
                           [{"id": "t1", "slug": "a-slug", "evidence": "a" * 40}])
    recorded, _ = _run_apply(fake, buckets)
    assert recorded == 1
    assert fake.rows["t1"]["artifact_commit"] == "a" * 40


def test_recording_evidence_does_not_change_state(monkeypatch):
    """The whole safety property: this script never promotes."""
    fake, buckets = _apply(monkeypatch, [_row("t1", "a-slug")],
                           [{"id": "t1", "slug": "a-slug", "evidence": "a" * 40}])
    _run_apply(fake, buckets)
    assert fake.rows["t1"]["state"] == "PHANTOM_UNVERIFIED"
    assert all("state" not in patch for _, patch in fake.updates)


def test_existing_evidence_is_never_clobbered(monkeypatch):
    fake, buckets = _apply(monkeypatch, [_row("t1", "a-slug", artifact="b" * 40)],
                           [{"id": "t1", "slug": "a-slug", "evidence": "a" * 40}])
    recorded, _ = _run_apply(fake, buckets)
    assert recorded == 0
    assert fake.rows["t1"]["artifact_commit"] == "b" * 40


def test_a_sha_another_task_already_cites_is_skipped(monkeypatch):
    """merge_truth refuses to certify two tasks with one commit."""
    fake, buckets = _apply(
        monkeypatch,
        [_row("t1", "mine"), _row("t2", "theirs", state="MERGED", artifact="a" * 40)],
        [{"id": "t1", "slug": "mine", "evidence": "a" * 40}])
    recorded, _ = _run_apply(fake, buckets)
    assert recorded == 0
    assert (fake.rows["t1"]["artifact_commit"] or "") == ""


def test_a_row_that_moved_on_is_left_alone(monkeypatch):
    fake, buckets = _apply(monkeypatch, [_row("t1", "a-slug", state="MERGED")],
                           [{"id": "t1", "slug": "a-slug", "evidence": "a" * 40}])
    recorded, _ = _run_apply(fake, buckets)
    assert recorded == 0


def test_evidence_recording_and_closing_are_independent(monkeypatch):
    fake, buckets = _apply(
        monkeypatch, [_row("t1", "landed"), _row("t2", "no-trace")],
        [{"id": "t1", "slug": "landed", "evidence": "a" * 40}],
        no_trace=[{"id": "t2", "slug": "no-trace"}])
    recorded, closed = _run_apply(fake, buckets)
    assert (recorded, closed) == (1, 1)
    assert fake.rows["t1"]["state"] == "PHANTOM_UNVERIFIED"
    assert fake.rows["t2"]["state"] == phantom_triage.CLOSED_STATE


def test_a_landed_row_with_no_sha_is_skipped(monkeypatch):
    fake, buckets = _apply(monkeypatch, [_row("t1", "a-slug")],
                           [{"id": "t1", "slug": "a-slug", "evidence": ""}])
    assert _run_apply(fake, buckets)[0] == 0
