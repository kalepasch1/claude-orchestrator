"""Selection rules for stranded-branch recovery.

These pin the properties that stop this from becoming another
M4_bulk_resolved_sweep: no in-flight task is requeued, no branch without a task
row invents one, ambiguity never resolves to a guess, and the batch is capped.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stranded_recovery_queue import (  # noqa: E402
    DEFAULT_BATCH,
    classify_conflicting,
    provenance_note,
    recovery_candidates,
)


def row(slug, clean=True, added=100, files=2, age=1.0):
    return {"slug": slug, "branch": f"origin/agent/{slug}", "clean_merge": clean,
            "source_added": added, "source_files": files, "age_days": age,
            "source_removed": 0, "excluded_added": 0}


def test_phantom_merged_branches_are_recovered_first():
    """A task saying MERGED whose branch never reached master is the top case."""
    rows = [row("small-phantom", added=10), row("quarantined-big", added=9999),
            row("big-phantom", added=500)]
    states = {"small-phantom": "MERGED", "quarantined-big": "QUARANTINED",
              "big-phantom": "MERGED"}

    picks = recovery_candidates(rows, states)

    assert [p["slug"] for p in picks][:2] == ["big-phantom", "small-phantom"]
    assert picks[0]["prior_state"] == "MERGED"


def test_in_flight_tasks_are_never_requeued():
    """DONE/QUEUED/RUNNING/DECOMPOSED still drain on their own post-7ec2d4e."""
    rows = [row(s) for s in ("a", "b", "c", "d")]
    states = {"a": "DONE", "b": "QUEUED", "c": "RUNNING", "d": "DECOMPOSED"}

    assert recovery_candidates(rows, states) == []


def test_branch_without_a_task_row_is_not_invented():
    rows = [row("orphan-branch")]

    assert recovery_candidates(rows, {}) == []


def test_conflicting_branches_are_never_requeued():
    rows = [row("conflicted", clean=False)]

    assert recovery_candidates(rows, {"conflicted": "MERGED"}) == []


def test_batch_is_capped():
    rows = [row(f"phantom-{i}") for i in range(200)]
    states = {f"phantom-{i}": "MERGED" for i in range(200)}

    assert len(recovery_candidates(rows, states)) == DEFAULT_BATCH
    assert len(recovery_candidates(rows, states, batch=5)) == 5


def test_recovered_slug_is_suffixed_and_bounded():
    rows = [row("x" * 300)]
    states = {"x" * 300: "MERGED"}

    pick = recovery_candidates(rows, states)[0]

    assert pick["recovered_slug"].endswith("-recovered")
    assert len(pick["recovered_slug"]) <= 200


def test_provenance_note_names_the_branch_and_the_phantom_case():
    rows = [row("ghost")]
    note = provenance_note(recovery_candidates(rows, {"ghost": "MERGED"})[0])

    assert "origin/agent/ghost" in note
    assert "phantom merge" in note
    assert "not a direct merge" in note


def test_conflicting_classification_only_calls_superseded_when_nothing_remains():
    empty = row("nothing-left", clean=False, added=0, files=0)
    assert classify_conflicting(empty)[0] == "superseded"


@pytest.mark.parametrize("added,files", [(1, 1), (500, 9)])
def test_conflicting_with_remaining_source_goes_to_operator_not_a_guess(added, files):
    """Closing real work as superseded on thin evidence destroys it. Never guess."""
    klass, why = classify_conflicting(row("ambiguous", clean=False,
                                          added=added, files=files))

    assert klass == "unclear"
    assert "operator" in why
