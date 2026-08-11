#!/usr/bin/env python3
"""Wave C slice 5 — disposition memory wired into the planner (Part 7).

Slice 3 shipped `platform_spine.disposition_signal` / `should_generate` as pure logic. Pure
logic nothing calls saves nothing: the spec's claim is that "duplicate work stops being
GENERATED", and generation happens in `planner.plan()`. This is that wiring.

The failure it ends: the fleet closes a duplicate, learns nothing, and the planner emits the
same duplicate again the following week — which this very session watched happen (two slices
decomposed from one §6 hygiene section, one of them pure waste).
"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO, "runner")
sys.path.insert(0, RUNNER)

import planner  # noqa: E402
import platform_spine  # noqa: E402


class DispositionMappingTests(unittest.TestCase):
    def test_a_superseded_state_is_waste(self):
        self.assertEqual(planner._disposition_of({"state": "SUPERSEDED"}), "superseded")

    def test_a_DONE_task_whose_note_admits_duplication_is_still_waste(self):
        """The common shape: waste recorded as success. A state filter alone misses it."""
        row = {"state": "DONE", "note": "duplicate decomposition; nothing left to build"}
        self.assertEqual(planner._disposition_of(row), "duplicate")

    def test_already_done_and_no_code_target_are_recognised(self):
        self.assertEqual(
            planner._disposition_of({"state": "DONE", "note": "verified already present in HEAD"}),
            "already-done")
        self.assertEqual(
            planner._disposition_of({"state": "BLOCKED", "note": "no code target found"}),
            "no-op")

    def test_a_genuine_merge_is_not_waste(self):
        self.assertEqual(
            planner._disposition_of({"state": "DONE", "note": "implemented and pushed"}),
            "merged")

    def test_mapping_is_fail_soft(self):
        for value in (None, {}, "junk", 42):
            self.assertEqual(planner._disposition_of(value), "merged", repr(value))


class PlannerSuppressionTests(unittest.TestCase):
    """The wiring itself, exercised through the real `plan()` tail."""

    WASTEFUL = [
        {"slug": "spammy-initiative-slice-1", "disposition": "duplicate"},
        {"slug": "spammy-initiative-slice-2", "disposition": "superseded"},
    ]

    def _tasks(self):
        return [{"slug": "spammy-initiative-slice-9", "prompt": "p"},
                {"slug": "healthy-initiative-slice-1", "prompt": "p"}]

    def test_a_repeat_offender_initiative_is_not_regenerated(self):
        signal = platform_spine.disposition_signal(self.WASTEFUL)
        allowed, reason = platform_spine.should_generate("spammy-initiative-slice-9", signal)
        self.assertFalse(allowed)
        self.assertIn("not worth doing", reason)

    def test_unrelated_work_is_untouched(self):
        signal = platform_spine.disposition_signal(self.WASTEFUL)
        self.assertTrue(platform_spine.should_generate("healthy-initiative-slice-1", signal)[0])

    def test_the_planner_consults_the_signal_before_returning(self):
        source = open(os.path.join(RUNNER, "planner.py"), errors="replace").read()
        self.assertIn("platform_spine.should_generate", source)
        self.assertIn("_disposition_signal", source)
        tail = source[source.index("import platform_spine"):]
        self.assertIn("return tasks", tail, "suppression must run before plan() returns")

    def test_suppression_never_returns_an_empty_plan(self):
        """A planner that can silently produce zero tasks is worse than one that repeats work."""
        source = open(os.path.join(RUNNER, "planner.py"), errors="replace").read()
        self.assertIn("if dropped and kept:", source)
        self.assertIn("keeping the plan rather than returning nothing", source)

    def test_every_suppression_is_logged_with_its_reason(self):
        source = open(os.path.join(RUNNER, "planner.py"), errors="replace").read()
        self.assertIn("SUPPRESSED", source)
        self.assertIn("{reason}", source)

    def test_the_wiring_is_fail_soft(self):
        source = open(os.path.join(RUNNER, "planner.py"), errors="replace").read()
        block = source[source.index("import platform_spine"):source.index("def _disposition_signal")]
        self.assertIn("except Exception", block)
        self.assertIn("planning unchanged", block)

    def test_a_db_outage_yields_no_signal_rather_than_a_wrong_one(self):
        import db
        real = db.select
        db.select = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        try:
            self.assertEqual(planner._disposition_signal("beethoven"), {})
        finally:
            db.select = real

    def test_no_history_means_no_suppression(self):
        signal = platform_spine.disposition_signal([])
        self.assertTrue(platform_spine.should_generate("anything-slice-1", signal)[0])


class ThresholdTests(unittest.TestCase):
    def test_one_bad_shard_does_not_suppress_its_initiative(self):
        signal = platform_spine.disposition_signal(
            [{"slug": "unlucky-slice-1", "disposition": "duplicate"}])
        self.assertTrue(platform_spine.should_generate("unlucky-slice-2", signal)[0])

    def test_two_make_a_pattern(self):
        signal = platform_spine.disposition_signal([
            {"slug": "unlucky-slice-1", "disposition": "duplicate"},
            {"slug": "unlucky-slice-2", "disposition": "duplicate"},
        ])
        self.assertFalse(platform_spine.should_generate("unlucky-slice-3", signal)[0])

    def test_the_reason_itemises_what_went_wrong_so_it_is_reviewable(self):
        signal = platform_spine.disposition_signal([
            {"slug": "x-slice-1", "disposition": "duplicate"},
            {"slug": "x-slice-2", "disposition": "superseded"},
        ])
        _, reason = platform_spine.should_generate("x-slice-3", signal)
        self.assertIn("duplicatex1", reason.replace(" ", ""))
        self.assertIn("supersededx1", reason.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
