"""
test_cade_scorecard.py - Tests for CADE fleet scorecard aggregation.

Covers normalization, composite scoring, weakest-app selection,
tie-breaks, and empty input.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cade_scorecard as cs


# ── sample telemetry ────────────────────────────────────────────
STRONG_APP = {
    "win_rate_lift": 0.45,
    "calibration_gap": 0.05,
    "alignment_recall": 0.92,
    "alignment_surprise": 0.03,
    "override_failure_rate": 0.02,
}

WEAK_APP = {
    "win_rate_lift": 0.08,
    "calibration_gap": 0.40,
    "alignment_recall": 0.50,
    "alignment_surprise": 0.35,
    "override_failure_rate": 0.25,
}

MEDIUM_APP = {
    "win_rate_lift": 0.20,
    "calibration_gap": 0.15,
    "alignment_recall": 0.75,
    "alignment_surprise": 0.10,
    "override_failure_rate": 0.10,
}


class TestNormalization(unittest.TestCase):

    def test_win_rate_lift(self):
        self.assertAlmostEqual(cs.normalize_dimension("win_rate_lift", 0.50), 50.0)

    def test_calibration_gap_perfect(self):
        self.assertAlmostEqual(cs.normalize_dimension("calibration_gap", 0.0), 100.0)

    def test_calibration_gap_bad(self):
        self.assertAlmostEqual(cs.normalize_dimension("calibration_gap", 1.0), 0.0)

    def test_alignment_recall(self):
        self.assertAlmostEqual(cs.normalize_dimension("alignment_recall", 0.80), 80.0)

    def test_surprise_low_is_good(self):
        self.assertAlmostEqual(cs.normalize_dimension("alignment_surprise", 0.10), 90.0)

    def test_override_failure_low_is_good(self):
        self.assertAlmostEqual(cs.normalize_dimension("override_failure_rate", 0.0), 100.0)

    def test_clamp_high(self):
        self.assertAlmostEqual(cs.normalize_dimension("win_rate_lift", 2.0), 100.0)

    def test_clamp_low(self):
        self.assertAlmostEqual(cs.normalize_dimension("calibration_gap", 1.5), 0.0)


class TestScoreApp(unittest.TestCase):

    def test_composite_in_range(self):
        result = cs.score_app(STRONG_APP)
        self.assertGreaterEqual(result["composite"], 0)
        self.assertLessEqual(result["composite"], 100)

    def test_strong_beats_weak(self):
        strong = cs.score_app(STRONG_APP)
        weak = cs.score_app(WEAK_APP)
        self.assertGreater(strong["composite"], weak["composite"])

    def test_all_dimensions_present(self):
        result = cs.score_app(STRONG_APP)
        for dim in cs.DIMENSION_WEIGHTS:
            self.assertIn(dim, result["dimensions"])

    def test_weakest_dimension_exists(self):
        result = cs.score_app(WEAK_APP)
        self.assertIn(result["weakest_dimension"], cs.DIMENSION_WEIGHTS)

    def test_missing_dims_default_zero(self):
        result = cs.score_app({"win_rate_lift": 0.5})
        self.assertIn("calibration_gap", result["dimensions"])


class TestFleetScorecard(unittest.TestCase):

    def test_empty_input(self):
        result = cs.fleet_scorecard({})
        self.assertIsNone(result["weakest_app"])
        self.assertIsNone(result["recommended_next_capability"])
        self.assertEqual(result["apps"], {})

    def test_weakest_app_selection(self):
        fleet = {"alpha": STRONG_APP, "beta": WEAK_APP}
        result = cs.fleet_scorecard(fleet)
        self.assertEqual(result["weakest_app"], "beta")

    def test_recommended_capability(self):
        fleet = {"alpha": STRONG_APP, "beta": WEAK_APP}
        result = cs.fleet_scorecard(fleet)
        self.assertIn(result["recommended_next_capability"], cs.CAPABILITIES)

    def test_tie_break_alphabetical(self):
        # Two apps with identical telemetry — alphabetically first wins tie
        fleet = {"zebra": MEDIUM_APP, "alpha": MEDIUM_APP}
        result = cs.fleet_scorecard(fleet)
        self.assertEqual(result["weakest_app"], "alpha")

    def test_single_app(self):
        fleet = {"only": MEDIUM_APP}
        result = cs.fleet_scorecard(fleet)
        self.assertEqual(result["weakest_app"], "only")
        self.assertIn(result["recommended_next_capability"], cs.CAPABILITIES)

    def test_three_apps_correct_weakest(self):
        fleet = {"a": STRONG_APP, "b": MEDIUM_APP, "c": WEAK_APP}
        result = cs.fleet_scorecard(fleet)
        self.assertEqual(result["weakest_app"], "c")
        self.assertEqual(len(result["apps"]), 3)


if __name__ == "__main__":
    unittest.main()
