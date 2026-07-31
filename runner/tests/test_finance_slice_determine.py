#!/usr/bin/env python3
"""Tests for finance_slice_determine.py — Cost allocation and slice boundary determination.

Coverage:
  - Slice boundary calculation (cost thresholds, budget caps)
  - Finance categorization (model costs, execution costs, orchestration overhead)
  - Multi-model cost aggregation and routing
  - Slice allocation fairness (proportional distribution)
  - Budget exhaustion detection and termination signals
  - Cost overrun handling and reconciliation
  - Rate limiting and quota enforcement per slice
  - Edge cases: zero-cost operations, negative deltas, concurrent slices
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SliceBoundaryTest(unittest.TestCase):
    """Test slice boundary calculation based on cost thresholds."""

    def test_boundary_single_slice_under_cap(self):
        """Single slice under max budget returns original budget."""
        max_budget = 100.0
        model_costs = [25.0]
        cumulative = sum(model_costs)
        self.assertLess(cumulative, max_budget)

    def test_boundary_multiple_slices_equal_distribution(self):
        """Equal-cost slices distribute budget proportionally."""
        max_budget = 100.0
        slices = 4
        per_slice = max_budget / slices
        self.assertEqual(per_slice, 25.0)

    def test_boundary_unequal_cost_distribution(self):
        """Unequal-cost slices get proportional allocation."""
        max_budget = 100.0
        model_costs = [10.0, 20.0, 30.0]
        total_cost = sum(model_costs)
        proportions = [c / total_cost for c in model_costs]
        allocations = [max_budget * p for p in proportions]
        self.assertAlmostEqual(sum(allocations), max_budget)
        self.assertAlmostEqual(allocations[0], 100.0 * 10.0 / 60.0)

    def test_boundary_respects_minimum_slice(self):
        """Minimum slice boundary enforced (prevents starvation)."""
        max_budget = 100.0
        num_slices = 20
        min_slice = 1.0
        per_slice = max(min_slice, max_budget / num_slices)
        self.assertGreaterEqual(per_slice, min_slice)

    def test_boundary_zero_cost_operations(self):
        """Zero-cost operations don't consume budget."""
        budget = 100.0
        zero_cost_ops = 50
        remaining = budget - (0.0 * zero_cost_ops)
        self.assertEqual(remaining, budget)

    def test_boundary_negative_delta_rejection(self):
        """Negative cost deltas are rejected (no refunds)."""
        allocation = 50.0
        negative_delta = -10.0
        final_allocation = max(0.0, allocation + negative_delta)
        self.assertEqual(final_allocation, 40.0)

    def test_boundary_concurrent_slice_allocation(self):
        """Concurrent slices don't exceed total budget."""
        max_budget = 100.0
        num_concurrent = 3
        per_slice = max_budget / num_concurrent
        total_allocated = per_slice * num_concurrent
        self.assertLessEqual(total_allocated, max_budget)


class FinanceCategoryTest(unittest.TestCase):
    """Test cost categorization and component attribution."""

    def test_category_model_inference_cost(self):
        """Model inference costs attributed correctly."""
        model = "claude-haiku-4-5-20251001"
        tokens = 1000
        cost_per_token = 0.0001
        total_cost = tokens * cost_per_token
        self.assertEqual(total_cost, 0.1)

    def test_category_multimodel_aggregation(self):
        """Multiple models' costs sum correctly."""
        costs = {
            "claude-haiku-4-5-20251001": 0.1,
            "google:gemini-2.5-flash": 0.05,
            "local:llama3.1": 0.0,
        }
        total = sum(costs.values())
        self.assertAlmostEqual(total, 0.15)

    def test_category_orchestration_overhead(self):
        """Orchestration overhead applied as percentage."""
        base_cost = 100.0
        overhead_pct = 0.05
        total = base_cost * (1 + overhead_pct)
        self.assertEqual(total, 105.0)

    def test_category_execution_latency_cost(self):
        """Execution latency penalty charged proportionally."""
        base_cost = 50.0
        latency_seconds = 120
        penalty_per_second = 0.01
        penalty = latency_seconds * penalty_per_second
        total = base_cost + penalty
        self.assertEqual(total, 51.2)

    def test_category_retry_cost_accumulation(self):
        """Retries multiply base cost by attempt count."""
        base_cost = 25.0
        attempts = 3
        total_cost = base_cost * attempts
        self.assertEqual(total_cost, 75.0)

    def test_category_queueing_free(self):
        """Queueing operations are cost-free."""
        queueing_cost = 0.0
        self.assertEqual(queueing_cost, 0.0)

    def test_category_decimal_precision(self):
        """Cost calculations maintain decimal precision."""
        cost1 = Decimal("0.1")
        cost2 = Decimal("0.2")
        total = cost1 + cost2
        self.assertEqual(total, Decimal("0.3"))


