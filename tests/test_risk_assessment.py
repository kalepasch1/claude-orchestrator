#!/usr/bin/env python3
"""Tests for risk_assessment (merge-risk model, slice 3).

Covers the contract, the saturation behaviour that is the whole point of the model,
and the fail-soft paths — a scorer that raises inside the merge train is worse than
one that returns 0.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import risk_assessment as ra  # noqa: E402


def _cfg():
    return ra.load_config()


class ScoreRangeTests(unittest.TestCase):
    def test_empty_metrics_score_zero_and_read_low(self):
        self.assertEqual(ra.score_pull_request({}), 0.0)
        self.assertEqual(ra.classify(0.0), "low")

    def test_score_is_clamped_to_the_zero_hundred_range(self):
        huge = {
            "files_changed": 10_000,
            "lines_added": 500_000,
            "lines_deleted": 500_000,
            "coverage_delta": -95.0,
            "contributor_reverts": 99,
            "material_paths": 99,
        }
        score = ra.score_pull_request(huge)
        self.assertLessEqual(score, 100.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertEqual(ra.classify(score), "high")

    def test_score_is_monotonic_in_churn(self):
        small = ra.score_pull_request({"lines_added": 10})
        big = ra.score_pull_request({"lines_added": 400})
        self.assertGreater(big, small)


class SaturationTests(unittest.TestCase):
    """A giant reformat must not drown out a small material change."""

    def test_churn_saturates_so_it_cannot_pin_the_score(self):
        cfg = _cfg()
        at_cap = ra.component_scores({"lines_added": cfg["saturation"]["lines_churn"]}, cfg)
        way_over = ra.component_scores({"lines_added": 1_000_000}, cfg)
        self.assertAlmostEqual(at_cap["lines_churn"], way_over["lines_churn"])
        self.assertAlmostEqual(way_over["lines_churn"], cfg["weights"]["lines_churn"])

    def test_a_small_material_change_still_scores(self):
        one_line_material = ra.score_pull_request(
            {"files_changed": 1, "lines_added": 2, "material_paths": 3})
        self.assertGreater(one_line_material, 0.0)


class CoverageTests(unittest.TestCase):
    def test_only_a_coverage_drop_counts_as_risk(self):
        drop = ra.component_scores({"coverage_delta": -5.0})["coverage_delta"]
        gain = ra.component_scores({"coverage_delta": +5.0})["coverage_delta"]
        self.assertGreater(drop, 0.0)
        self.assertEqual(gain, 0.0)


class ContributorHistoryTests(unittest.TestCase):
    def test_a_track_record_damps_but_never_erases_reverts(self):
        raw = ra.component_scores({"contributor_reverts": 3})["contributor_history"]
        damped = ra.component_scores(
            {"contributor_reverts": 3, "contributor_prior_merges": 200})["contributor_history"]
        self.assertLess(damped, raw)
        self.assertGreater(damped, 0.0)


class ClassifyTests(unittest.TestCase):
    def test_bands_follow_the_configured_thresholds(self):
        cfg = _cfg()
        low_max = cfg["thresholds"]["low_risk_max"]
        high_min = cfg["thresholds"]["high_risk_min"]
        self.assertEqual(ra.classify(low_max, cfg), "low")
        self.assertEqual(ra.classify(high_min, cfg), "high")
        self.assertEqual(ra.classify((low_max + high_min) / 2, cfg), "medium")

    def test_unscoreable_input_reads_as_the_safest_band(self):
        self.assertEqual(ra.classify(None), "low")
        self.assertEqual(ra.classify("not a number"), "low")


class FailSoftTests(unittest.TestCase):
    def test_bad_metric_types_do_not_raise(self):
        for bad in (None, 42, "a string", [], object()):
            self.assertIsInstance(ra.score_pull_request(bad), float)

    def test_garbage_metric_values_are_ignored_not_fatal(self):
        score = ra.score_pull_request(
            {"files_changed": "many", "lines_added": None, "coverage_delta": [1]})
        self.assertEqual(score, 0.0)

    def test_missing_config_file_degrades_to_defaults(self):
        cfg = ra.load_config("/nonexistent/path/risk_config.yaml")
        self.assertEqual(cfg["thresholds"]["low_risk_max"],
                         ra.DEFAULT_CONFIG["thresholds"]["low_risk_max"])

    def test_config_singleton_is_cached_and_invalidatable(self):
        ra.invalidate_config()
        first = ra.get_config()
        self.assertIs(first, ra.get_config())
        ra.invalidate_config()
        self.assertIsNot(first, ra.get_config())


class AssessTests(unittest.TestCase):
    def test_assess_reports_score_band_and_every_component(self):
        out = ra.assess({"files_changed": 12, "lines_added": 300, "coverage_delta": -2.0})
        self.assertEqual(set(out), {"score", "band", "components"})
        self.assertEqual(set(out["components"]), set(ra.DEFAULT_CONFIG["weights"]))
        self.assertEqual(out["band"], ra.classify(out["score"]))

    def test_assess_on_bad_input_reports_zero_risk_rather_than_raising(self):
        out = ra.assess(None)
        self.assertEqual(out["score"], 0.0)
        self.assertEqual(out["band"], "low")


class ShippedConfigTests(unittest.TestCase):
    def test_risk_config_yaml_is_present_and_parses(self):
        path = ra.default_config_path()
        self.assertTrue(os.path.exists(path), path)
        cfg = ra.load_config(path)
        self.assertLess(cfg["thresholds"]["low_risk_max"],
                        cfg["thresholds"]["high_risk_min"])
        self.assertEqual(set(cfg["weights"]), set(ra.DEFAULT_CONFIG["weights"]))


if __name__ == "__main__":
    unittest.main()
