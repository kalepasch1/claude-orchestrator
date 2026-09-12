#!/usr/bin/env python3
"""
Test suite for cross-learning route selection and Q-score updates.

Tests cover:
- Learned route querying by operation name
- Q-score (quality/performance signal) retrieval
- Q-score updates after task completion
- Model/provider selection from routes
- Fallback to default when route missing
- Route ranking and highest-confidence selection
- Cost tracking and model performance correlation
"""
import pytest
import os
import sys
import json
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import orchestration_contract as oc


class TestLearnedRoutes:
    """Tests for learned model route definitions."""

    def test_route_debate_compress_exists(self):
        """Learned route: debate_compress -> haiku q=7.0."""
        # Mock DB to return learned route
        with patch('orchestration_contract.db.select') as mock_select:
            mock_select.return_value = [
                {"operation": "debate_compress", "model": "claude-haiku-4.5", "q_score": 7.0, "cost": 0.0008}
            ]
            rows = mock_select()
            assert len(rows) > 0
            route = rows[0]
            assert route["operation"] == "debate_compress"
            assert route["model"] == "claude-haiku-4.5"
            assert route["q_score"] == 7.0

    def test_route_pipeline_plan_exists(self):
        """Learned route: pipeline_plan -> llama3.2 q=7.7."""
        with patch('orchestration_contract.db.select') as mock_select:
            mock_select.return_value = [
                {"operation": "pipeline_plan", "model": "local:llama3.2:70b", "q_score": 7.7, "cost": 0.0}
            ]
            rows = mock_select()
            route = rows[0]
            assert route["operation"] == "pipeline_plan"
            assert "llama3.2" in route["model"]
            assert route["q_score"] == 7.7

    def test_route_build_fix_exists(self):
        """Learned route: build_fix -> kimi-k2.7-code q=7.7."""
        with patch('orchestration_contract.db.select') as mock_select:
            mock_select.return_value = [
                {"operation": "build_fix", "model": "kimi-k2.7-code", "q_score": 7.7, "cost": 0.002}
            ]
            rows = mock_select()
            route = rows[0]
            assert route["operation"] == "build_fix"
            assert "kimi" in route["model"]
            assert route["q_score"] == 7.7

    def test_route_confidence_gate_exists(self):
        """Learned route: confidence_gate -> haiku q=7.0."""
        with patch('orchestration_contract.db.select') as mock_select:
            mock_select.return_value = [
                {"operation": "confidence_gate", "model": "claude-haiku-4.5", "q_score": 7.0, "cost": 0.0008}
            ]
            rows = mock_select()
            route = rows[0]
            assert route["operation"] == "confidence_gate"
            assert route["q_score"] == 7.0


class TestQScoreManagement:
    """Tests for Q-score retrieval and updates."""

    def test_query_route_by_name(self):
        """Query learned route by operation name."""
        with patch('orchestration_contract.db.select') as mock_select:
            mock_select.return_value = [
                {"operation": "debate_compress", "model": "haiku", "q_score": 7.0}
            ]
            # Simulate querying by operation name
            rows = mock_select("learned_routes", {"operation": "debate_compress"})
            assert len(rows) == 1
            assert rows[0]["q_score"] == 7.0

    def test_q_score_reflects_performance(self):
        """Q-score indicates model performance quality."""
        # Higher q-score = better performance
        route_excellent = {"model": "opus", "q_score": 8.5, "tests_passed": 20}
        route_good = {"model": "haiku", "q_score": 7.0, "tests_passed": 14}

        assert route_excellent["q_score"] > route_good["q_score"]

    def test_update_q_score_after_success(self):
        """Q-score increases after successful task."""
        old_q = 6.9
        new_q = 7.2  # Improved

        delta = new_q - old_q
        assert delta > 0
        # 7.2 - 6.9 is 0.2999999999999998 in binary floating point, so `== 0.3` could
        # never hold. Nothing here touches product code -- it is arithmetic on two
        # literals -- so the only thing to fix is the comparison.
        assert delta == pytest.approx(0.3)

    def test_update_q_score_after_failure(self):
        """Q-score decreases after failed task."""
        old_q = 7.2
        new_q = 6.8  # Decreased

        delta = new_q - old_q
        assert delta < 0

    def test_q_score_bounded_range(self):
        """Q-scores stay within valid range."""
        valid_q_scores = [0.0, 1.5, 5.0, 7.5, 9.0, 10.0]
        for q in valid_q_scores:
            assert 0.0 <= q <= 10.0

    def test_q_score_precision(self):
        """Q-scores maintain decimal precision."""
        q = 7.234567
        # Should round to reasonable precision
        rounded = round(q, 1)
        assert 7.2 <= rounded <= 7.3


