#!/usr/bin/env python3
"""Tests for tactic_success_detection module."""
import os, sys, math, time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Must mock db before importing the module under test
sys.modules.setdefault("db", type(sys)("db"))

import ab_test_framework
import tactic_success_detection as tsd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _seed_metrics(test_name, control_values, treatment_values,
                  metric_name="conversion_rate", treatment_variant="variant_a"):
    """Populate ab_test_framework store with synthetic data."""
    for v in control_values:
        ab_test_framework.record_metric(test_name, "control", metric_name, v)
    for v in treatment_values:
        ab_test_framework.record_metric(test_name, treatment_variant, metric_name, v)


@pytest.fixture(autouse=True)
def _clean_metrics():
    """Clear metrics before each test."""
    ab_test_framework.clear_metrics()
    yield
    ab_test_framework.clear_metrics()


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------
class TestMean:
    def test_basic(self):
        assert tsd._mean([1, 2, 3]) == 2.0

    def test_empty(self):
        assert tsd._mean([]) == 0.0

    def test_single(self):
        assert tsd._mean([5.0]) == 5.0


class TestVariance:
    def test_basic(self):
        # sample variance of [2, 4, 4, 4, 5, 5, 7, 9] = 4.571...
        vals = [2, 4, 4, 4, 5, 5, 7, 9]
        assert abs(tsd._variance(vals) - 4.571428571) < 0.01

    def test_single_element(self):
        assert tsd._variance([1.0]) == 0.0


class TestWelchTTest:
    def test_identical_groups(self):
        a = [1.0] * 50
        b = [1.0] * 50
        assert tsd._welch_t_test(a, b) == 1.0  # no difference

    def test_clearly_different(self):
        import random
        random.seed(42)
        a = [random.gauss(10, 1) for _ in range(100)]
        b = [random.gauss(15, 1) for _ in range(100)]
        p = tsd._welch_t_test(a, b)
        assert p < 0.001  # very significant

    def test_small_sample(self):
        assert tsd._welch_t_test([1.0], [2.0]) == 1.0


class TestCohensD:
    def test_large_effect(self):
        import random
        random.seed(99)
        a = [random.gauss(10, 2) for _ in range(100)]
        b = [random.gauss(15, 2) for _ in range(100)]
        d = tsd._cohens_d(a, b)
        assert d > 2.0  # very large effect

    def test_no_effect(self):
        a = [5.0] * 50
        b = [5.0] * 50
        assert tsd._cohens_d(a, b) == 0.0


# ---------------------------------------------------------------------------
# detect_proven_tactics
# ---------------------------------------------------------------------------
class TestDetectProvenTactics:
    def test_significant_lift_detected(self):
        """Treatment with >10% lift and p<0.05 should be returned."""
        import random
        random.seed(7)
        control = [random.gauss(0.10, 0.02) for _ in range(200)]
        treatment = [random.gauss(0.15, 0.02) for _ in range(200)]
        _seed_metrics("test_signup_cta", control, treatment)

        results = tsd.detect_proven_tactics(
            ["test_signup_cta"], metric_name="conversion_rate",
            min_lift=0.10, p_threshold=0.05, min_samples=30,
        )
        assert len(results) == 1
        r = results[0]
        assert r["test_name"] == "test_signup_cta"
        assert r["variant"] == "variant_a"
        assert r["lift"] > 0.10
        assert r["p_value"] < 0.05
        assert r["n_control"] == 200
        assert r["n_treatment"] == 200

    def test_no_lift_not_detected(self):
        """Equal groups should not be detected."""
        vals = [0.10] * 50
        _seed_metrics("test_no_diff", vals, vals)

        results = tsd.detect_proven_tactics(
            ["test_no_diff"], min_lift=0.10, p_threshold=0.05, min_samples=30,
        )
        assert len(results) == 0

    def test_insufficient_samples_skipped(self):
        """Too few samples should be skipped."""
        control = [0.10] * 5
        treatment = [0.20] * 5
        _seed_metrics("test_tiny", control, treatment)

        results = tsd.detect_proven_tactics(
            ["test_tiny"], min_samples=30,
        )
        assert len(results) == 0

    def test_not_significant_skipped(self):
        """High variance / low n => not significant despite lift."""
        import random
        random.seed(123)
        control = [random.gauss(0.10, 0.20) for _ in range(35)]
        treatment = [random.gauss(0.12, 0.20) for _ in range(35)]
        _seed_metrics("test_noisy", control, treatment)

        results = tsd.detect_proven_tactics(
            ["test_noisy"], min_lift=0.10, p_threshold=0.05, min_samples=30,
        )
        assert len(results) == 0

    def test_multiple_tests(self):
        """Scan multiple test names at once."""
        import random
        random.seed(55)
        # Test A: significant
        ctrl_a = [random.gauss(0.10, 0.01) for _ in range(100)]
        treat_a = [random.gauss(0.15, 0.01) for _ in range(100)]
        _seed_metrics("test_a", ctrl_a, treat_a)

        # Test B: no lift
        ctrl_b = [0.10] * 100
        treat_b = [0.10] * 100
        _seed_metrics("test_b", ctrl_b, treat_b)

        results = tsd.detect_proven_tactics(
            ["test_a", "test_b"], min_lift=0.10, p_threshold=0.05, min_samples=30,
        )
        assert len(results) == 1
        assert results[0]["test_name"] == "test_a"

    def test_missing_test_handled(self):
        """Non-existent test name should not raise."""
        results = tsd.detect_proven_tactics(["nonexistent_test"])
        assert results == []

    def test_custom_metric_name(self):
        """Should work with arbitrary metric names."""
        import random
        random.seed(77)
        ctrl = [random.gauss(50, 5) for _ in range(100)]
        treat = [random.gauss(65, 5) for _ in range(100)]
        _seed_metrics("test_rev", ctrl, treat, metric_name="revenue_per_user")

        results = tsd.detect_proven_tactics(
            ["test_rev"], metric_name="revenue_per_user",
            min_lift=0.10, p_threshold=0.05, min_samples=30,
        )
        assert len(results) == 1
        assert results[0]["lift"] > 0.20


# ---------------------------------------------------------------------------
# stats()
# ---------------------------------------------------------------------------
class TestStats:
    def test_stats_returns_keys(self):
        s = tsd.stats()
        assert "queries" in s
        assert "proven_tactics_found" in s
        assert "errors" in s
        assert "config" in s
        assert "lookback_days" in s["config"]
        assert "min_lift" in s["config"]
        assert "p_threshold" in s["config"]
        assert "min_samples" in s["config"]

    def test_stats_increments(self):
        initial = tsd.stats()["queries"]
        tsd.detect_proven_tactics([])
        assert tsd.stats()["queries"] == initial + 1
