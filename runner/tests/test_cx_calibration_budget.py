"""
test_cx_calibration_budget.py - Brier-scored autonomy budget advisories.

The module must write only the advisory owner_model key and an inbox note. It must never write the
live autonomy_budget key owned by committees.tune_budget().
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cx_calibration_budget as cxb
import db


class MockDB(unittest.TestCase):

    def setUp(self):
        self.orig = (db.select, db.insert)
        self.inserts = []

    def tearDown(self):
        db.select, db.insert = self.orig

    def install(self, scoreboard, budget=20):
        def _select(table, params=None):
            if table == "committee_scoreboard":
                return list(scoreboard)
            if table == "owner_model" and params and params.get("key") == "eq.autonomy_budget":
                return [{"value": budget}]
            return []
        db.select = _select
        db.insert = lambda table, row, upsert=False: self.inserts.append((table, row, upsert))

    def advisory_insert(self):
        return next(row for table, row, _ in self.inserts
                    if table == "owner_model" and row.get("key") == cxb.ADVISORY_KEY)

    def note_insert(self):
        return next(row for table, row, _ in self.inserts if table == "approvals")


class TestRun(MockDB):

    def test_good_brier_recommends_increase_without_live_budget_write(self):
        self.install([
            {"committee": "Growth", "brier": 0.10, "calls": 10},
            {"committee": "Risk", "brier": 0.20, "calls": 10},
        ], budget=20)
        result = cxb.run()

        self.assertEqual(result["weighted_brier"], 0.15)
        self.assertEqual(result["adjustment"], 3)
        self.assertEqual(result["recommended_budget"], 23)
        self.assertEqual(self.advisory_insert()["value"], 3)
        self.assertTrue(any(table == "owner_model" and row.get("key") == cxb.ADVISORY_KEY and upsert
                            for table, row, upsert in self.inserts))
        self.assertFalse(any(table == "owner_model" and row.get("key") == cxb.LIVE_BUDGET_KEY
                             for table, row, _ in self.inserts))
        self.assertIn("committees.tune_budget remains the sole writer",
                      self.note_insert()["value"])

    def test_bad_brier_recommends_decrease(self):
        self.install([
            {"committee": "General", "brier": 0.50, "calls": 6},
            {"committee": "Security", "brier": 0.35, "calls": 4},
        ], budget=12)
        result = cxb.run()

        self.assertEqual(result["weighted_brier"], 0.44)
        self.assertEqual(result["adjustment"], -4)
        self.assertEqual(result["recommended_budget"], 8)
        self.assertIn("under-calibrated", self.note_insert()["why"])

    def test_missing_brier_scores_write_neutral_advisory(self):
        self.install([
            {"committee": "NoBrier", "brier": None, "calls": 10},
            {"committee": "NoCalls", "brier": 0.1, "calls": 0},
        ], budget=20)
        result = cxb.run()

        self.assertIsNone(result["weighted_brier"])
        self.assertEqual(result["calls"], 0)
        self.assertEqual(result["adjustment"], 0)
        self.assertEqual(result["recommended_budget"], 20)
        self.assertEqual(self.advisory_insert()["value"], 0)

    def test_empty_scoreboard_is_neutral(self):
        self.install([], budget=20)
        result = cxb.run()

        self.assertEqual(result["committees"], 0)
        self.assertEqual(result["adjustment"], 0)
        self.assertEqual(result["recommended_budget"], 20)

    def test_extreme_values_are_clamped_and_budget_is_bounded(self):
        self.install([
            {"committee": "ImpossibleLow", "brier": -10, "calls": 1},
            {"committee": "ImpossibleHigh", "brier": 2, "calls": 9},
        ], budget=7)
        result = cxb.run()

        self.assertEqual(result["weighted_brier"], 0.9)
        self.assertEqual(result["adjustment"], -4)
        self.assertEqual(result["recommended_budget"], cxb.MIN_BUDGET)


class TestPureHelpers(unittest.TestCase):

    def test_adjustment_bands(self):
        self.assertEqual(cxb._adjustment_for_brier(0.12), 5)
        self.assertEqual(cxb._adjustment_for_brier(0.18), 3)
        self.assertEqual(cxb._adjustment_for_brier(0.25), 1)
        self.assertEqual(cxb._adjustment_for_brier(0.30), 0)
        self.assertEqual(cxb._adjustment_for_brier(0.40), -2)
        self.assertEqual(cxb._adjustment_for_brier(0.41), -4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
