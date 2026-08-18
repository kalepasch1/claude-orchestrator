"""One commit must not certify two tasks — the client gate now agrees with the database.

WHY THIS EXISTS

`enforce_evidence_on_closure()` in Postgres refuses a closure whose `artifact_commit` is
already cited by another task in DONE / MERGED / DEPLOYED_AND_VERIFIED, unless the note
carries `NO-ARTIFACT-JUSTIFIED:`. `merge_truth` did not know that rule, so it proposed
writes the database then rejected. Draining the phantom backlog on 2026-08-18 produced
**25 such rejections out of 161 writes** — every one of them this case.

The reason it matters beyond tidiness: one commit certifying several tasks is the
documented slice-1-certifies-slice-2..N phantom, one of the three root causes the
2026-08-04 audit blamed for 10,584 false MERGED rows. `verify_merge_reachable()` only asks
whether a sha is REACHABLE. A sha can be perfectly reachable and still be the wrong
evidence for this task, because it is already the evidence for a different one.

The check FAILS OPEN. A database error returns None, and the merge proceeds — being unable
to ask whether a duplicate exists is not evidence that one does, and this must never be the
reason legitimate work is withheld.
"""
import os
import sys

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import merge_truth  # noqa: E402

PROJECT = {
    "id": "p1", "name": "beethoven", "repo_path": "/tmp/beethoven",
    "staging_branch": "orchestrator/dev", "prod_branch": "master", "default_base": "master",
}
SHA = "abc123def456"


class FakeDB:
    """Serves the projects row, and whatever `tasks` rows a test wants for the dup query."""

    def __init__(self, dup_rows=None, raises=None):
        self.dup_rows = dup_rows or []
        self.raises = raises
        self.task_queries = []

    def select(self, table, params=None):
        if table == "projects":
            return [PROJECT]
        if table == "tasks":
            self.task_queries.append(params or {})
            if self.raises:
                raise self.raises
            return list(self.dup_rows)
        return []


_REAL_DB = merge_truth.db


def _install(db):
    merge_truth.db = db
    merge_truth.invalidate_project_cache()
    return db


def teardown_function(_):
    merge_truth.db = _REAL_DB
    merge_truth.invalidate_project_cache()


def _gate(monkeypatch, db, note=None, task_note=None, verdict=None):
    """Run gate_merged_patch with reachability stubbed to the given verdict (default OK)."""
    monkeypatch.setattr(merge_truth, "verify_merge_reachable",
                        lambda *a, **k: (verdict or merge_truth.OK, "ancestor"))
    task = {"id": "t1", "slug": "the-task", "project_id": "p1", "artifact_commit": SHA}
    if task_note is not None:
        task["note"] = task_note
    patch = {"state": "MERGED", "artifact_commit": SHA}
    if note is not None:
        patch["note"] = note
    return merge_truth.gate_merged_patch(task, patch, fetch=False), patch


# ---------------------------------------------------------------- the predicate itself

def test_no_other_task_cites_the_commit():
    _install(FakeDB(dup_rows=[]))
    assert merge_truth._commit_already_cited(SHA, "t1") is None


def test_another_closed_task_citing_it_is_reported():
    _install(FakeDB(dup_rows=[{"id": "t2", "slug": "slice-1"}]))
    assert merge_truth._commit_already_cited(SHA, "t1") == "slice-1"


def test_the_same_task_citing_it_is_not_a_duplicate():
    """Re-writing MERGED on a row that already carries this sha must stay allowed."""
    _install(FakeDB(dup_rows=[{"id": "t1", "slug": "the-task"}]))
    assert merge_truth._commit_already_cited(SHA, "t1") is None


def test_id_comparison_survives_int_vs_str():
    _install(FakeDB(dup_rows=[{"id": 1, "slug": "the-task"}]))
    assert merge_truth._commit_already_cited(SHA, "1") is None


def test_a_row_with_no_slug_still_reports_something_actionable():
    _install(FakeDB(dup_rows=[{"id": "t2"}]))
    assert merge_truth._commit_already_cited(SHA, "t1") == "(unnamed task)"


def test_empty_sha_is_never_a_duplicate():
    db = _install(FakeDB(dup_rows=[{"id": "t2", "slug": "other"}]))
    assert merge_truth._commit_already_cited("", "t1") is None
    assert merge_truth._commit_already_cited(None, "t1") is None
    assert db.task_queries == []


def test_database_error_fails_open():
    """Unable to ask is not evidence of a duplicate."""
    _install(FakeDB(raises=RuntimeError("control plane down")))
    assert merge_truth._commit_already_cited(SHA, "t1") is None


