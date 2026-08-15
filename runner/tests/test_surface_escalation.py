#!/usr/bin/env python3
"""Acceptance tests for surface escalation in improvement_miner.

improvement_measure writes measured per-surface returns to surface_returns. Before this, the miner only
re-WEIGHTED those surfaces (surf_boost on already-mined ideas), so a surface that was demonstrably paying
off still waited its turn in the round-robin and got no extra slots. These tests pin the stronger
contract: crossing ORCH_SURFACE_ESCALATE_THRESHOLD must (a) pin the surface into the rotation and
(b) spawn deeper exploration tasks through the existing intake path.

Everything here is offline — the queue collaborators are injected, so no database is touched.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import improvement_miner as im

HOT = "reliability"          # a real member of im.SURFACES
COLD = "frontend"


class EscalatingSurfacesTest(unittest.TestCase):
    """Threshold behavior, ordering, and refusal to trust bad rows."""

    def test_high_return_surface_escalates(self):
        self.assertIn(HOT, im.escalating_surfaces({HOT: 5.0}, threshold=0.25))

    def test_low_return_surface_does_not_escalate(self):
        self.assertEqual(im.escalating_surfaces({COLD: 0.01}, threshold=0.25), [])

    def test_threshold_is_strict(self):
        self.assertEqual(im.escalating_surfaces({HOT: 0.25}, threshold=0.25), [])
        self.assertIn(HOT, im.escalating_surfaces({HOT: 0.26}, threshold=0.25))

    def test_best_surface_comes_first(self):
        got = im.escalating_surfaces({COLD: 1.0, HOT: 9.0}, threshold=0.25)
        self.assertEqual(got[0], HOT)

    def test_unknown_surface_cannot_inject_itself(self):
        # A stale/mistyped surface_returns row must not put an arbitrary name into the rotation.
        self.assertEqual(im.escalating_surfaces({"not-a-real-surface": 99.0}, threshold=0.25), [])

    def test_bad_data_is_a_noop_not_a_crash(self):
        self.assertEqual(im.escalating_surfaces({HOT: "not-a-number"}, threshold=0.25), [])
        self.assertEqual(im.escalating_surfaces({HOT: None}, threshold=0.25), [])
        self.assertEqual(im.escalating_surfaces({}, threshold=0.25), [])
        self.assertEqual(im.escalating_surfaces(None, threshold=0.25), [])
        self.assertEqual(im.escalating_surfaces("garbage", threshold=0.25), [])

    def test_limit_caps_the_escalation_set(self):
        rets = {s: 9.0 for s in im.SURFACES[:6]}
        self.assertEqual(len(im.escalating_surfaces(rets, threshold=0.25, limit=2)), 2)


class EscalationPairsTest(unittest.TestCase):
    """The budget/frequency raise: escalated surfaces get pinned rotation slots."""

    def test_escalated_surface_is_pinned_for_each_app(self):
        pairs = im.escalation_pairs(["apparently"], [HOT])
        self.assertIn(("apparently", HOT), pairs)

    def test_no_escalation_means_no_pinned_pairs(self):
        self.assertEqual(im.escalation_pairs(["apparently"], []), [])
        self.assertEqual(im.escalation_pairs([], [HOT]), [])
        self.assertEqual(im.escalation_pairs(None, None), [])

    def test_cap_is_honoured_so_rotation_is_never_starved(self):
        pairs = im.escalation_pairs(["a", "b", "c"], im.SURFACES[:5], cap=3)
        self.assertEqual(len(pairs), 3)

    def test_pairs_are_unique(self):
        pairs = im.escalation_pairs(["a", "a"], [HOT, HOT], cap=10)
        self.assertEqual(len(pairs), len(set(pairs)))


class ExplorationRecordsTest(unittest.TestCase):
    """Deeper exploration tasks are well-formed before anything is queued."""

    def test_depth_controls_how_many_are_spawned(self):
        rows = im.exploration_records("apparently", [HOT], "proj-1", depth=3)
        self.assertEqual(len(rows), 3)

    def test_records_are_queued_build_tasks_naming_the_surface(self):
        row = im.exploration_records("apparently", [HOT], "proj-1", depth=1)[0]
        self.assertEqual(row["state"], "QUEUED")
        self.assertEqual(row["project_id"], "proj-1")
        self.assertIn(HOT, row["slug"])
        self.assertIn(HOT, row["prompt"])

    def test_slug_stays_within_column_budget(self):
        for row in im.exploration_records("a-very-long-application-name-here", im.SURFACES, "p", depth=2):
            self.assertLessEqual(len(row["slug"]), 60)

    def test_missing_project_or_app_yields_nothing(self):
        self.assertEqual(im.exploration_records("apparently", [HOT], None), [])
        self.assertEqual(im.exploration_records(None, [HOT], "proj-1"), [])
        self.assertEqual(im.exploration_records("apparently", [], "proj-1"), [])


class QueueExplorationTasksTest(unittest.TestCase):
    """ACCEPTANCE: a fixture high-return surface actually spawns deeper exploration tasks."""

    def setUp(self):
        self.inserted = []

    def _sink(self, existing=None):
        """Injected enqueue collaborators; `existing` simulates an already-open matching task."""
        return {
            "find_open_by_intent": lambda key: existing,
            "insert": lambda record, key: self.inserted.append(record) or f"id-{len(self.inserted)}",
            "bump": lambda row: self.bumped.append(row),
        }

    def test_high_return_surface_spawns_exploration_tasks(self):
        hot = im.escalating_surfaces({HOT: 7.5}, threshold=0.25)
        self.assertTrue(hot, "fixture surface should have escalated")
        self.bumped = []
        tally = im.queue_exploration_tasks("apparently", hot, "proj-1", depth=2, **self._sink())
        self.assertEqual(tally["created"], 2)
        self.assertEqual(len(self.inserted), 2)
        self.assertTrue(all(HOT in r["slug"] for r in self.inserted))

    def test_below_threshold_surface_spawns_nothing(self):
        cold = im.escalating_surfaces({COLD: 0.01}, threshold=0.25)
        self.bumped = []
        tally = im.queue_exploration_tasks("apparently", cold, "proj-1", depth=2, **self._sink())
        self.assertEqual(tally, {"created": 0, "coalesced": 0})
        self.assertEqual(self.inserted, [])

    def test_repeat_escalation_coalesces_instead_of_duplicating(self):
        # The hot surface stays hot every hour; escalation must bump the open task, not mint a new one.
        self.bumped = []
        tally = im.queue_exploration_tasks("apparently", [HOT], "proj-1", depth=2,
                                           **self._sink(existing={"id": "existing-1", "attempt": 0}))
        self.assertEqual(tally["created"], 0)
        self.assertEqual(tally["coalesced"], 2)
        self.assertEqual(self.inserted, [])
        self.assertEqual(len(self.bumped), 2)

    def test_failing_sink_is_swallowed(self):
        def boom(*a, **k):
            raise RuntimeError("db down")
        tally = im.queue_exploration_tasks("apparently", [HOT], "proj-1", depth=2,
                                           find_open_by_intent=boom, insert=boom, bump=boom)
        self.assertEqual(tally, {"created": 0, "coalesced": 0})


class ContractsPreservedTest(unittest.TestCase):
    """Escalation is additive; the miner's existing surface contracts must be intact."""

    def test_threshold_contract_is_exported(self):
        self.assertIsInstance(im.ORCH_SURFACE_ESCALATE_THRESHOLD, float)

    def test_existing_entrypoints_survive(self):
        for fn in ("run", "run_measured", "run_template", "_next_pairs", "_mine", "_draft_slots"):
            self.assertTrue(callable(getattr(im, fn, None)), f"{fn} missing or not callable")

    def test_surface_catalogue_unchanged(self):
        self.assertIn(HOT, im.SURFACES)
        self.assertIn(COLD, im.SURFACES)


if __name__ == "__main__":
    unittest.main()