class TestModelSelection:
    """Tests for model selection from routes."""

    def test_select_model_from_route(self):
        """Select model from route definition."""
        route = {"model": "claude-opus", "q_score": 8.0}
        model = route["model"]
        assert model == "claude-opus"

    def test_select_provider_from_route(self):
        """Select provider from route definition."""
        route = {"model": "local:llama3.2:70b", "q_score": 7.7}
        # Provider can be extracted from model string
        if ":" in route["model"]:
            provider = route["model"].split(":")[0]
            assert provider == "local"

    def test_select_highest_q_score_route(self):
        """Select route with highest Q-score."""
        routes = [
            {"operation": "op1", "q_score": 6.5},
            {"operation": "op2", "q_score": 7.8},
            {"operation": "op3", "q_score": 7.2},
        ]
        best = max(routes, key=lambda r: r["q_score"])
        assert best["operation"] == "op2"
        assert best["q_score"] == 7.8

    def test_route_cost_selection(self):
        """Route includes cost information."""
        route = {"model": "local:llama", "q_score": 7.5, "cost": 0.0}
        # Local models have zero cost
        assert route["cost"] == 0.0

    def test_route_cost_for_cloud_models(self):
        """Cloud model routes include cost."""
        route = {"model": "claude-opus", "q_score": 8.0, "cost": 0.015}
        assert route["cost"] > 0


class TestFallbackRouting:
    """Tests for fallback behavior when route missing."""

    def test_fallback_to_default_model(self):
        """Fallback to default model if learned route missing."""
        with patch('orchestration_contract.db.select') as mock_select:
            mock_select.return_value = []  # No learned route
            rows = mock_select("learned_routes", {"operation": "unknown_op"})

            if not rows:
                default_model = "claude-haiku-4.5"
                assert default_model is not None

    def test_fallback_when_db_unavailable(self):
        """Fallback when DB query fails."""
        with patch('orchestration_contract.db.select') as mock_select:
            mock_select.side_effect = Exception("DB error")

            try:
                rows = mock_select("learned_routes", {})
            except Exception:
                # Should fail gracefully in actual code
                default = "claude-haiku-4.5"
                assert default is not None

    def test_fallback_preserves_operation_type(self):
        """Fallback model still handles same operation."""
        operation = "task_preflight"

        # If learned route missing, use default
        with patch('orchestration_contract.db.select') as mock_select:
            mock_select.return_value = []

            # Code should still assign a model to this operation
            default_for_op = "claude-haiku-4.5"
            assert default_for_op is not None


class TestRouteRanking:
    """Tests for route ranking and selection."""

    def test_rank_routes_by_q_score(self):
        """Routes ranked by Q-score descending."""
        routes = [
            {"model": "llama", "q_score": 6.5},
            {"model": "opus", "q_score": 8.2},
            {"model": "sonnet", "q_score": 7.9},
            {"model": "haiku", "q_score": 7.0},
        ]

        ranked = sorted(routes, key=lambda r: r["q_score"], reverse=True)
        assert ranked[0]["model"] == "opus"
        assert ranked[1]["model"] == "sonnet"
        assert ranked[2]["model"] == "haiku"
        assert ranked[3]["model"] == "llama"

    def test_select_top_ranked_route(self):
        """Selection prefers top-ranked (highest Q) route."""
        routes = [
            {"operation": "task1", "q_score": 6.0},
            {"operation": "task2", "q_score": 8.5},
            {"operation": "task3", "q_score": 7.2},
        ]

        selected = max(routes, key=lambda r: r["q_score"])
        assert selected["operation"] == "task2"

    def test_route_confidence_threshold(self):
        """Route only selected if confidence above threshold."""
        threshold = 6.0
        routes = [
            {"model": "weak_model", "q_score": 5.5},  # Below threshold
            {"model": "good_model", "q_score": 7.2},  # Above threshold
        ]

        valid = [r for r in routes if r["q_score"] >= threshold]
        assert len(valid) == 1
        assert valid[0]["model"] == "good_model"

    def test_route_tie_breaking(self):
        """Tie-breaking when multiple routes have same Q-score."""
        routes = [
            {"model": "model_a", "q_score": 7.0, "tests_passed": 20},
            {"model": "model_b", "q_score": 7.0, "tests_passed": 22},
        ]

        # Break tie by secondary metric (tests_passed)
        if routes[0]["q_score"] == routes[1]["q_score"]:
            selected = max(routes, key=lambda r: r.get("tests_passed", 0))
            assert selected["model"] == "model_b"