def test_the_query_matches_the_database_trigger_exactly():
    """If these drift apart the client starts proposing writes the DB rejects again."""
    db = _install(FakeDB(dup_rows=[]))
    merge_truth._commit_already_cited(SHA, "t1")
    q = db.task_queries[-1]
    assert q["artifact_commit"] == f"eq.{SHA}"
    for state in ("DONE", "MERGED", "DEPLOYED_AND_VERIFIED"):
        assert state in q["state"]
    assert q["state"].startswith("in.(")


def test_closed_states_constant_matches_the_trigger():
    assert set(merge_truth.CLOSED_STATES) == {"DONE", "MERGED", "DEPLOYED_AND_VERIFIED"}


def test_justified_marker_constant_is_what_the_trigger_looks_for():
    assert merge_truth.JUSTIFIED_MARKER == "NO-ARTIFACT-JUSTIFIED:"


# ---------------------------------------------------------------- the gate

def test_unique_commit_passes_the_gate(monkeypatch):
    _install(FakeDB(dup_rows=[]))
    out, patch = _gate(monkeypatch, None)
    assert out == patch


def test_duplicate_commit_is_refused(monkeypatch):
    _install(FakeDB(dup_rows=[{"id": "t2", "slug": "slice-1"}]))
    out, _ = _gate(monkeypatch, None)
    assert out is None, "a second task citing one commit is the slice-1 phantom"


def test_refusal_leaves_the_row_untouched(monkeypatch, capsys):
    """None means 'write nothing', not 'write PHANTOM' — the row is closed deliberately
    elsewhere and must not be rewritten on the strength of ambiguous evidence."""
    _install(FakeDB(dup_rows=[{"id": "t2", "slug": "slice-1"}]))
    out, _ = _gate(monkeypatch, None)
    assert out is None
    assert "already the artifact_commit of slice-1" in capsys.readouterr().out


def test_justified_marker_in_the_patch_note_overrides(monkeypatch):
    _install(FakeDB(dup_rows=[{"id": "t2", "slug": "slice-1"}]))
    out, patch = _gate(monkeypatch, None,
                       note="NO-ARTIFACT-JUSTIFIED: shared commit, one PR landed both slices")
    assert out == patch


def test_justified_marker_on_the_existing_task_note_overrides(monkeypatch):
    _install(FakeDB(dup_rows=[{"id": "t2", "slug": "slice-1"}]))
    out, patch = _gate(monkeypatch, None,
                       task_note="NO-ARTIFACT-JUSTIFIED: recorded when the row was opened")
    assert out == patch


def test_database_error_does_not_withhold_a_legitimate_merge(monkeypatch):
    _install(FakeDB(raises=RuntimeError("control plane down")))
    out, patch = _gate(monkeypatch, None)
    assert out == patch


def test_non_merged_patches_are_never_dup_checked(monkeypatch):
    db = _install(FakeDB(dup_rows=[{"id": "t2", "slug": "slice-1"}]))
    task = {"id": "t1", "slug": "the-task", "project_id": "p1"}
    patch = {"state": "QUEUED"}
    assert merge_truth.gate_merged_patch(task, patch) == patch
    assert db.task_queries == []


def test_phantom_verdict_is_unaffected(monkeypatch):
    """A duplicate check must not turn a phantom into something else."""
    _install(FakeDB(dup_rows=[{"id": "t2", "slug": "slice-1"}]))
    out, _ = _gate(monkeypatch, None, verdict=merge_truth.PHANTOM)
    assert out is not None
    assert out["state"] == merge_truth.PHANTOM_STATE


def test_infra_error_verdict_is_unaffected(monkeypatch):
    _install(FakeDB(dup_rows=[{"id": "t2", "slug": "slice-1"}]))
    out, _ = _gate(monkeypatch, None, verdict=merge_truth.INFRA_ERROR)
    assert out is None


def test_the_dup_check_runs_only_after_reachability(monkeypatch):
    """Ordering matters: an unreachable sha should not cost a control-plane round-trip."""
    db = _install(FakeDB(dup_rows=[]))
    _gate(monkeypatch, None, verdict=merge_truth.PHANTOM)
    assert db.task_queries == [], "no dup query should be issued for a phantom"


def test_one_extra_round_trip_at_most(monkeypatch):
    """The gate already reads the projects row; the dup check must add exactly one query."""
    db = _install(FakeDB(dup_rows=[]))
    _gate(monkeypatch, None)
    assert len(db.task_queries) == 1
