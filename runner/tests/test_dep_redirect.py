#!/usr/bin/env python3
"""Repointing collapsed dependency edges.

queue_deadlock_report is read-only because three of its four categories need a
human. The fourth does not: `collapsed` means the backlog compactor folded a
task into a batch and wrote the target in the note. The work exists under
another name and the edge points at the old one — a clerical error with the
answer printed next to it.

The tests that matter are the refusals. A tool that rewrites dependency edges
can quietly make a queue look healthy while leaving it just as stuck, so every
case where redirecting would swap one unsatisfiable edge for another, invent a
self-dependency, or rewrite the history of a task that is no longer waiting is
pinned here.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dep_redirect  # noqa: E402
import queue_deadlock_report as qdr  # noqa: E402


def task(tid, slug, state="QUEUED", deps=None, note="", parent=None):
    return {
        "id": tid, "slug": slug, "state": state, "deps": deps or [],
        "note": note, "parent_task_id": parent, "project_id": "p1",
        "created_at": "2026-08-01T00:00:00+00:00",
    }


def collapsed(tid, slug, into):
    """A DECOMPOSED task with no children whose note names where the work went."""
    return task(tid, slug, state="DECOMPOSED",
                note="backlog-compactor: %s%s" % (qdr.COLLAPSE_MARKER, into))


def plan_for(tasks):
    """Run the planner over an in-memory task list."""
    with patch.object(qdr.db, "select_all", return_value=list(tasks)):
        index = qdr._index()
    return dep_redirect.plan_redirects(*index)


class TestTheClericalCaseIsFixed:
    def test_a_collapsed_edge_is_repointed_at_the_batch(self):
        tasks = [
            task("1", "waiter", deps=["old-work"]),
            collapsed("2", "old-work", "batch-7"),
            task("3", "batch-7"),
        ]
        plan = plan_for(tasks)
        assert len(plan) == 1
        assert plan[0]["deps_after"] == ["batch-7"]
        assert plan[0]["redirects"] == [("old-work", "batch-7")]

    def test_other_deps_on_the_same_task_are_left_alone(self):
        tasks = [
            task("1", "waiter", deps=["still-running", "old-work"]),
            task("2", "still-running", state="QUEUED"),
            collapsed("3", "old-work", "batch-7"),
            task("4", "batch-7"),
        ]
        plan = plan_for(tasks)
        assert plan[0]["deps_after"] == ["still-running", "batch-7"]

    def test_a_qualified_cross_project_dep_resolves_on_the_bare_slug(self):
        tasks = [
            task("1", "waiter", deps=["beethoven:old-work"]),
            collapsed("2", "old-work", "batch-7"),
            task("3", "batch-7"),
        ]
        plan = plan_for(tasks)
        assert plan[0]["deps_after"] == ["batch-7"]

    def test_a_duplicate_edge_collapses_instead_of_doubling(self):
        # The task already waits on the batch; the stale edge is dropped, not
        # added a second time.
        tasks = [
            task("1", "waiter", deps=["batch-7", "old-work"]),
            collapsed("2", "old-work", "batch-7"),
            task("3", "batch-7"),
        ]
        plan = plan_for(tasks)
        assert plan[0]["deps_after"] == ["batch-7"]

    def test_running_twice_is_a_no_op(self):
        tasks = [
            task("1", "waiter", deps=["batch-7"]),
            collapsed("2", "old-work", "batch-7"),
            task("3", "batch-7"),
        ]
        assert plan_for(tasks) == []


class TestTheRefusals:
    def test_a_target_that_never_existed_is_not_repointed(self):
        # Swapping one unsatisfiable edge for another makes the report look
        # better and the queue no less stuck.
        tasks = [
            task("1", "waiter", deps=["old-work"]),
            collapsed("2", "old-work", "batch-that-never-was"),
        ]
        assert plan_for(tasks) == []

    def test_a_self_dependency_is_never_created(self):
        # A compactor that folded a task into its own dependent is a bug to
        # expose, not to paper over with a permanently unsatisfiable edge.
        tasks = [
            task("1", "waiter", deps=["old-work"]),
            collapsed("2", "old-work", "waiter"),
        ]
        assert plan_for(tasks) == []

    def test_a_task_that_is_not_queued_is_left_alone(self):
        # A RUNNING or finished task's deps are history.
        for state in ("RUNNING", "DONE", "MERGED", "QUARANTINED", "DECOMPOSED"):
            tasks = [
                task("1", "waiter", state=state, deps=["old-work"]),
                collapsed("2", "old-work", "batch-7"),
                task("3", "batch-7"),
            ]
            assert plan_for(tasks) == [], state

    def test_the_other_three_categories_are_untouched(self):
        tasks = [
            # dangling
            task("1", "w1", deps=["never-existed"]),
            # terminal
            task("2", "w2", deps=["abandoned"]),
            task("3", "abandoned", state="QUARANTINED"),
            # decomposed-childless
            task("4", "w3", deps=["lost"]),
            task("5", "lost", state="DECOMPOSED"),
        ]
        assert plan_for(tasks) == []

    def test_a_satisfied_dep_is_not_rewritten(self):
        tasks = [
            task("1", "waiter", deps=["finished"]),
            task("2", "finished", state="MERGED"),
        ]
        assert plan_for(tasks) == []

    def test_a_decomposed_dep_with_live_children_is_a_legitimate_wait(self):
        tasks = [
            task("1", "waiter", deps=["parent"]),
            collapsed("2", "parent", "batch-7"),
            task("3", "child", state="QUEUED", parent="2"),
            task("4", "batch-7"),
        ]
        # Children exist, so the dep is waiting rather than collapsed.
        assert plan_for(tasks) == []


class TestApplyIsDryByDefault:
    def test_a_dry_run_writes_nothing(self):
        plan = [{"task_id": "1", "slug": "waiter", "redirects": [],
                 "deps_before": ["a"], "deps_after": ["b"]}]
        with patch.object(dep_redirect.db, "update") as upd:
            result = dep_redirect.apply_plan(plan, write=False)
        upd.assert_not_called()
        assert result == {"applied": 0, "failed": 0}

    def test_apply_writes_exactly_the_planned_deps(self):
        plan = [{"task_id": "1", "slug": "waiter", "redirects": [],
                 "deps_before": ["a"], "deps_after": ["b"]}]
        with patch.object(dep_redirect.db, "update") as upd:
            result = dep_redirect.apply_plan(plan, write=True)
        upd.assert_called_once_with("tasks", {"id": "1"}, {"deps": ["b"]})
        assert result == {"applied": 1, "failed": 0}

    def test_one_failed_row_does_not_abort_the_rest(self):
        plan = [
            {"task_id": "1", "slug": "a", "redirects": [], "deps_before": [], "deps_after": ["x"]},
            {"task_id": "2", "slug": "b", "redirects": [], "deps_before": [], "deps_after": ["y"]},
        ]
        calls = []

        def flaky(table, match, patch_body):
            calls.append(match["id"])
            if match["id"] == "1":
                raise RuntimeError("conflict")
            return True

        with patch.object(dep_redirect.db, "update", side_effect=flaky):
            result = dep_redirect.apply_plan(plan, write=True)
        assert calls == ["1", "2"]
        assert result == {"applied": 1, "failed": 1}


class TestCollapsedTargetParsing:
    def test_trailing_punctuation_is_stripped(self):
        row = {"note": "compactor: %sbatch-7." % qdr.COLLAPSE_MARKER}
        assert dep_redirect.collapsed_target(row) == "batch-7"

    def test_extra_prose_after_the_slug_is_ignored(self):
        row = {"note": "compactor: %sbatch-7 (3 tasks folded)" % qdr.COLLAPSE_MARKER}
        assert dep_redirect.collapsed_target(row) == "batch-7"

    def test_a_note_without_the_marker_yields_none(self):
        assert dep_redirect.collapsed_target({"note": "parked for review"}) is None
        assert dep_redirect.collapsed_target({"note": ""}) is None
        assert dep_redirect.collapsed_target(None) is None

    def test_a_marker_with_nothing_after_it_yields_none(self):
        row = {"note": "compactor: %s" % qdr.COLLAPSE_MARKER}
        assert dep_redirect.collapsed_target(row) is None
