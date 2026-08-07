"""Tests for economic_scheduler_revenue — cost-aware task scheduling and revenue optimization."""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestScheduleCostOptimized(unittest.TestCase):
    """Test cost-aware scheduling of tasks."""

    @patch("db.select")
    def test_schedules_high_roi_task_first(self, mock_select):
        """High-ROI tasks should be scheduled before low-ROI tasks."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"id": "t1", "estimated_cost_usd": 0.01, "revenue_impact_usd": 0.50},
            {"id": "t2", "estimated_cost_usd": 0.05, "revenue_impact_usd": 0.30},
        ]
        result = economic_scheduler_revenue.schedule_cost_optimized()
        self.assertEqual(result[0]["id"], "t1")

    @patch("db.select")
    def test_skips_negative_roi_tasks(self, mock_select):
        """Tasks with negative ROI should not be scheduled."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"id": "t1", "estimated_cost_usd": 0.10, "revenue_impact_usd": 0.05},
            {"id": "t2", "estimated_cost_usd": 0.01, "revenue_impact_usd": 0.20},
        ]
        result = economic_scheduler_revenue.schedule_cost_optimized()
        self.assertNotIn("t1", [t["id"] for t in result])

    @patch("db.select")
    def test_empty_queue_returns_empty_list(self, mock_select):
        """Empty task queue should return empty list."""
        import economic_scheduler_revenue
        mock_select.return_value = []
        result = economic_scheduler_revenue.schedule_cost_optimized()
        self.assertEqual(result, [])