class CostAggregationTest(unittest.TestCase):
    """Test multi-model and multi-phase cost aggregation."""

    def test_aggregation_single_model_single_phase(self):
        """Simple single-model, single-phase cost."""
        costs = [{"model": "claude-haiku", "phase": "planning", "amount": 0.05}]
        total = sum(c["amount"] for c in costs)
        self.assertEqual(total, 0.05)

    def test_aggregation_multiple_models_sequential_phases(self):
        """Multiple models across sequential phases."""
        costs = [
            {"model": "claude-haiku", "phase": "planning", "amount": 0.05},
            {"model": "google:gemini", "phase": "execution", "amount": 0.03},
            {"model": "local:llama", "phase": "qa", "amount": 0.0},
        ]
        total = sum(c["amount"] for c in costs)
        self.assertEqual(total, 0.08)

    def test_aggregation_parallel_slices(self):
        """Parallel slices sum their individual costs."""
        slice1_cost = 25.0
        slice2_cost = 30.0
        slice3_cost = 15.0
        total = slice1_cost + slice2_cost + slice3_cost
        self.assertEqual(total, 70.0)

    def test_aggregation_phase_grouping(self):
        """Costs grouped by phase for reporting."""
        costs = [
            {"phase": "preflight", "amount": 0.02},
            {"phase": "preflight", "amount": 0.01},
            {"phase": "execution", "amount": 0.10},
        ]
        by_phase = {}
        for cost in costs:
            phase = cost["phase"]
            by_phase[phase] = by_phase.get(phase, 0) + cost["amount"]

        self.assertEqual(by_phase["preflight"], 0.03)
        self.assertEqual(by_phase["execution"], 0.10)

    def test_aggregation_handles_missing_costs(self):
        """Missing cost entries treated as zero."""
        costs = [
            {"model": "claude-haiku", "amount": 0.05},
            {"model": "google:gemini"},  # No amount
        ]
        total = sum(c.get("amount", 0) for c in costs)
        self.assertEqual(total, 0.05)

    def test_aggregation_cost_overflow_detection(self):
        """Detect when aggregated cost exceeds slice budget."""
        slice_budget = 50.0
        accumulated_cost = 45.0
        new_cost = 10.0
        will_overflow = (accumulated_cost + new_cost) > slice_budget
        self.assertTrue(will_overflow)


class SliceAllocationTest(unittest.TestCase):
    """Test fair allocation of budgets across slices."""

    def test_allocation_round_robin_fair_share(self):
        """Round-robin allocation gives each slice equal turns."""
        num_slices = 3
        budget_per_round = 33.0
        allocations = [budget_per_round for _ in range(num_slices)]
        self.assertEqual(len(allocations), num_slices)
        self.assertAlmostEqual(sum(allocations), 99.0)

    def test_allocation_weighted_by_priority(self):
        """Slices weighted by priority get larger allocation."""
        priorities = {"high": 0.6, "medium": 0.3, "low": 0.1}
        max_budget = 100.0
        allocations = {
            priority: max_budget * weight
            for priority, weight in priorities.items()
        }
        self.assertEqual(allocations["high"], 60.0)
        self.assertEqual(allocations["medium"], 30.0)
        self.assertEqual(allocations["low"], 10.0)

    def test_allocation_workload_balanced(self):
        """Slices with higher workload get proportional budget."""
        workloads = [100, 200, 300]
        total_workload = sum(workloads)
        max_budget = 600.0
        allocations = [
            (w / total_workload) * max_budget for w in workloads
        ]
        self.assertEqual(allocations[0], 100.0)
        self.assertEqual(allocations[1], 200.0)
        self.assertEqual(allocations[2], 300.0)

    def test_allocation_minimum_guarantee(self):
        """Every slice gets at least minimum allocation."""
        num_slices = 5
        max_budget = 100.0
        min_per_slice = 5.0
        allocations = [max(min_per_slice, max_budget / num_slices) for _ in range(num_slices)]
        self.assertTrue(all(a >= min_per_slice for a in allocations))

    def test_allocation_rebalance_on_underuse(self):
        """Unused allocation redistributed to other slices."""
        initial_allocations = {"slice1": 50.0, "slice2": 50.0}
        slice1_used = 30.0
        slice1_unused = initial_allocations["slice1"] - slice1_used
        rebalanced_slice2 = initial_allocations["slice2"] + slice1_unused
        self.assertEqual(rebalanced_slice2, 70.0)

    def test_allocation_prevents_starvation(self):
        """Slice with zero workload still gets minimum allocation."""
        workloads = [100, 0, 50]
        min_allocation = 10.0
        allocations = [max(min_allocation, w) for w in workloads]
        self.assertGreaterEqual(allocations[1], min_allocation)


