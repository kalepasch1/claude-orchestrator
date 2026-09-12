"""An improvement that cannot be measured is a change, not an improvement.

Measured 2026-09-01 against the live fleet database:

    month     proposals   falsifiable
    2026-07         814             0
    2026-08         189            52

814 proposals carried no metric_query, baseline_value, comparator or required_margin.
improvement_verify.evaluate() re-runs metric_query and compares against baseline using
comparator and required_margin -- with none of them present there is no verdict to
reach, so 'did this help?' is permanently unanswerable for every one of them. Their
code merged anyway. Across all 1003 proposals, exactly ONE has ever been 'validated'.

queue() now refuses a proposal that could never be proved wrong.
"""
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)
import improvement_ledger as il  # noqa: E402

FALSIFIABLE = {
    "app": "tomorrow", "surface": "merge", "title": "Cut merge-train cycle time",
    "bottleneck_key": "merge_cycle", "metric_query": "select avg(x) from stage_metrics",
    "baseline_value": 100.0, "target_value": 60.0, "comparator": "lt",
    "required_margin": 1.2, "predicted_multiplier": 1.6,
}
# The exact shape of all 814 July rows.
UNFALSIFIABLE = {
    "app": "beethoven", "surface": "queue", "bottleneck_key": "queue",
    "title": "Implement Real-Time Queue Monitoring and Alerts",
}


class FalsifiabilityTests(unittest.TestCase):
    def setUp(self):
        self.inserted = []
        self._insert, self._dup, self._slug = il.db.insert, il.is_duplicate, il.make_slug
        il.db.insert = lambda table, row: self.inserted.append(row)
        il.is_duplicate = lambda row: {"duplicate": False}
        # make_slug queries existing slugs; this suite is about the falsifiability
        # check, which runs before it.
        il.make_slug = lambda title, key, existing=None: "improve-stub-slug"

    def tearDown(self):
        il.db.insert, il.is_duplicate, il.make_slug = self._insert, self._dup, self._slug
        os.environ.pop("ORCH_IMPROVE_REQUIRE_PREDICTION", None)

    def test_the_814_shape_is_refused(self):
        self.assertIsNone(il.queue(dict(UNFALSIFIABLE)))
        self.assertEqual(self.inserted, [], "an unmeasurable proposal was queued")

    def test_a_real_prediction_is_queued(self):
        out = il.queue(dict(FALSIFIABLE))
        self.assertIsNotNone(out)
        self.assertEqual(len(self.inserted), 1)
        self.assertTrue(self.inserted[0].get("task_slug"), "slug should be allocated")

    def test_every_field_is_load_bearing(self):
        for drop in ("metric_query", "comparator", "baseline_value", "required_margin"):
            row = dict(FALSIFIABLE)
            row[drop] = None
            self.inserted.clear()
            self.assertIsNone(il.queue(row), f"dropping {drop} should make it unfalsifiable")
            self.assertEqual(self.inserted, [], drop)

    def test_blank_strings_do_not_count(self):
        for drop in ("metric_query", "comparator"):
            row = dict(FALSIFIABLE)
            row[drop] = "   "
            self.assertIsNone(il.queue(row), drop)

    def test_zero_baseline_is_still_a_baseline(self):
        """0.0 is falsy in Python but a legitimate baseline — must not be rejected."""
        row = dict(FALSIFIABLE, baseline_value=0.0)
        self.assertIsNotNone(il.queue(row), "a zero baseline was wrongly treated as missing")

    def test_is_falsifiable_is_directly_testable(self):
        self.assertTrue(il.is_falsifiable(FALSIFIABLE))
        self.assertFalse(il.is_falsifiable(UNFALSIFIABLE))

    def test_requirement_is_on_by_default(self):
        self.assertTrue(il.REQUIRE_PREDICTION)

    def test_flag_restores_old_behaviour(self):
        os.environ["ORCH_IMPROVE_REQUIRE_PREDICTION"] = "false"
        import importlib
        il2 = importlib.reload(il)
        il2.db.insert = lambda table, row: self.inserted.append(row)
        il2.is_duplicate = lambda row: {"duplicate": False}
        il2.make_slug = lambda title, key, existing=None: "improve-stub-slug"
        try:
            self.assertIsNotNone(il2.queue(dict(UNFALSIFIABLE)))
            self.assertEqual(len(self.inserted), 1)
        finally:
            os.environ.pop("ORCH_IMPROVE_REQUIRE_PREDICTION", None)
            importlib.reload(il)

    def test_dedupe_still_runs_for_valid_proposals(self):
        il.is_duplicate = lambda row: {"duplicate": True, "why": "semantic", "of": "x", "status": "merged"}
        self.assertIsNone(il.queue(dict(FALSIFIABLE)))
        self.assertEqual(self.inserted, [])


if __name__ == "__main__":
    unittest.main()