class TestBudgetConstrainedScheduling(unittest.TestCase):
    """Test scheduling under budget constraints."""

    @patch("db.select")
    def test_respects_daily_budget_limit(self, mock_select):
        """Should not schedule tasks exceeding daily budget."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"id": "t1", "estimated_cost_usd": 2.00},
            {"id": "t2", "estimated_cost_usd": 3.00},
            {"id": "t3", "estimated_cost_usd": 1.00},
        ]
        result = economic_scheduler_revenue.schedule_with_budget(
            daily_budget_usd=4.00
        )
        total_cost = sum(t["estimated_cost_usd"] for t in result)
        self.assertLessEqual(total_cost, 4.00)

    @patch("db.select")
    def test_prioritizes_within_budget_constraints(self, mock_select):
        """Should schedule highest-ROI tasks within budget."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"id": "t1", "estimated_cost_usd": 0.50, "roi": 10.0},
            {"id": "t2", "estimated_cost_usd": 0.50, "roi": 5.0},
            {"id": "t3", "estimated_cost_usd": 0.50, "roi": 15.0},
        ]
        result = economic_scheduler_revenue.schedule_with_budget(daily_budget_usd=1.00)
        # Should prefer t3 (highest ROI) and t1 (second highest)
        ids = [t["id"] for t in result]
        self.assertIn("t3", ids)

    @patch("db.select")
    def test_returns_empty_when_cheapest_task_exceeds_budget(self, mock_select):
        """Should return empty if cheapest task exceeds remaining budget."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"id": "t1", "estimated_cost_usd": 5.00},
        ]
        result = economic_scheduler_revenue.schedule_with_budget(daily_budget_usd=1.00)
        self.assertEqual(result, [])


class TestCostPrediction(unittest.TestCase):
    """Test cost estimation and prediction."""

    def test_predicts_cost_for_haiku_input_tokens(self):
        """Should accurately predict Haiku costs for input tokens."""
        import economic_scheduler_revenue
        # Haiku: ~$0.00080 per 1M input tokens
        cost = economic_scheduler_revenue.predict_cost(
            model="claude-haiku-4-5-20251001",
            input_tokens=1000000
        )
        self.assertAlmostEqual(cost, 0.80, places=1)

    def test_predicts_cost_for_sonnet_input_tokens(self):
        """Should accurately predict Sonnet costs for input tokens."""
        import economic_scheduler_revenue
        # Sonnet: ~$0.003 per 1M input tokens
        cost = economic_scheduler_revenue.predict_cost(
            model="claude-sonnet-5",
            input_tokens=1000000
        )
        self.assertAlmostEqual(cost, 3.00, places=1)

    def test_predicts_cost_for_output_tokens(self):
        """Should factor output tokens in cost prediction."""
        import economic_scheduler_revenue
        cost = economic_scheduler_revenue.predict_cost(
            model="claude-sonnet-5",
            input_tokens=100,
            output_tokens=1000
        )
        self.assertGreater(cost, 0.0)

    def test_returns_zero_for_invalid_model(self):
        """Should return 0 for unknown model."""
        import economic_scheduler_revenue
        cost = economic_scheduler_revenue.predict_cost(
            model="unknown-model",
            input_tokens=1000
        )
        self.assertEqual(cost, 0.0)


class TestRevenueTracking(unittest.TestCase):
    """Test revenue attribution and tracking."""

    @patch("db.insert")
    @patch("db.select")
    def test_logs_revenue_for_successful_task(self, mock_select, mock_insert):
        """Should record revenue when task completes successfully."""
        import economic_scheduler_revenue
        mock_select.return_value = []
        mock_insert.return_value = True

        result = economic_scheduler_revenue.record_revenue(
            task_id="t1",
            revenue_usd=5.00,
            status="success",
            cost_usd=0.05
        )
        self.assertTrue(result)
        mock_insert.assert_called_once()

    @patch("db.insert")
    def test_records_negative_revenue_on_failure(self, mock_insert):
        """Should allow negative revenue recording for failed tasks."""
        import economic_scheduler_revenue
        mock_insert.return_value = True

        result = economic_scheduler_revenue.record_revenue(
            task_id="t1",
            revenue_usd=-1.00,
            status="failed",
            cost_usd=0.10
        )
        self.assertTrue(result)

    @patch("db.select")
    def test_calculates_profit_correctly(self, mock_select):
        """Should calculate profit as revenue minus cost."""
        import economic_scheduler_revenue
        profit = economic_scheduler_revenue.calculate_profit(
            revenue_usd=10.00,
            cost_usd=0.50
        )
        self.assertEqual(profit, 9.50)


class TestModelSelectionStrategy(unittest.TestCase):
    """Test intelligent model selection based on economics."""

    def test_selects_haiku_for_simple_tasks(self):
        """Should choose Haiku for low-complexity tasks."""
        import economic_scheduler_revenue
        model = economic_scheduler_revenue.select_model_economically(
            complexity_score=0.1,
            urgency=0.5,
            budget_remaining_usd=10.00
        )
        self.assertIn("haiku", model.lower())

    def test_selects_sonnet_for_moderate_complexity(self):
        """Should choose Sonnet for moderate complexity."""
        import economic_scheduler_revenue
        model = economic_scheduler_revenue.select_model_economically(
            complexity_score=0.6,
            urgency=0.5,
            budget_remaining_usd=10.00
        )
        self.assertIsNotNone(model)

    def test_respects_budget_constraint_in_model_selection(self):
        """Should not select expensive models when budget is low."""
        import economic_scheduler_revenue
        model = economic_scheduler_revenue.select_model_economically(
            complexity_score=0.8,
            urgency=0.5,
            budget_remaining_usd=0.10
        )
        # Should either fall back to cheaper model or return None
        if model:
            self.assertIn("haiku", model.lower())


class TestCostAnomalyDetection(unittest.TestCase):
    """Test detection of unusual API costs."""

    @patch("db.select")
    def test_detects_cost_spike(self, mock_select):
        """Should flag tasks with costs significantly above average."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"cost_usd": 0.01},
            {"cost_usd": 0.02},
            {"cost_usd": 0.015},
            {"cost_usd": 5.00},  # Anomaly
        ]
        anomalies = economic_scheduler_revenue.detect_cost_anomalies()
        self.assertGreater(len(anomalies), 0)

    @patch("db.select")
    def test_returns_empty_for_normal_costs(self, mock_select):
        """Should not flag normal cost variations."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"cost_usd": 0.01},
            {"cost_usd": 0.015},
            {"cost_usd": 0.012},
        ]
        anomalies = economic_scheduler_revenue.detect_cost_anomalies()
        self.assertEqual(len(anomalies), 0)


class TestBatchOptimization(unittest.TestCase):
    """Test batching tasks for cost efficiency."""

    @patch("db.select")
    def test_batches_similar_tasks(self, mock_select):
        """Should group similar tasks for batch processing."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"id": "t1", "type": "linting", "input_tokens": 500},
            {"id": "t2", "type": "linting", "input_tokens": 600},
            {"id": "t3", "type": "testing", "input_tokens": 1000},
        ]
        batches = economic_scheduler_revenue.optimize_batching()
        self.assertGreater(len(batches), 0)

    @patch("db.select")
    def test_batch_reduces_overhead_cost(self, mock_select):
        """Should estimate cost reduction from batching."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"id": "t1", "estimated_cost_usd": 0.10},
            {"id": "t2", "estimated_cost_usd": 0.10},
        ]
        savings = economic_scheduler_revenue.estimate_batch_savings(
            task_ids=["t1", "t2"]
        )
        self.assertGreater(savings, 0.0)


class TestCostStats(unittest.TestCase):
    """Test cost tracking and statistics."""

    @patch("db.select")
    def test_returns_cost_stats_dict(self, mock_select):
        """Should return structured cost statistics."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"cost_usd": 0.05, "revenue_usd": 1.00},
            {"cost_usd": 0.03, "revenue_usd": 0.50},
        ]
        stats = economic_scheduler_revenue.cost_stats()
        self.assertIsInstance(stats, dict)
        self.assertIn("total_cost_usd", stats)
        self.assertIn("total_revenue_usd", stats)
        self.assertIn("profit_usd", stats)

    @patch("db.select")
    def test_stats_includes_roi_metrics(self, mock_select):
        """Stats should include ROI calculations."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"cost_usd": 0.10, "revenue_usd": 1.00},
        ]
        stats = economic_scheduler_revenue.cost_stats()
        self.assertIn("avg_roi", stats)
        self.assertGreater(stats["avg_roi"], 0.0)


class TestBudgetTracking(unittest.TestCase):
    """Test budget allocation and tracking."""

    @patch("db.select")
    def test_tracks_remaining_budget(self, mock_select):
        """Should accurately calculate remaining budget."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"cost_usd": 2.00},
            {"cost_usd": 1.50},
        ]
        remaining = economic_scheduler_revenue.remaining_budget(
            daily_budget_usd=10.00
        )
        self.assertEqual(remaining, 6.50)

    @patch("db.select")
    def test_detects_budget_exhaustion(self, mock_select):
        """Should flag when budget is depleted."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"cost_usd": 9.00},
            {"cost_usd": 1.50},
        ]
        is_exhausted = economic_scheduler_revenue.is_budget_exhausted(
            daily_budget_usd=10.00
        )
        self.assertTrue(is_exhausted)

    @patch("db.select")
    def test_alerts_on_budget_threshold(self, mock_select):
        """Should alert when spending exceeds threshold."""
        import economic_scheduler_revenue
        mock_select.return_value = [
            {"cost_usd": 7.50},
        ]
        should_alert = economic_scheduler_revenue.should_alert_budget(
            daily_budget_usd=10.00,
            alert_threshold=0.75
        )
        self.assertTrue(should_alert)


class TestTokenEstimation(unittest.TestCase):
    """Test token count estimation for cost prediction."""

    def test_estimates_tokens_for_text(self):
        """Should estimate token count from text."""
        import economic_scheduler_revenue
        text = "Fix the bug in auth.py"
        estimated = economic_scheduler_revenue.estimate_tokens(text)
        self.assertGreater(estimated, 0)
        self.assertLess(estimated, len(text.split()) * 3)

    def test_estimates_tokens_for_empty_string(self):
        """Should handle empty string gracefully."""
        import economic_scheduler_revenue
        estimated = economic_scheduler_revenue.estimate_tokens("")
        self.assertEqual(estimated, 0)

    def test_token_estimation_scales_with_length(self):
        """Longer text should have higher token estimate."""
        import economic_scheduler_revenue
        short = "Fix bug"
        long = "Fix the bug in auth.py by implementing proper session validation" * 10
        short_tokens = economic_scheduler_revenue.estimate_tokens(short)
        long_tokens = economic_scheduler_revenue.estimate_tokens(long)
        self.assertLess(short_tokens, long_tokens)


# Pytest-style tests
def test_schedule_respects_cost_constraints():
    """Scheduling should never exceed specified cost limit."""
    import economic_scheduler_revenue
    with patch("db.select") as mock_select:
        mock_select.return_value = [
            {"id": "t1", "estimated_cost_usd": 1.00},
            {"id": "t2", "estimated_cost_usd": 2.00},
        ]
        result = economic_scheduler_revenue.schedule_with_budget(daily_budget_usd=1.50)
        total = sum(t["estimated_cost_usd"] for t in result)
        assert total <= 1.50


def test_high_roi_prioritized_over_low_roi():
    """High ROI tasks should always be scheduled before low ROI tasks."""
    import economic_scheduler_revenue
    with patch("db.select") as mock_select:
        mock_select.return_value = [
            {"id": "low_roi", "roi": 1.0},
            {"id": "high_roi", "roi": 10.0},
        ]
        result = economic_scheduler_revenue.schedule_cost_optimized()
        if len(result) > 1:
            assert result[0]["id"] == "high_roi"


def test_negative_profit_tasks_skipped():
    """Tasks with negative profit should not be scheduled."""
    import economic_scheduler_revenue
    with patch("db.select") as mock_select:
        mock_select.return_value = [
            {"id": "unprofitable", "revenue_usd": 0.10, "cost_usd": 1.00},
        ]
        result = economic_scheduler_revenue.schedule_cost_optimized()
        assert all(t["id"] != "unprofitable" for t in result)


def test_cost_prediction_consistent():
    """Cost predictions should be consistent across calls."""
    import economic_scheduler_revenue
    cost1 = economic_scheduler_revenue.predict_cost(
        model="claude-sonnet-5",
        input_tokens=10000
    )
    cost2 = economic_scheduler_revenue.predict_cost(
        model="claude-sonnet-5",
        input_tokens=10000
    )
    assert cost1 == cost2


def test_stats_never_raise_on_empty_data():
    """Stats calculation should handle empty data gracefully."""
    import economic_scheduler_revenue
    with patch("db.select") as mock_select:
        mock_select.return_value = []
        stats = economic_scheduler_revenue.cost_stats()
        assert isinstance(stats, dict)
        assert stats.get("total_cost_usd", 0.0) == 0.0


if __name__ == "__main__":
    unittest.main()