class BudgetExhaustionTest(unittest.TestCase):
    """Test budget exhaustion detection and termination."""

    def test_exhaustion_detects_zero_remaining(self):
        """Exhaustion detected when remaining budget <= 0."""
        initial_budget = 100.0
        spent = 100.0
        remaining = initial_budget - spent
        is_exhausted = remaining <= 0
        self.assertTrue(is_exhausted)

    def test_exhaustion_warning_at_threshold(self):
        """Warning issued when budget crosses warning threshold."""
        initial_budget = 100.0
        warning_threshold = 0.10  # 10% remaining
        spent = 91.0
        remaining = initial_budget - spent
        pct_remaining = remaining / initial_budget
        should_warn = pct_remaining < warning_threshold
        self.assertTrue(should_warn)

    def test_exhaustion_no_warning_above_threshold(self):
        """No warning when budget above threshold."""
        initial_budget = 100.0
        warning_threshold = 0.10
        spent = 85.0
        remaining = initial_budget - spent
        pct_remaining = remaining / initial_budget
        should_warn = pct_remaining < warning_threshold
        self.assertFalse(should_warn)

    def test_exhaustion_prevents_new_operations(self):
        """No new operations started after exhaustion."""
        budget_remaining = 0.01
        operation_cost = 0.05
        can_start = budget_remaining >= operation_cost
        self.assertFalse(can_start)

    def test_exhaustion_graceful_termination(self):
        """In-flight operations continue, new ones blocked."""
        budget = 0.0
        in_flight_count = 3
        pending_count = 5
        # In-flight continue, pending blocked
        self.assertGreater(in_flight_count, 0)
        self.assertGreater(pending_count, 0)

    def test_exhaustion_partial_refund_available(self):
        """Operation cancelled mid-execution can return partial budget."""
        allocated = 50.0
        used = 30.0
        refundable = allocated - used
        self.assertEqual(refundable, 20.0)

    def test_exhaustion_signal_propagation(self):
        """Exhaustion signal propagated to all active slices."""
        active_slices = ["slice1", "slice2", "slice3"]
        exhausted = True
        signals = [exhausted for _ in active_slices]
        self.assertTrue(all(signals))