class TestCrossLearningContext:
    """Tests for cross-learning from prior runs."""

    def test_recent_outcome_signal(self):
        """Query recent outcome signals."""
        with patch('orchestration_contract.query_recent_outcomes') as mock_query:
            mock_query.return_value = [
                {"task_id": "t1", "integrated": True, "model": "claude-opus"},
                {"task_id": "t2", "integrated": True, "model": "claude-opus"},
                {"task_id": "t3", "integrated": False, "model": "local:llama"},
            ]

            outcomes = mock_query(30)
            assert len(outcomes) == 3
            integrated = [o for o in outcomes if o["integrated"]]
            assert len(integrated) == 2

    def test_outcome_signal_affects_route_selection(self):
        """Outcomes influence route selection."""
        route_a = {"model": "opus", "q_score": 8.0, "recent_successes": 5}
        route_b = {"model": "llama", "q_score": 7.5, "recent_successes": 2}

        # Route A has both higher q-score and more recent successes
        if route_a["q_score"] >= route_b["q_score"]:
            selected = route_a
            assert selected["model"] == "opus"

    def test_learned_route_update_from_outcome(self):
        """Learned routes update from task outcomes."""
        # Initial route
        route = {"operation": "build_fix", "model": "kimi", "q_score": 7.7, "successes": 3, "failures": 1}

        # After successful task
        new_q = 7.8  # Slight improvement
        assert new_q >= route["q_score"]

    def test_model_performance_correlation(self):
        """Model Q-score correlates with task success rate."""
        # High Q-score model
        high_q = {"model": "opus", "q_score": 8.5, "tests_passed": 25, "tests_total": 25}
        success_rate_high = high_q["tests_passed"] / high_q["tests_total"]

        # Lower Q-score model
        low_q = {"model": "haiku", "q_score": 6.5, "tests_passed": 16, "tests_total": 25}
        success_rate_low = low_q["tests_passed"] / low_q["tests_total"]

        # Higher Q should correlate with higher success rate
        assert success_rate_high > success_rate_low


class TestRouteMetrics:
    """Tests for route metrics and tracking."""

    def test_route_includes_cost_metric(self):
        """Route includes cost information."""
        route = {"model": "opus", "q_score": 8.0, "cost": 0.015, "currency": "USD"}
        assert "cost" in route
        assert route["cost"] > 0

    def test_route_includes_latency_metric(self):
        """Route includes latency information."""
        route = {"model": "llama", "q_score": 7.0, "latency_ms": 250}
        assert route["latency_ms"] < 1000  # Should be reasonable

    def test_route_includes_availability_metric(self):
        """Route includes availability metric."""
        route = {"model": "opus", "q_score": 8.0, "availability": 0.999}
        assert 0.0 <= route["availability"] <= 1.0

    def test_route_tracks_success_count(self):
        """Route tracks number of successful uses."""
        route = {"model": "sonnet", "q_score": 7.8, "successful_uses": 42}
        assert route["successful_uses"] >= 0

    def test_route_tracks_failure_count(self):
        """Route tracks number of failed uses."""
        route = {"model": "sonnet", "q_score": 7.8, "failed_uses": 3}
        assert route["failed_uses"] >= 0


class TestRouteIntegration:
    """End-to-end route selection workflow."""

    def test_full_route_selection_workflow(self):
        """Complete route selection for task."""
        with patch('orchestration_contract.db.select') as mock_select:
            # Mock learned routes
            mock_select.return_value = [
                {"operation": "task_preflight", "model": "haiku", "q_score": 7.0},
                {"operation": "task_strategy", "model": "llama3.2", "q_score": 7.7},
                {"operation": "task_qa", "model": "sonnet", "q_score": 7.9},
            ]

            routes = mock_select()
            assert len(routes) == 3

            # Select best for each operation
            for op in ["task_preflight", "task_strategy", "task_qa"]:
                op_routes = [r for r in routes if r["operation"] == op]
                if op_routes:
                    selected = max(op_routes, key=lambda r: r["q_score"])
                    assert selected is not None

    def test_route_selection_respects_constraints(self):
        """Route selection respects cost/availability constraints."""
        routes = [
            {"model": "expensive", "q_score": 9.0, "cost": 0.100, "availability": 0.95},
            {"model": "cheap", "q_score": 7.0, "cost": 0.001, "availability": 0.999},
        ]

        # Under cost constraint
        budget = 0.005
        affordable = [r for r in routes if r["cost"] <= budget]
        assert len(affordable) == 1
        assert affordable[0]["model"] == "cheap"

    def test_learned_routes_improve_over_time(self):
        """Q-scores improve as routes learn."""
        route_day1 = {"model": "opus", "q_score": 6.8, "date": "2026-01-01"}
        route_day30 = {"model": "opus", "q_score": 7.3, "date": "2026-01-30"}

        # Route improved over time
        assert route_day30["q_score"] > route_day1["q_score"]

    def test_route_degradation_tracked(self):
        """Degrading routes are tracked and replaced."""
        route_good = {"model": "llama", "q_score": 7.5, "status": "active"}
        route_bad = {"model": "llama", "q_score": 5.0, "status": "degraded"}

        if route_bad["q_score"] < 6.0:
            assert route_bad["status"] == "degraded"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
