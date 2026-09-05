"""rca_engine — the autonomous root-cause classifier, under test.

`runner/rca_engine.py` clusters QUARANTINED/BLOCKED tasks by error signature and emits
remediation guidance that feeds agentic_repair and the approval pipeline. It shipped with
no tests at all, which is a poor place to have none: a misclassification does not fail
anything, it quietly routes a whole cluster of failures to the wrong fix, and the counts
it produces are what decide which root cause looks biggest.

Two defects are pinned here as well:
  * the task read was `db.select`, which PostgREST caps at 1,000 rows — in a COUNTING
    function a truncated read silently under-counts every cluster;
  * that read was unguarded, so a transient DB error crashed a job whose contract is
    fail-soft.
"""
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import db  # noqa: E402
import rca_engine as rca  # noqa: E402


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(rca, "ENABLED", True)
    monkeypatch.setattr(rca, "MIN_CLUSTER", 3)
    monkeypatch.setattr(rca, "MAX_CLUSTERS", 10)


def _rows(notes):
    return [{"id": i, "slug": f"t{i}", "note": n, "kind": "build", "attempt": 1}
            for i, n in enumerate(notes)]


# --- classify_note ----------------------------------------------------------------------

@pytest.mark.parametrize("note,expected", [
    ("semantic-dedupe: duplicate of t9", "duplicate-or-superseded"),
    ("monolith superseded by the new plan", "duplicate-or-superseded"),
    ("repo not found for org/repo", "auth-or-repo-missing"),
    ("PAT lacks access", "auth-or-repo-missing"),
    ("rebase conflict in runner/db.py", "merge-conflict"),
    ("merge conflict integrating agent/x", "merge-conflict"),
    ("tests failed: 3 assertions", "test-failure"),
    ("build fail: cannot find module", "build-failure"),
    ("agent timed out after 900s", "timeout"),
    ("Reached maximum number of turns", "timeout"),
    ("missing branch agent/foo", "missing-branch"),
    ("rate limit exceeded", "rate-limited"),
    ("no space left on device", "disk-space"),
    ("PATCH TEMPLATE 3d86782460c5", "unresolvable-template"),
    ("nothing to commit, working tree clean", "no-op"),
])
def test_known_signatures_are_classified(note, expected):
    assert rca.classify_note(note) == expected


def test_classification_is_case_insensitive():
    assert rca.classify_note("MERGE CONFLICT in x") == "merge-conflict"


def test_an_unrecognised_note_is_unknown_not_guessed():
    """Guessing a category would route a real failure to a confidently wrong fix."""
    assert rca.classify_note("something nobody has seen before") == "unknown"


@pytest.mark.parametrize("bad", [None, "", 0, [], {}])
def test_classify_is_fail_soft_on_junk(bad):
    assert rca.classify_note(bad) == "unknown"


def test_every_category_has_remediation_guidance():
    """A cluster with no guidance is a report the reader cannot act on."""
    for _pattern, category in rca._SIGNATURES:
        assert rca._REMEDIATIONS.get(category, "").strip(), category


# --- analyze ------------------------------------------------------------------------------

def test_clusters_are_counted_and_ranked(monkeypatch):
    notes = ["merge conflict"] * 5 + ["tests failed"] * 3
    monkeypatch.setattr(db, "select_all", lambda *a, **k: _rows(notes))

    out = rca.analyze()

    assert [c["root_cause"] for c in out] == ["merge-conflict", "test-failure"]
    assert [c["count"] for c in out] == [5, 3]
    assert out[0]["remediation"]


def test_a_cluster_below_the_minimum_is_not_reported(monkeypatch):
    monkeypatch.setattr(db, "select_all",
                        lambda *a, **k: _rows(["merge conflict"] * 5 + ["disk space"] * 2))
    assert [c["root_cause"] for c in rca.analyze()] == ["merge-conflict"]


def test_samples_are_capped_and_truncated(monkeypatch):
    monkeypatch.setattr(db, "select_all",
                        lambda *a, **k: _rows(["merge conflict " + "x" * 500] * 9))
    cluster = rca.analyze()[0]
    assert len(cluster["samples"]) == 3
    assert all(len(s["note"]) <= 200 for s in cluster["samples"])


def test_the_scan_is_paged_not_capped_at_one_page(monkeypatch):
    """The counting bug: db.select stops at 1,000 rows and under-counts every cluster."""
    used = {}
    monkeypatch.setattr(db, "select_all",
                        lambda *a, **k: used.setdefault("paged", True) and _rows([]) or _rows([]))
    monkeypatch.setattr(db, "select",
                        lambda *a, **k: pytest.fail("must page with select_all, not select"))
    rca.analyze()
    assert used.get("paged") is True


def test_all_rows_are_counted_beyond_one_page(monkeypatch):
    monkeypatch.setattr(db, "select_all", lambda *a, **k: _rows(["merge conflict"] * 2500))
    assert rca.analyze()[0]["count"] == 2500


def test_a_transient_db_error_reports_no_clusters_instead_of_crashing(monkeypatch):
    def boom(*a, **k):
        raise db.TransientDBError("control plane unreachable")
    monkeypatch.setattr(db, "select_all", boom)
    assert rca.analyze() == []


def test_disabled_engine_does_no_work(monkeypatch):
    monkeypatch.setattr(rca, "ENABLED", False)
    monkeypatch.setattr(db, "select_all",
                        lambda *a, **k: pytest.fail("must not read while disabled"))
    assert rca.analyze() == []


def test_an_empty_queue_yields_no_clusters(monkeypatch):
    monkeypatch.setattr(db, "select_all", lambda *a, **k: [])
    assert rca.analyze() == []


def test_a_project_filter_is_passed_through(monkeypatch):
    seen = {}

    def capture(table, params=None, **k):
        seen["params"] = params
        return []

    monkeypatch.setattr(db, "select_all", capture)
    rca.analyze(project_id="p1")
    assert seen["params"]["project_id"] == "eq.p1"
    assert "QUARANTINED" in seen["params"]["state"]