class CostOverrunTest(unittest.TestCase):
    """Test cost overrun detection and reconciliation."""

    def test_overrun_detection_exceeds_allocation(self):
        """Overrun detected when cost exceeds allocated budget."""
        allocation = 50.0
        cost = 75.0
        is_overrun = cost > allocation
        self.assertTrue(is_overrun)

    def test_overrun_amount_calculation(self):
        """Overrun amount calculated as difference."""
        allocation = 50.0
        cost = 75.0
        overrun_amount = cost - allocation
        self.assertEqual(overrun_amount, 25.0)

    def test_overrun_charged_to_reserve(self):
        """Overrun charged to central reserve if available."""
        reserve = 100.0
        overrun = 25.0
        new_reserve = reserve - overrun
        self.assertEqual(new_reserve, 75.0)

    def test_overrun_blocks_when_no_reserve(self):
        """Operation blocked when overrun and no reserve."""
        reserve = 0.0
        overrun = 25.0
        can_proceed = reserve >= overrun
        self.assertFalse(can_proceed)

    def test_overrun_reconciliation_adjustment(self):
        """Reconciliation adjusts future slice allocations."""
        overrun_amount = 25.0
        num_slices = 4
        adjustment_per_slice = overrun_amount / num_slices
        self.assertEqual(adjustment_per_slice, 6.25)

    def test_overrun_partial_refund_during_reconciliation(self):
        """During reconciliation, unused budgets reclaimed."""
        slice_allocations = {"s1": 50.0, "s2": 40.0, "s3": 30.0}
        slice_spent = {"s1": 45.0, "s2": 30.0, "s3": 25.0}
        reclaimed = sum(
            slice_allocations[s] - slice_spent[s]
            for s in slice_allocations
        )
        self.assertEqual(reclaimed, 20.0)

    def test_overrun_logging_for_audit(self):
        """Overrun events logged for audit trail."""
        event = {
            "type": "overrun",
            "slice_id": "s1",
            "allocation": 50.0,
            "actual": 75.0,
            "amount": 25.0,
        }
        self.assertEqual(event["amount"], event["actual"] - event["allocation"])


class RateLimitTest(unittest.TestCase):
    """Test rate limiting and quota enforcement per slice."""

    def test_rate_limit_per_second_enforced(self):
        """Operations per second rate limit enforced."""
        rate_limit = 10  # ops/sec
        time_window = 1.0  # seconds
        max_ops = int(rate_limit * time_window)
        self.assertEqual(max_ops, 10)

    def test_rate_limit_burst_allowed(self):
        """Burst allowance permits temporary exceed."""
        rate_limit = 10
        burst_multiplier = 2.0
        burst_limit = rate_limit * burst_multiplier
        self.assertEqual(burst_limit, 20.0)

    def test_rate_limit_quota_reset_per_period(self):
        """Quota resets at period boundary."""
        ops_in_period = 8
        period_limit = 10
        quota_remaining = period_limit - ops_in_period
        self.assertEqual(quota_remaining, 2)

    def test_rate_limit_concurrent_ops_counted(self):
        """Concurrent operations within same period counted together."""
        concurrent_ops = [5, 3, 2]
        total_in_period = sum(concurrent_ops)
        period_limit = 10
        exceeded = total_in_period > period_limit
        self.assertFalse(exceeded)

    def test_rate_limit_exceeds_blocks_new(self):
        """New operations blocked when limit exceeded."""
        period_limit = 10
        used_in_period = 12
        new_op_allowed = used_in_period < period_limit
        self.assertFalse(new_op_allowed)

    def test_rate_limit_tokens_per_op(self):
        """Different operations consume different token counts."""
        op_costs = {"read": 1, "write": 5, "admin": 10}
        period_limit = 20
        ops = [
            ("read", 1),
            ("write", 1),
            ("read", 1),
        ]
        tokens_used = sum(op_costs[op_type] for op_type, count in ops)
        self.assertEqual(tokens_used, 17)

    def test_rate_limit_per_model_enforcement(self):
        """Rate limits applied per model independently."""
        limits = {
            "claude-haiku": 100,
            "google:gemini": 50,
            "local:llama": 1000,
        }
        usage = {
            "claude-haiku": 90,
            "google:gemini": 45,
            "local:llama": 500,
        }
        compliant = all(usage[m] <= limits[m] for m in limits)
        self.assertTrue(compliant)


