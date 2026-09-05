#!/usr/bin/env python3
"""A requeue reason must not destroy the resolution it is requeueing over.

slo_controller's trigger_patch_recovery action selects BLOCKED tasks with
`note like %missing%branch%` and then overwrites `note` with
"slo: requeued for patch recovery".

The selector reads prose and the update deletes the prose it read. Any task blocked for
an unrelated reason that merely *mentions* a missing branch while explaining itself gets
swept, and the explanation is gone.

Observed 2026-08-24: a task blocked because a pre-push author-identity guard refused the
push wrote a note naming the offending commit and how to fix it. The note contained the
words "missing branch" while describing a different code path. Ten minutes later it was
QUEUED again with a four-word note, and the next executor had to re-derive everything.

The loop is self-concealing — the evidence that would expose it is what gets overwritten.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import slo_controller  # noqa: E402


@pytest.fixture
def db(monkeypatch):
    """Stub db.select/update and record every write."""
    state = {"rows": [], "updates": []}

    monkeypatch.setattr(slo_controller.db, "select",
                        lambda table, params: list(state["rows"]))
    monkeypatch.setattr(slo_controller.db, "update",
                        lambda table, where, patch: state["updates"].append((where, patch)))
    return state


def _recover(db_stub, rows):
    db_stub["rows"] = rows
    slo_controller._apply_action({"action": "trigger_patch_recovery"})
    return db_stub["updates"]


def test_prior_note_is_preserved(db):
    prior = ("cowork-executor: BLOCKED — push refused by author_identity_guard because "
             "commit dd94eb79 is authored noreply@anthropic.com. Unrelated to the "
             "missing branch path.")
    updates = _recover(db, [{"id": "t1", "slug": "s1", "note": prior}])

    assert len(updates) == 1
    note = updates[0][1]["note"]
    assert "slo: requeued for patch recovery" in note
    assert "dd94eb79" in note, (
        "the requeue reason replaced the diagnosis instead of adding to it; "
        "the next executor now has to re-derive it from nothing"
    )


def test_explicit_no_artifact_resolution_is_not_requeued(db):
    """NO-ARTIFACT-JUSTIFIED is a decision, not a symptom to retry."""
    updates = _recover(db, [{
        "id": "t1", "slug": "s1",
        "note": "NO-ARTIFACT-JUSTIFIED: no code target; the missing branch never existed",
    }])
    assert updates == [], "requeueing a settled decision asks the fleet to re-derive it"


def test_genuine_missing_branch_task_is_still_requeued(db):
    """The recovery path must keep working for what it was built for."""
    updates = _recover(db, [{
        "id": "t1", "slug": "s1",
        "note": "train: approved, but agent/s1 is still missing after 2 rebuilds",
    }])

    assert len(updates) == 1
    patch = updates[0][1]
    assert patch["state"] == "QUEUED"
    assert patch["kind"] == "recovery"


def test_empty_note_does_not_produce_a_dangling_separator(db):
    updates = _recover(db, [{"id": "t1", "slug": "s1", "note": ""}])
    assert updates[0][1]["note"] == "slo: requeued for patch recovery"


def test_preserved_note_is_bounded(db):
    """A task cycling repeatedly must not grow an unbounded note."""
    updates = _recover(db, [{"id": "t1", "slug": "s1",
                             "note": "missing branch " + ("x" * 5000)}])
    assert len(updates[0][1]["note"]) < 800


def test_missing_note_key_is_tolerated(db):
    """db.select shapes vary across callers; absence must not raise."""
    updates = _recover(db, [{"id": "t1", "slug": "s1"}])
    assert updates[0][1]["note"] == "slo: requeued for patch recovery"
