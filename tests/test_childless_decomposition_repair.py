"""Executable criteria for the childless-decomposition repair.

The defect these cover deadlocked the operator drop-box: all 6 QUEUED dropbox-*
tasks sat at attempt=0 from 2026-08-07 because each waited on a DECOMPOSED
parent with no children, and `runner/db.py::_closed_decompositions()` correctly
refuses to treat such a parent as satisfied. Measured 2026-09-09: 5,015 of 5,316
DECOMPOSED parents were childless.

Every assertion below can fail. Each one pins a decision that, made the other
way, either re-deadlocks the queue or releases dependents of work that does not
exist -- and the second failure is the worse of the two, so the "refuses to"
cases are as load-bearing as the "repairs" ones.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.reconcile_childless_decompositions import (  # noqa: E402
    build_plans, classify, collapse_target, plan_for,
)
from tools.queue_health import (  # noqa: E402
    build_dead_ends, classify_task, summarize,
)


def parent(slug="p", note=None, pid=1, tid=10):
    return {"id": tid, "slug": slug, "note": note, "project_id": pid}


class CollapseNoteParsing(unittest.TestCase):
    def test_reads_the_compactor_target(self):
        self.assertEqual(
            collapse_target("backlog-compactor: collapsed into backlog-batch-tomorrow-b498c9b"),
            "backlog-batch-tomorrow-b498c9b")

    def test_ignores_prose_that_merely_mentions_collapsing(self):
        """A loose pattern would manufacture a target slug out of a hand note.

        That matters because a manufactured target that happened to name a
        finished task would close the parent and release its dependents onto
        work nobody ever did.
        """
        for note in ("collapsed into a heap", "see: collapsed into the batch below",
                     "auto-sliced-before-agent: parent=foo", "", None):
            self.assertIsNone(collapse_target(note), note)


class ClassifyingAChildlessParent(unittest.TestCase):
    def test_slice_named_children_without_the_fk_are_relinked(self):
        kids = [{"id": 2, "slug": "p-slice-1"}, {"id": 3, "slug": "p-slice-2"}]
        disposition, _ = classify(parent(), kids, None)
        self.assertEqual(disposition, "RELINK")

    def test_children_outrank_a_collapse_note(self):
        """A task can be sliced and later collapsed. The children are evidence
        of where the work actually went; the note records only an intent."""
        kids = [{"id": 2, "slug": "p-slice-1"}]
        disposition, _ = classify(
            parent(note="backlog-compactor: collapsed into batch-x"), kids,
            {"slug": "batch-x", "state": "DONE"})
        self.assertEqual(disposition, "RELINK")

    def test_a_landed_collapse_closes_the_parent(self):
        disposition, reason = classify(
            parent(note="backlog-compactor: collapsed into batch-x"), [],
            {"slug": "batch-x", "state": "DONE"})
        self.assertEqual(disposition, "CLOSE_VIA_COLLAPSE")
        self.assertIn("batch-x", reason)

    def test_an_unfinished_collapse_is_left_alone(self):
        """Not broken and not finished. Forcing it either way is wrong."""
        disposition, _ = classify(
            parent(note="backlog-compactor: collapsed into batch-x"), [],
            {"slug": "batch-x", "state": "QUEUED"})
        self.assertEqual(disposition, "DEFER_TO_COLLAPSE")

    def test_a_collapse_into_a_target_that_does_not_exist_requeues_the_parent(self):
        """804 parents in the live queue point at a batch task that was never
        created. The work exists nowhere, so the parent is the only thing left
        that can carry it."""
        disposition, reason = classify(
            parent(note="backlog-compactor: collapsed into batch-ghost"), [], None)
        self.assertEqual(disposition, "REQUEUE")
        self.assertIn("does not exist", reason)

    def test_no_children_and_no_note_requeues(self):
        disposition, _ = classify(parent(), [], None)
        self.assertEqual(disposition, "REQUEUE")


class PlansNeverReleaseDependentsOfWorkThatDoesNotExist(unittest.TestCase):
    def test_requeue_returns_the_parent_and_does_not_mark_it_done(self):
        """The trap the _closed_decompositions() comment warns about.

        Marking a lost parent DONE would satisfy its dependents instantly and
        let them build on work that was never performed. Returning it to QUEUED
        keeps the dependents waiting -- but now on something that can finish.
        """
        plan = plan_for(parent(), [], None)
        self.assertEqual(plan["disposition"], "REQUEUE")
        states = [w["values"].get("state") for w in plan["writes"]]
        self.assertEqual(states, ["QUEUED"])
        self.assertNotIn("DONE", states)

    def test_close_via_collapse_inherits_the_targets_commit_as_provenance(self):
        plan = plan_for(parent(note="backlog-compactor: collapsed into batch-x"), [],
                        {"slug": "batch-x", "state": "DONE", "artifact_commit": "abc1234"})
        write = plan["writes"][0]["values"]
        self.assertEqual(write["state"], "DONE")
        self.assertEqual(write["artifact_commit"], "abc1234")

    def test_closing_without_a_commit_says_so_rather_than_inventing_one(self):
        plan = plan_for(parent(note="backlog-compactor: collapsed into batch-x"), [],
                        {"slug": "batch-x", "state": "DONE"})
        write = plan["writes"][0]["values"]
        self.assertNotIn("artifact_commit", write)
        self.assertIn("NO-ARTIFACT-JUSTIFIED", write["note"])

    def test_relink_writes_the_fk_on_the_children_not_the_parent(self):
        kids = [{"id": 2, "slug": "p-slice-1"}, {"id": 3, "slug": "p-slice-2"}]
        plan = plan_for(parent(tid=10), kids, None)
        self.assertEqual([w["match"]["id"] for w in plan["writes"]], [2, 3])
        self.assertTrue(all(w["values"]["parent_task_id"] == 10 for w in plan["writes"]))

    def test_observations_produce_no_writes(self):
        plan = plan_for(parent(note="backlog-compactor: collapsed into batch-x"), [],
                        {"slug": "batch-x", "state": "RUNNING"})
        self.assertEqual(plan["writes"], [])


class BuildPlansSkipsHealthyParents(unittest.TestCase):
    def test_a_parent_with_real_children_is_not_touched(self):
        parents = [parent(slug="healthy", tid=10)]
        tasks = parents + [{"id": 2, "slug": "healthy-slice-1", "project_id": 1,
                            "parent_task_id": 10, "state": "QUEUED"}]
        self.assertEqual(build_plans(parents, tasks), [])

    def test_a_parent_whose_children_lost_the_fk_is_relinked(self):
        parents = [parent(slug="lost", tid=10)]
        tasks = parents + [{"id": 2, "slug": "lost-slice-1", "project_id": 1,
                            "parent_task_id": None, "state": "QUEUED"}]
        plans = build_plans(parents, tasks)
        self.assertEqual([p["disposition"] for p in plans], ["RELINK"])


class QueueHealthSeparatesBlockedFromUnsatisfiable(unittest.TestCase):
    """Conflating the two is what hid the drop-box deadlock for a month."""

    def test_a_childless_decomposed_parent_is_a_dead_end(self):
        tasks = [{"id": 10, "slug": "p", "state": "DECOMPOSED", "note": None,
                  "project_id": 1, "parent_task_id": None}]
        self.assertIn("p", build_dead_ends(tasks)[1])

    def test_a_decomposed_parent_with_children_is_not_a_dead_end(self):
        tasks = [{"id": 10, "slug": "p", "state": "DECOMPOSED", "note": None,
                  "project_id": 1, "parent_task_id": None},
                 {"id": 11, "slug": "p-slice-1", "state": "QUEUED", "note": None,
                  "project_id": 1, "parent_task_id": 10}]
        self.assertNotIn("p", build_dead_ends(tasks).get(1, {}))

    def test_a_collapse_into_a_live_target_is_not_a_dead_end(self):
        tasks = [{"id": 10, "slug": "p", "state": "DECOMPOSED", "project_id": 1,
                  "parent_task_id": None,
                  "note": "backlog-compactor: collapsed into batch-x"},
                 {"id": 11, "slug": "batch-x", "state": "QUEUED", "note": None,
                  "project_id": 1, "parent_task_id": None}]
        self.assertNotIn("p", build_dead_ends(tasks).get(1, {}))

    def test_a_collapse_into_a_missing_target_is_a_dead_end(self):
        tasks = [{"id": 10, "slug": "p", "state": "DECOMPOSED", "project_id": 1,
                  "parent_task_id": None,
                  "note": "backlog-compactor: collapsed into batch-ghost"}]
        self.assertIn("p", build_dead_ends(tasks)[1])

    def test_a_task_waiting_on_a_dead_end_is_reported_unsatisfiable(self):
        task = {"slug": "dropbox-x-slice-3", "project_id": 1,
                "deps": ["dropbox-x-slice-2"], "kind": "build"}
        dead = {1: {"dropbox-x-slice-2": "DECOMPOSED with no children"}}
        verdict, detail = classify_task(task, {1}, {1: set()}, dead)
        self.assertEqual(verdict, "unsatisfiable")
        self.assertIn("dropbox-x-slice-2", detail)

    def test_a_task_waiting_on_live_work_is_still_only_blocked(self):
        task = {"slug": "b", "project_id": 1, "deps": ["a"], "kind": "build"}
        verdict, _ = classify_task(task, {1}, {1: set()}, {1: {}})
        self.assertEqual(verdict, "blocked")

    def test_deployed_and_verified_satisfies_a_dependency(self):
        """queue_health used to accept only DONE/MERGED while the runner also
        honoured DEPLOYED_AND_VERIFIED, so it invented blocked tasks that the
        claim path would happily have taken."""
        task = {"slug": "b", "project_id": 1, "deps": ["a"], "kind": "build"}
        verdict, _ = classify_task(task, {1}, {1: {"a"}}, {1: {}})
        self.assertEqual(verdict, "claimable")

    def test_summarize_counts_the_new_bucket(self):
        tasks = [{"slug": "b", "project_id": 1, "deps": ["a"], "kind": "build"}]
        report = summarize(tasks, {1}, {1: set()}, {1: {"a": "SUPERSEDED"}})
        self.assertEqual(report["unsatisfiable"], 1)
        self.assertEqual(report["blocked"], 0)


class TheSlicerReportsOrphanedSlices(unittest.TestCase):
    """A slice that lands without parent_task_id makes its parent childless
    forever, which reads as a healthy decomposition. It must be reported."""

    def test_insert_chain_separates_orphans_from_landings(self):
        from runner.task_slicer import _insert_chain

        parts = [{"slug": "s-slice-%d" % i} for i in (1, 2, 3)]

        def insert(row):
            # middle slice loses its parent link, mimicking the ladder's last variant
            return False if row["slug"].endswith("2") else True

        landed, dropped, orphaned = _insert_chain(
            parts, lambda part, deps: {"slug": part["slug"], "deps": deps},
            lambda slug: False, insert)
        self.assertEqual(landed, [p["slug"] for p in parts])
        self.assertEqual(dropped, [])
        self.assertEqual(orphaned, ["s-slice-2"])


if __name__ == "__main__":
    unittest.main()
