#!/usr/bin/env python3
"""Tests for childless-decomposition classification and unsatisfiable deps.

Pure functions only — no database. Run: python3 -m pytest tools/ -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.queue_health import (  # noqa: E402
    classify_task, summarize, unsatisfiable_deps,
)
from tools.reconcile_childless_decompositions import (  # noqa: E402
    AUTO_APPLY, DONE_BY_SUCCESSION, LEAVE, RELINK, REQUEUE_PARENT,
    REVIEW_SUCCESSOR_TERMINAL, build_plan, classify,
)

P = "proj-1"


def parent(slug, note=None, pid=P, tid=None):
    return {"id": tid or ("id-" + slug), "slug": slug, "project_id": pid,
            "note": note, "state": "DECOMPOSED"}


def child(slug, state="QUEUED", parent_task_id=None, pid=P):
    return {"id": "id-" + slug, "slug": slug, "project_id": pid,
            "state": state, "parent_task_id": parent_task_id}


# --------------------------------------------------------------------------
# classify() — one parent at a time
# --------------------------------------------------------------------------


def test_parent_with_linked_children_is_left_to_the_normal_path():
    verdict, detail = classify(parent("a"), [child("a-slice-1")], [], {})
    assert verdict == LEAVE
    assert "normal close path" in detail


def test_compactor_successor_that_shipped_marks_parent_done():
    successor = {"slug": "backlog-batch-x", "project_id": P, "state": "MERGED"}
    verdict, detail = classify(
        parent("a", note="backlog-compactor: collapsed into backlog-batch-x"),
        [], [], {(P, "backlog-batch-x"): successor})
    assert verdict == DONE_BY_SUCCESSION
    assert "backlog-batch-x" in detail


def test_compactor_successor_still_queued_requeues_the_parent():
    successor = {"slug": "backlog-batch-x", "project_id": P, "state": "QUEUED"}
    verdict, _ = classify(
        parent("a", note="backlog-compactor: collapsed into backlog-batch-x"),
        [], [], {(P, "backlog-batch-x"): successor})
    assert verdict == REQUEUE_PARENT


def test_quarantined_successor_is_held_for_review_not_requeued():
    """4,294 rows rode on this distinction — see the constant's comment."""
    for dead_state in ("QUARANTINED", "SUPERSEDED", "CLOSED"):
        successor = {"slug": "b", "project_id": P, "state": dead_state}
        verdict, detail = classify(
            parent("a", note="backlog-compactor: collapsed into b"),
            [], [], {(P, "b"): successor})
        assert verdict == REVIEW_SUCCESSOR_TERMINAL, dead_state
        assert dead_state in detail


def test_review_bucket_is_not_auto_appliable():
    assert REVIEW_SUCCESSOR_TERMINAL not in AUTO_APPLY
    assert LEAVE not in AUTO_APPLY


def test_compactor_successor_that_vanished_requeues_the_parent():
    verdict, detail = classify(
        parent("a", note="backlog-compactor: collapsed into gone"), [], [], {})
    assert verdict == REQUEUE_PARENT
    assert "no such task" in detail


def test_deployed_and_verified_counts_as_shipped():
    """The state the delivery ladder aims at must satisfy a succession."""
    successor = {"slug": "b", "project_id": P, "state": "DEPLOYED_AND_VERIFIED"}
    verdict, _ = classify(
        parent("a", note="backlog-compactor: collapsed into b"),
        [], [], {(P, "b"): successor})
    assert verdict == DONE_BY_SUCCESSION


def test_unlinked_slices_are_relinked_not_closed():
    """auth-gate-audit's real shape: children delivered, FK never written."""
    kids = [child("a-slice-%d" % i, state="DEPLOYED_AND_VERIFIED")
            for i in (1, 2, 3)]
    verdict, detail = classify(
        parent("a", note="auto-sliced-before-agent: spawning 3 sub-subtasks"),
        [], kids, {})
    assert verdict == RELINK
    assert "3 slice(s)" in detail


def test_relink_does_not_itself_mark_the_parent_done():
    """Relinking hands the decision back to _closed_decompositions()."""
    kids = [child("a-slice-1", state="QUEUED")]
    verdict, _ = classify(parent("a"), [], kids, {})
    assert verdict == RELINK


def test_no_evidence_anywhere_requeues_the_parent():
    verdict, detail = classify(
        parent("a", note="recovered from shelf -> split into sub-tasks"),
        [], [], {})
    assert verdict == REQUEUE_PARENT
    assert "never started" in detail


