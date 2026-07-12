"""
test_cade_scorecard.py - Tests for CADE fleet scorecard pure aggregator.
Covers normalization, weakest-app selection, tie-breaks, and empty input.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cade_scorecard


class TestNormalizeKpi(unittest.TestCase):
    def test_clamp_low(self):
        self.assertEqual(cade_scorecard.normalize_kpi(-0.5), 0.0)
    def test_clamp_high(self):
        self.assertEqual(cade_scorecard.normalize_kpi(1.5), 1.0)
    def test_midpoint(self):
        self.assertAlmostEqual(cade_scorecard.normalize_kpi(0.5), 0.5)
    def test_none(self):
        self.assertEqual(cade_scorecard.normalize_kpi(None), 0.0)
    def test_equal_floor_ceiling(self):
        self.assertEqual(cade_scorecard.normalize_kpi(1.0, floor=1.0, ceiling=1.0), 1.0)
        self.assertEqual(cade_scorecard.normalize_kpi(0.5, floor=1.0, ceiling=1.0), 0.0)


class TestScoreApp(unittest.TestCase):
    def test_perfect_scores(self):
        kpis = {"win_rate_lift": 1.0, "calibration_gap": 0.0,
                "alignment_recall": 1.0, "alignment_surprise": 0.0,
                "override_failure": 0.0}
        self.assertAlmostEqual(cade_scorecard.score_app(kpis), 1.0)
    def test_worst_scores(self):
        kpis = {"win_rate_lift": 0.0, "calibration_gap": 1.0,
                "alignment_recall": 0.0, "alignment_surprise": 1.0,
                "override_failure": 1.0}
        self.assertAlmostEqual(cade_scorecard.score_app(kpis), 0.0)
    def test_empty(self):
        self.assertEqual(cade_scorecard.score_app({}), 0.0)
    def test_none(self):
        self.assertEqual(cade_scorecard.score_app(None), 0.0)
    def test_partial_kpis(self):
        kpis = {"win_rate_lift": 0.8}
        score = cade_scorecard.score_app(kpis)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)


class TestFleetScorecard(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(cade_scorecard.fleet_scorecard({}), [])
    def test_sorted_weakest_first(self):
        apps = {
            "strong": {"win_rate_lift": 0.9, "calibration_gap": 0.1,
                       "alignment_recall": 0.9, "alignment_surprise": 0.1,
                       "override_failure": 0.1},
            "weak":   {"win_rate_lift": 0.1, "calibration_gap": 0.9,
                       "alignment_recall": 0.1, "alignment_surprise": 0.9,
                       "override_failure": 0.9},
        }
        sc = cade_scorecard.fleet_scorecard(apps)
        self.assertEqual(len(sc), 2)
        self.assertEqual(sc[0]["app"], "weak")
        self.assertEqual(sc[1]["app"], "strong")
        self.assertLess(sc[0]["score"], sc[1]["score"])
    def test_preserves_kpis(self):
        apps = {"a": {"win_rate_lift": 0.5}}
        sc = cade_scorecard.fleet_scorecard(apps)
        self.assertEqual(sc[0]["kpis"]["win_rate_lift"], 0.5)


class TestWeakestApp(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(cade_scorecard.weakest_app({}))
    def test_identifies_weakest(self):
        apps = {
            "good": {"win_rate_lift": 0.9, "calibration_gap": 0.1,
                     "alignment_recall": 0.9, "alignment_surprise": 0.1,
                     "override_failure": 0.1},
            "bad":  {"win_rate_lift": 0.1, "calibration_gap": 0.9,
                     "alignment_recall": 0.1, "alignment_surprise": 0.9,
                     "override_failure": 0.9},
        }
        result = cade_scorecard.weakest_app(apps)
        self.assertEqual(result["app"], "bad")
        self.assertIn("recommended_next_capability", result)
    def test_tiebreak_alphabetical(self):
        kpis = {"win_rate_lift": 0.5, "calibration_gap": 0.5,
                "alignment_recall": 0.5, "alignment_surprise": 0.5,
                "override_failure": 0.5}
        apps = {"beta": kpis, "alpha": kpis}
        result = cade_scorecard.weakest_app(apps)
        self.assertEqual(result["app"], "alpha")
    def test_missing_kpis_worst_gap(self):
        apps = {"app1": {"win_rate_lift": 0.8}}
        result = cade_scorecard.weakest_app(apps)
        self.assertIsNotNone(result)
        self.assertIn("gap", result)
    def test_recommends_capability(self):
        apps = {"app1": {"win_rate_lift": 0.1, "calibration_gap": 0.0,
                         "alignment_recall": 0.9, "alignment_surprise": 0.0,
                         "override_failure": 0.0}}
        result = cade_scorecard.weakest_app(apps)
        self.assertEqual(result["recommended_next_capability"], "ab_experimentation")
    def test_single_app(self):
        apps = {"only": {"win_rate_lift": 0.5}}
        result = cade_scorecard.weakest_app(apps)
        self.assertEqual(result["app"], "only")


if __name__ == "__main__":
    unittest.main()