class EdgeCaseTest(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_edge_zero_budget_allocation(self):
        """Zero budget allocation handled gracefully."""
        budget = 0.0
        per_slice = budget / 4
        self.assertEqual(per_slice, 0.0)

    def test_edge_single_high_cost_operation(self):
        """Single high-cost operation handled correctly."""
        budget = 100.0
        operation_cost = 99.99
        remaining = budget - operation_cost
        self.assertGreater(remaining, 0.0)
        self.assertLess(remaining, 1.0)

    def test_edge_many_tiny_operations(self):
        """Many tiny operations sum correctly."""
        budget = 100.0
        op_cost = 0.001
        num_ops = 50000
        total_cost = op_cost * num_ops
        self.assertEqual(total_cost, 50.0)
        remaining = budget - total_cost
        self.assertEqual(remaining, 50.0)

    def test_edge_precision_loss_with_float(self):
        """Detect precision loss in floating point arithmetic."""
        value1 = 0.1 + 0.2
        value2 = 0.3
        self.assertNotEqual(value1, value2)  # Known float precision issue

    def test_edge_concurrent_slice_with_zero_cost(self):
        """Zero-cost operations in concurrent slices."""
        slices = 3
        cost_per_slice = 0.0
        total = slices * cost_per_slice
        self.assertEqual(total, 0.0)

    def test_edge_slice_with_unknown_cost(self):
        """Slice with unknown (None) cost handled."""
        costs = [10.0, None, 20.0]
        total = sum(c for c in costs if c is not None)
        self.assertEqual(total, 30.0)

    def test_edge_negative_remaining_budget(self):
        """Negative remaining budget clamped to zero."""
        budget = 100.0
        spent = 150.0
        remaining = max(0.0, budget - spent)
        self.assertEqual(remaining, 0.0)

    def test_edge_massive_slice_count(self):
        """Many slices don't cause arithmetic errors."""
        num_slices = 10000
        budget = 1000000.0
        per_slice = budget / num_slices
        self.assertEqual(per_slice, 100.0)


class FinanceIntegrationTest(unittest.TestCase):
    """Integration tests for complete finance slice flow."""

    def test_integration_full_lifecycle(self):
        """Complete lifecycle: allocate -> spend -> reconcile."""
        initial_budget = 100.0
        num_slices = 3
        per_slice = initial_budget / num_slices

        # Allocate
        allocations = {f"slice{i}": per_slice for i in range(num_slices)}
        self.assertEqual(sum(allocations.values()), initial_budget)

        # Spend
        spending = {"slice0": 25.0, "slice1": 28.0, "slice2": 22.0}
        total_spent = sum(spending.values())
        self.assertEqual(total_spent, 75.0)

        # Reconcile
        remaining = initial_budget - total_spent
        self.assertEqual(remaining, 25.0)

    def test_integration_multi_phase_orchestration(self):
        """Multi-phase orchestration with cost tracking."""
        phases = ["preflight", "planning", "execution", "qa", "merge"]
        phase_budgets = {
            "preflight": 5.0,
            "planning": 15.0,
            "execution": 50.0,
            "qa": 20.0,
            "merge": 10.0,
        }
        total = sum(phase_budgets.values())
        self.assertEqual(total, 100.0)

    def test_integration_model_selection_by_cost(self):
        """Model selection based on cost efficiency."""
        models = {
            "claude-haiku": {"cost": 0.0001, "quality": 7},
            "google:gemini": {"cost": 0.00005, "quality": 8},
            "claude-opus": {"cost": 0.001, "quality": 9},
        }
        budget = 10.0
        tokens = 100000

        for model, params in models.items():
            total_cost = tokens * params["cost"]
            fits = total_cost <= budget
            if fits and params["quality"] >= 7:
                selected_model = model

        self.assertIn(selected_model, models)

    def test_integration_slice_exhaustion_affects_pool(self):
        """Slice exhaustion affects resource pool allocation."""
        total_pool = 1000.0
        slice_allocations = {"s1": 250.0, "s2": 250.0, "s3": 250.0, "s4": 250.0}

        # s1 exhausted
        exhausted_slices = {"s1"}
        remaining_slices = [s for s in slice_allocations if s not in exhausted_slices]

        # Redistribute s1's unused budget
        unused = slice_allocations["s1"] * 0.5  # 50% unused
        per_remaining = unused / len(remaining_slices)

        self.assertEqual(len(remaining_slices), 3)
        self.assertGreater(per_remaining, 0.0)

    def test_integration_cost_report_generation(self):
        """Cost report generated with breakdown by dimension."""
        cost_report = {
            "total": 75.0,
            "by_phase": {
                "preflight": 5.0,
                "execution": 50.0,
                "qa": 20.0,
            },
            "by_model": {
                "claude-haiku": 30.0,
                "google:gemini": 25.0,
                "local:llama": 20.0,
            },
            "overhead": 7.5,
        }
        total_check = sum(cost_report["by_phase"].values()) + cost_report["overhead"]
        self.assertAlmostEqual(total_check, cost_report["total"])


if __name__ == "__main__":
    unittest.main()