def test_childless_parent_is_never_marked_done_without_evidence():
    """The trap the db.py comment warns about, asserted directly."""
    for note in ("recovered from shelf -> split into sub-tasks",
                 "recovered: restored from batch-orphan quarantine",
                 "auto-sliced-before-agent: spawning 5 sub-subtasks",
                 None):
        verdict, _ = classify(parent("a", note=note), [], [], {})
        assert verdict != DONE_BY_SUCCESSION, note


# --------------------------------------------------------------------------
# build_plan() — whole-queue wiring
# --------------------------------------------------------------------------


def test_build_plan_finds_slug_children_only_within_the_same_project():
    parents = [parent("a")]
    tasks = [child("a-slice-1", pid="other-project")]
    plan = build_plan(parents, tasks)
    assert plan[0]["verdict"] == REQUEUE_PARENT


def test_build_plan_does_not_confuse_a_prefix_neighbour():
    """`a` must not adopt `ab-slice-1`."""
    parents = [parent("a")]
    plan = build_plan(parents, [child("ab-slice-1")])
    assert plan[0]["verdict"] == REQUEUE_PARENT


def test_build_plan_collects_ids_to_relink():
    parents = [parent("a", tid="pid-a")]
    plan = build_plan(parents, [child("a-slice-1"), child("a-slice-2")])
    assert plan[0]["verdict"] == RELINK
    assert set(plan[0]["children"]) == {"id-a-slice-1", "id-a-slice-2"}


# --------------------------------------------------------------------------
# queue_health unsatisfiable-edge detection
# --------------------------------------------------------------------------


def test_terminal_dep_is_unsatisfiable():
    task = {"slug": "t", "project_id": P, "deps": ["d"]}
    dead = unsatisfiable_deps(task, {P: {"d": "SUPERSEDED"}}, {})
    assert dead and "SUPERSEDED" in dead[0][1]


def test_childless_decomposed_dep_is_unsatisfiable():
    task = {"slug": "t", "project_id": P, "deps": ["d"]}
    dead = unsatisfiable_deps(task, {P: {"d": "DECOMPOSED"}}, {P: {"d"}})
    assert dead and "zero children" in dead[0][1]


def test_healthy_decomposed_dep_is_not_unsatisfiable():
    """A parent WITH children resolves normally and must not be flagged."""
    task = {"slug": "t", "project_id": P, "deps": ["d"]}
    assert unsatisfiable_deps(task, {P: {"d": "DECOMPOSED"}}, {P: set()}) == []


def test_dangling_dep_slug_is_unsatisfiable():
    task = {"slug": "t", "project_id": P, "deps": ["nope"]}
    dead = unsatisfiable_deps(task, {P: {}}, {})
    assert dead and "no such task" in dead[0][1]


def test_merely_running_dep_is_blocked_not_unsatisfiable():
    task = {"slug": "t", "project_id": P, "deps": ["d"]}
    assert unsatisfiable_deps(task, {P: {"d": "RUNNING"}}, {}) == []


def test_classify_task_reports_unsatisfiable_over_blocked():
    task = {"slug": "t", "project_id": P, "deps": ["d"], "kind": "build"}
    verdict, detail = classify_task(
        task, {P}, {P: set()}, {P: {"d": "QUARANTINED"}}, {})
    assert verdict == "unsatisfiable"
    assert "QUARANTINED" in detail


def test_classify_task_still_reports_ordinary_blocking():
    task = {"slug": "t", "project_id": P, "deps": ["d"], "kind": "build"}
    verdict, _ = classify_task(task, {P}, {P: set()}, {P: {"d": "RUNNING"}}, {})
    assert verdict == "blocked"


def test_summarize_counts_unsatisfiable_separately():
    tasks = [
        {"slug": "dead", "project_id": P, "deps": ["x"], "kind": "build"},
        {"slug": "waiting", "project_id": P, "deps": ["y"], "kind": "build"},
        {"slug": "ready", "project_id": P, "deps": [], "kind": "build"},
    ]
    report = summarize(tasks, {P}, {P: set()},
                       {P: {"x": "CLOSED", "y": "RUNNING"}}, {})
    assert report["unsatisfiable"] == 1
    assert report["blocked"] == 1
    assert report["claimable"] == 1
    assert report["deadlocked"] is False


def test_summarize_is_backward_compatible_without_the_new_maps():
    """Old two-arg callers keep working and see no unsatisfiable rows."""
    tasks = [{"slug": "t", "project_id": P, "deps": ["d"], "kind": "build"}]
    report = summarize(tasks, {P}, {P: set()})
    assert report["blocked"] == 1
    assert report["unsatisfiable"] == 0
