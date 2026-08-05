#!/usr/bin/env python3
"""
Test suite for economic_scheduler.py - revenue-focused task prioritization.

Tests cover:
- predict_revenue for high-growth projects, revenue keywords, bugfix w/ error spikes
- cost_benefit threshold logic (worthwhile / not worthwhile edge cases)
- Consistent scoring across projects with/without revenue history
- Fail-soft: missing revenue data → return 0 score, task stays queued
- Deterministic scoring: same task+ctx → same score every time
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import economic_scheduler as es


class TestPredictRevenue:
    """Test suite for predict_revenue function."""

    def test_base_revenue_from_kind_roi(self):
        """predict_revenue uses kind's historical avg_delta as base."""
        task = {"kind": "bugfix", "project": "myapp", "prompt": "fix the bug"}
        ctx = {
            "surface_returns": {"bugfix": 50.0},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        result = es.predict_revenue(task, ctx)
        assert result["point_estimate"] == 50.0, f"Expected 50.0, got {result['point_estimate']}"
        assert result["confidence_low"] == 37.5
        assert result["confidence_high"] == 62.5

    def test_high_growth_boost_2x(self):
        """predict_revenue boosts 2x if project is high-growth."""
        task = {"kind": "build", "project": "startup-app", "prompt": "new feature"}
        ctx = {
            "surface_returns": {"build": 30.0},
            "high_growth_projects": {"startup-app"},
            "app_signals": {},
        }
        result = es.predict_revenue(task, ctx)
        # 30.0 * 2.0 = 60.0
        assert result["point_estimate"] == 60.0, f"Expected 60.0, got {result['point_estimate']}"

    def test_revenue_keywords_boost_1_5x(self):
        """predict_revenue boosts 1.5x if task mentions revenue keywords."""
        task = {
            "kind": "build",
            "project": "myapp",
            "prompt": "implement stripe payment integration"
        }
        ctx = {
            "surface_returns": {"build": 20.0},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        result = es.predict_revenue(task, ctx)
        # 20.0 * 1.5 = 30.0
        assert result["point_estimate"] == 30.0, f"Expected 30.0, got {result['point_estimate']}"

    def test_error_spike_boosts_bugfix_1_5x(self):
        """predict_revenue boosts bugfix 1.5x when error_rate > 0.3."""
        task = {"kind": "bugfix", "project": "myapp", "prompt": "fix the crash"}
        ctx = {
            "surface_returns": {"bugfix": 20.0},
            "high_growth_projects": set(),
            "app_signals": {"myapp": {"error_rate": 0.5}},
        }
        result = es.predict_revenue(task, ctx)
        # 20.0 * 1.5 = 30.0
        assert result["point_estimate"] == 30.0, f"Expected 30.0, got {result['point_estimate']}"

    def test_combined_boosts_multiplicative(self):
        """Multiple boosts stack multiplicatively."""
        task = {
            "kind": "bugfix",
            "project": "startup-app",
            "prompt": "fix stripe payment crash",
        }
        ctx = {
            "surface_returns": {"bugfix": 10.0},
            "high_growth_projects": {"startup-app"},  # 2x
            "app_signals": {"startup-app": {"error_rate": 0.5}},  # 1.5x
        }
        result = es.predict_revenue(task, ctx)
        # 10.0 * 2.0 * 1.5 = 30.0 (no revenue keyword, so no third boost)
        assert result["point_estimate"] == 30.0, f"Expected 30.0, got {result['point_estimate']}"

    def test_combined_boosts_with_revenue_keyword(self):
        """All three boosts: high-growth, revenue keyword, error spike."""
        task = {
            "kind": "bugfix",
            "project": "startup-app",
            "prompt": "fix critical stripe payment processing error",
        }
        ctx = {
            "surface_returns": {"bugfix": 10.0},
            "high_growth_projects": {"startup-app"},  # 2x
            "app_signals": {"startup-app": {"error_rate": 0.5}},  # 1.5x
        }
        result = es.predict_revenue(task, ctx)
        # 10.0 * 2.0 * 1.5 * 1.5 = 45.0
        assert result["point_estimate"] == 45.0, f"Expected 45.0, got {result['point_estimate']}"

    def test_zero_revenue_base_stays_zero(self):
        """If kind_roi is 0 or missing, revenue stays capped at 0."""
        task = {"kind": "refactor", "project": "myapp", "prompt": "refactor utils"}
        ctx = {
            "surface_returns": {},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        result = es.predict_revenue(task, ctx)
        assert result["point_estimate"] == 0.0

    def test_missing_context_fails_soft(self):
        """Missing context keys return 0 estimate, not exception."""
        task = {"kind": "build", "project": "myapp", "prompt": "test"}
        ctx = {}
        result = es.predict_revenue(task, ctx)
        assert result["point_estimate"] == 0.0
        assert result["confidence_low"] == 0.0
        assert result["confidence_high"] == 0.0

    def test_none_task_fails_soft(self):
        """None task returns 0 estimate, not exception."""
        ctx = {"surface_returns": {}}
        result = es.predict_revenue(None, ctx)
        assert result["point_estimate"] == 0.0


class TestCostBenefit:
    """Test suite for cost_benefit function."""

    def test_worthwhile_when_revenue_exceeds_threshold(self):
        """worthwhile=True when revenue > 1.5 * cost."""
        task = {"kind": "build", "project": "myapp", "prompt": "add payment"}
        ctx = {
            "surface_returns": {"build": 30.0},
            "outcome_stats": {"myapp": {"avg_usd": 10.0, "success_rate": 0.8}},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        result = es.cost_benefit(task, ctx)
        # revenue=30.0, cost=10.0, roi=3.0, 30.0 > 1.5*10.0 (15.0) ✓
        assert result["worthwhile"] is True
        assert result["roi"] == 3.0

    def test_not_worthwhile_when_revenue_below_threshold(self):
        """worthwhile=False when revenue <= 1.5 * cost."""
        task = {"kind": "refactor", "project": "myapp", "prompt": "code cleanup"}
        ctx = {
            "surface_returns": {"refactor": 0.0},
            "outcome_stats": {"myapp": {"avg_usd": 10.0, "success_rate": 0.8}},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        result = es.cost_benefit(task, ctx)
        # revenue=0.0, cost=10.0, roi=0.0, 0.0 NOT > 1.5*10.0 ✗
        assert result["worthwhile"] is False
        assert result["roi"] == 0.0

    def test_edge_case_exactly_threshold(self):
        """worthwhile=False when revenue == 1.5 * cost (requires >)."""
        task = {"kind": "build", "project": "myapp", "prompt": "test"}
        ctx = {
            "surface_returns": {"build": 15.0},
            "outcome_stats": {"myapp": {"avg_usd": 10.0, "success_rate": 0.8}},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        result = es.cost_benefit(task, ctx)
        # revenue=15.0, cost=10.0, 15.0 == 1.5*10.0, should be False (not >)
        assert result["worthwhile"] is False

    def test_missing_outcome_stats_cost_zero(self):
        """If outcome_stats missing, estimated_cost defaults to 0."""
        task = {"kind": "build", "project": "unknown-app", "prompt": "test"}
        ctx = {
            "surface_returns": {"build": 20.0},
            "outcome_stats": {},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        result = es.cost_benefit(task, ctx)
        assert result["estimated_cost"] == 0.0
        # revenue=20.0, cost=0, worthwhile should be True (20 > 1.5*0)
        assert result["worthwhile"] is True

    def test_fail_soft_returns_sensible_defaults(self):
        """Fail-soft: None task returns dict with False worthwhile."""
        ctx = {}
        result = es.cost_benefit(None, ctx)
        assert result["worthwhile"] is False
        assert result["predicted_revenue"] == 0.0
        assert result["estimated_cost"] == 0.0


class TestScore:
    """Test suite for score function."""

    def test_deterministic_same_input_same_output(self):
        """Deterministic: calling score(task, ctx) twice returns same result."""
        task = {"kind": "build", "project": "myapp", "prompt": "add feature"}
        ctx = {
            "surface_returns": {"build": 25.0},
            "outcome_stats": {"myapp": {"avg_usd": 5.0, "success_rate": 0.8}},
            "family_outcomes": {},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        score1 = es.score(task, ctx)
        score2 = es.score(task, ctx)
        assert score1 == score2, f"Score not deterministic: {score1} != {score2}"

    def test_score_incorporates_revenue_and_cost(self):
        """Score increases with revenue, decreases with cost."""
        task_high_rev = {"kind": "build", "project": "app1", "prompt": "pricing"}
        task_low_rev = {"kind": "build", "project": "app2", "prompt": "test"}
        ctx = {
            "surface_returns": {"build": 50.0},
            "outcome_stats": {
                "app1": {"avg_usd": 5.0, "success_rate": 0.8},
                "app2": {"avg_usd": 10.0, "success_rate": 0.8},
            },
            "family_outcomes": {},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        score_high = es.score(task_high_rev, ctx)
        score_low = es.score(task_low_rev, ctx)
        # High revenue + low cost should score higher
        assert score_high > score_low, f"Expected {score_high} > {score_low}"

    def test_score_incorporates_success_rate(self):
        """Score multiplied by (1 + success_rate)."""
        task = {"kind": "build", "project": "myapp", "prompt": "test"}
        ctx_base = {
            "surface_returns": {"build": 20.0},
            "family_outcomes": {},
            "high_growth_projects": set(),
            "app_signals": {},
        }

        ctx_high_success = dict(ctx_base)
        ctx_high_success["outcome_stats"] = {
            "myapp": {"avg_usd": 10.0, "success_rate": 0.9}
        }
        score_high = es.score(task, ctx_high_success)

        ctx_low_success = dict(ctx_base)
        ctx_low_success["outcome_stats"] = {
            "myapp": {"avg_usd": 10.0, "success_rate": 0.1}
        }
        score_low = es.score(task, ctx_low_success)

        # Higher success_rate should yield higher score
        assert score_high > score_low

    def test_score_zero_on_missing_data(self):
        """Score is 0 when predict_revenue returns 0."""
        task = {"kind": "refactor", "project": "myapp", "prompt": "cleanup"}
        ctx = {
            "surface_returns": {},
            "outcome_stats": {"myapp": {"avg_usd": 5.0, "success_rate": 0.8}},
            "family_outcomes": {},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        score = es.score(task, ctx)
        # predict_revenue returns 0, so score should be 0
        assert score == 0.0

    def test_score_fails_soft_on_exception(self):
        """Score returns 0.0 if an exception occurs."""
        task = {"kind": "build", "project": "myapp", "prompt": "test"}
        ctx = None  # Will cause AttributeError in score(), caught by fail-soft
        score = es.score(task, ctx)
        assert score == 0.0


class TestApplyRouting:
    """Test suite for apply_routing function."""

    def test_routes_top_n_tasks(self):
        """apply_routing annotates top TOP_REVENUE_TASKS tasks."""
        # Create mock scored tasks
        scored = [
            (10.0, {"id": f"task-{i}", "kind": "build", "project": "myapp"})
            for i in range(30)
        ]
        # Note: This test won't actually update the DB (no mock), but tests the logic
        result = es.apply_routing(scored)
        assert result["lane"] == "revenue-critical"
        # routed count depends on DB success; in test it would be 0 due to no mock

    def test_empty_scored_returns_zero_routed(self):
        """apply_routing on empty list returns 0 routed."""
        result = es.apply_routing([])
        assert result["routed"] == 0
        assert result["lane"] == "revenue-critical"

    def test_apply_routing_none_task_skipped(self):
        """apply_routing skips None tasks gracefully."""
        scored = [
            (10.0, None),
            (5.0, {"id": "task-1"}),
        ]
        result = es.apply_routing(scored)
        # Should return without error
        assert result["lane"] == "revenue-critical"


class TestPredictRevenueBulk:
    """Test suite for predict_revenue_bulk function."""

    def test_bulk_returns_dict_task_id_to_estimate(self):
        """predict_revenue_bulk returns dict mapping task_id -> revenue."""
        tasks = [
            {"id": "t1", "kind": "build", "project": "app1", "prompt": "pricing"},
            {"id": "t2", "kind": "refactor", "project": "app2", "prompt": "cleanup"},
        ]
        ctx = {
            "surface_returns": {"build": 30.0, "refactor": 0.0},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        result = es.predict_revenue_bulk(tasks, ctx)
        assert isinstance(result, dict)
        assert "t1" in result
        assert "t2" in result
        assert result["t1"] == 30.0
        assert result["t2"] == 0.0

    def test_bulk_empty_tasks(self):
        """predict_revenue_bulk on empty list returns empty dict."""
        result = es.predict_revenue_bulk([], {})
        assert result == {}

    def test_bulk_none_tasks_skipped(self):
        """predict_revenue_bulk skips None tasks."""
        tasks = [None, {"id": "t1", "kind": "build", "project": "app", "prompt": ""}]
        ctx = {"surface_returns": {"build": 20.0}, "high_growth_projects": set(), "app_signals": {}}
        result = es.predict_revenue_bulk(tasks, ctx)
        assert "t1" in result
        assert len(result) == 1


class TestIntegration:
    """Integration tests for the economic_scheduler module."""

    def test_revenue_vs_cost_drives_priority(self):
        """High-ROI tasks score higher than low-ROI tasks."""
        ctx = {
            "surface_returns": {"build": 100.0, "refactor": 0.0},
            "outcome_stats": {
                "app1": {"avg_usd": 5.0, "success_rate": 0.8},
                "app2": {"avg_usd": 5.0, "success_rate": 0.8},
            },
            "family_outcomes": {},
            "high_growth_projects": set(),
            "app_signals": {},
        }

        task_high_roi = {"kind": "build", "project": "app1", "prompt": "stripe integration"}
        task_low_roi = {"kind": "refactor", "project": "app2", "prompt": "cleanup"}

        score_high = es.score(task_high_roi, ctx)
        score_low = es.score(task_low_roi, ctx)

        assert score_high > score_low, "High-ROI task should score higher"

    def test_confidence_intervals_reasonable(self):
        """Confidence intervals are ±25% around point estimate."""
        task = {"kind": "build", "project": "app", "prompt": "feature"}
        ctx = {
            "surface_returns": {"build": 40.0},
            "high_growth_projects": set(),
            "app_signals": {},
        }
        result = es.predict_revenue(task, ctx)
        point = result["point_estimate"]
        low = result["confidence_low"]
        high = result["confidence_high"]

        assert low == point * 0.75
        assert high == point * 1.25

    def test_fail_soft_throughout_pipeline(self):
        """Every function fails soft: missing data doesn't crash."""
        bad_task = None
        bad_ctx = None
        ctx = {}

        # All should return sensible defaults, not raise
        assert es.predict_revenue(bad_task, bad_ctx) == {
            "point_estimate": 0.0,
            "confidence_low": 0.0,
            "confidence_high": 0.0,
        }
        assert es.cost_benefit(bad_task, bad_ctx)["worthwhile"] is False
        assert es.score(bad_task, bad_ctx) == 0.0
        assert es.apply_routing(None) == {"routed": 0, "lane": "revenue-critical"}


if __name__ == "__main__":
    # Simple test runner for manual verification
    import inspect

    test_classes = [
        TestPredictRevenue,
        TestCostBenefit,
        TestScore,
        TestApplyRouting,
        TestPredictRevenueBulk,
        TestIntegration,
    ]

    total_tests = 0
    passed_tests = 0
    failed_tests = []

    for test_class in test_classes:
        instance = test_class()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in methods:
            total_tests += 1
            try:
                method = getattr(instance, method_name)
                method()
                passed_tests += 1
                print(f"✓ {test_class.__name__}.{method_name}")
            except AssertionError as e:
                failed_tests.append((test_class.__name__, method_name, str(e)))
                print(f"✗ {test_class.__name__}.{method_name}: {e}")
            except Exception as e:
                failed_tests.append((test_class.__name__, method_name, str(e)))
                print(f"✗ {test_class.__name__}.{method_name}: {type(e).__name__}: {e}")

    print(f"\n{'='*60}")
    print(f"Results: {passed_tests}/{total_tests} passed")
    if failed_tests:
        print(f"\nFailed tests:")
        for cls, method, error in failed_tests:
            print(f"  - {cls}.{method}: {error}")
    print(f"{'='*60}")
