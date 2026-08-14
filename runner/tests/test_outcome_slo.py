#!/usr/bin/env python3
"""Outcome SLOs (slice 1): quality + latency, verified under simulated load.

The point of keeping the computation pure is exactly this file: the existing
slo_controller checks fetch inside the check function, so none of them can be
exercised against a synthetic fleet. These can.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import outcome_slo as slo  # noqa: E402


def build(clean=True, wall_ms=60_000, **over):
    """One completed build. Clean unless told otherwise."""
    row = {
        "tests_passed": True, "integrated": True, "attempts": 1,
        "review_failures": 0, "rate_limited": False, "wall_ms": wall_ms,
    }
    if not clean:
        row["attempts"] = 3
    row.update(over)
    return row


def load(n, clean_fraction=1.0, wall_ms=60_000):
    """Simulate a window of n completed builds with a given clean fraction."""
    clean_n = int(round(n * clean_fraction))
    return ([build(clean=True, wall_ms=wall_ms) for _ in range(clean_n)]
            + [build(clean=False, wall_ms=wall_ms) for _ in range(n - clean_n)])


class TestPercentile(unittest.TestCase):
    def test_nearest_rank_returns_a_value_that_actually_occurred(self):
        vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertIn(slo.percentile(vals, 95), vals)
        self.assertEqual(slo.percentile(vals, 95), 10)
        self.assertEqual(slo.percentile(vals, 50), 5)

    def test_single_value_and_empty(self):
        self.assertEqual(slo.percentile([42], 95), 42)
        self.assertIsNone(slo.percentile([], 95))
        self.assertIsNone(slo.percentile(None, 95))

    def test_ignores_unusable_values(self):
        self.assertEqual(slo.percentile([1, None, "x", 3], 100), 3)

    def test_clamps_out_of_range_percentiles(self):
        self.assertEqual(slo.percentile([1, 2, 3], 1000), 3)
        self.assertEqual(slo.percentile([1, 2, 3], -5), 1)


class TestOutcomeQualityAccuracy(unittest.TestCase):
    """Accuracy of the rate under several simulated load conditions."""

    def test_all_clean_fleet_passes_at_1_0(self):
        c = slo.compute_outcome_quality(load(50, clean_fraction=1.0))
        self.assertEqual(c["value"], 1.0)
        self.assertIs(c["ok"], True)
        self.assertEqual(c["clean"], 50)

    def test_half_clean_fleet_computes_exactly_0_5_and_fails(self):
        c = slo.compute_outcome_quality(load(100, clean_fraction=0.5))
        self.assertEqual(c["value"], 0.5)
        self.assertIs(c["ok"], False)
        self.assertEqual(c["retried"], 50)

    def test_boundary_exactly_at_threshold_passes(self):
        c = slo.compute_outcome_quality(load(100, clean_fraction=0.75), threshold=0.75)
        self.assertEqual(c["value"], 0.75)
        self.assertIs(c["ok"], True, "at-threshold must pass; the SLO is >=")

    def test_one_below_threshold_fails(self):
        c = slo.compute_outcome_quality(load(100, clean_fraction=0.74), threshold=0.75)
        self.assertIs(c["ok"], False)

    def test_a_merged_build_that_took_four_attempts_is_not_clean(self):
        c = slo.compute_outcome_quality([build(attempts=4) for _ in range(10)])
        self.assertEqual(c["value"], 0.0)
        self.assertEqual(c["retried"], 10)

    def test_a_merged_build_with_review_failures_is_not_clean(self):
        c = slo.compute_outcome_quality([build(review_failures=2) for _ in range(10)])
        self.assertEqual(c["value"], 0.0)
        self.assertEqual(c["review_failed"], 10)

    def test_a_rate_limited_build_is_not_clean(self):
        c = slo.compute_outcome_quality([build(rate_limited=True) for _ in range(10)])
        self.assertEqual(c["value"], 0.0)
        self.assertEqual(c["rate_limited"], 10)

    def test_tests_passed_but_never_integrated_counts_completed_not_clean(self):
        rows = [build(integrated=False) for _ in range(10)]
        c = slo.compute_outcome_quality(rows)
        self.assertEqual(c["completed"], 10)
        self.assertEqual(c["clean"], 0)

    def test_incomplete_builds_are_excluded_from_the_denominator(self):
        rows = load(10, clean_fraction=1.0) + [
            {"tests_passed": False, "integrated": False} for _ in range(90)
        ]
        c = slo.compute_outcome_quality(rows)
        self.assertEqual(c["completed"], 10)
        self.assertEqual(c["value"], 1.0)


class TestQualityUnknown(unittest.TestCase):
    def test_thin_sample_is_UNKNOWN_not_green(self):
        c = slo.compute_outcome_quality(load(2))
        self.assertIsNone(c["ok"])
        self.assertEqual(c["state"], "UNKNOWN")
        self.assertIsNone(c["value"], "a thin window must not report a value")

    def test_empty_and_none_are_UNKNOWN(self):
        for arg in ([], None):
            self.assertIsNone(slo.compute_outcome_quality(arg)["ok"])

    def test_at_the_sample_floor_it_reports(self):
        c = slo.compute_outcome_quality(load(slo.SLO_OUTCOME_MIN_SAMPLES))
        self.assertIsNotNone(c["ok"])


class TestBuildLatencyAccuracy(unittest.TestCase):
    def test_p95_and_p50_under_a_uniform_load(self):
        rows = [build(wall_ms=i * 1000) for i in range(1, 101)]
        c = slo.compute_build_latency(rows, threshold_s=1000)
        self.assertEqual(c["p50_s"], 50.0)
        self.assertEqual(c["p95_s"], 95.0)
        self.assertEqual(c["max_s"], 100.0)
        self.assertIs(c["ok"], True)

    def test_a_slow_tail_fails_the_slo_even_with_a_fast_median(self):
        rows = [build(wall_ms=1_000) for _ in range(90)] + [build(wall_ms=5_000_000) for _ in range(10)]
        c = slo.compute_build_latency(rows, threshold_s=900)
        self.assertEqual(c["p50_s"], 1.0, "median stays fast")
        self.assertIs(c["ok"], False, "the tail is what the SLO is for")

    def test_boundary_exactly_at_threshold_passes(self):
        rows = [build(wall_ms=900_000) for _ in range(20)]
        c = slo.compute_build_latency(rows, threshold_s=900)
        self.assertEqual(c["value"], 900.0)
        self.assertIs(c["ok"], True, "at-threshold must pass; the SLO is <=")

    def test_a_build_with_no_wall_ms_is_unmeasured_not_fast(self):
        rows = [build(wall_ms=1_000) for _ in range(10)] + [build(wall_ms=None) for _ in range(10)]
        c = slo.compute_build_latency(rows, threshold_s=900)
        self.assertEqual(c["measured"], 10)
        self.assertEqual(c["unmeasured"], 10)
        self.assertEqual(c["completed"], 20)

    def test_negative_wall_ms_is_unmeasured(self):
        rows = [build(wall_ms=-5) for _ in range(10)]
        self.assertIsNone(slo.compute_build_latency(rows)["ok"])

    def test_thin_measured_sample_is_UNKNOWN(self):
        c = slo.compute_build_latency([build(wall_ms=1_000) for _ in range(2)])
        self.assertIsNone(c["ok"])
        self.assertIsNone(c["value"])


class TestRobustness(unittest.TestCase):
    """Fail-soft: bad input is skipped, never fatal."""

    def test_malformed_rows_do_not_raise(self):
        junk = [None, "row", 42, [], {"tests_passed": "yes"}]
        self.assertIsNotNone(slo.compute_outcome_quality(junk))
        self.assertIsNotNone(slo.compute_build_latency(junk))

    def test_non_numeric_fields_do_not_raise(self):
        rows = [build(attempts="many", review_failures="lots", wall_ms="soon") for _ in range(10)]
        q = slo.compute_outcome_quality(rows)
        self.assertIsNotNone(q)
        self.assertIsNone(slo.compute_build_latency(rows)["ok"], "unparseable latency is unmeasured")

    def test_booleans_are_never_read_as_measurements(self):
        self.assertIsNone(slo._num(True))
        self.assertIsNone(slo._num(False))


class TestEvaluateAndReport(unittest.TestCase):
    def test_evaluate_returns_both_slos(self):
        checks = slo.evaluate_outcome_slos(load(20, clean_fraction=1.0))
        self.assertEqual(sorted(checks), ["build_latency", "outcome_quality"])

    def test_report_is_operator_readable_and_names_the_failure(self):
        checks = slo.evaluate_outcome_slos(load(100, clean_fraction=0.1, wall_ms=60_000))
        report = slo.render_report(checks)
        self.assertIn("outcome_quality", report)
        self.assertIn("FAIL", report)
        self.assertIn("FAILING:", report)

    def test_report_says_UNKNOWN_rather_than_inventing_a_green(self):
        report = slo.render_report(slo.evaluate_outcome_slos([]))
        self.assertIn("UNKNOWN", report)
        self.assertNotIn("PASS", report)

    def test_report_is_deterministic(self):
        checks = slo.evaluate_outcome_slos(load(30, clean_fraction=0.5))
        self.assertEqual(slo.render_report(checks), slo.render_report(checks))

    def test_report_survives_empty_input(self):
        self.assertIsInstance(slo.render_report({}), str)
        self.assertIsInstance(slo.render_report(None), str)


if __name__ == "__main__":
    unittest.main()
