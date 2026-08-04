"""
Tests for economic-scheduler-revenue: cost tracking and revenue calculation.

Validates token usage tracking, model-specific pricing, cache credit accounting,
and permission-aware cost attribution.
"""

import pytest
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ModelCost:
    """Model-specific pricing and token limits."""
    name: str
    input_rate_usd_per_mtok: float
    output_rate_usd_per_mtok: float
    cache_creation_rate_usd_per_mtok: float
    cache_read_rate_usd_per_mtok: float
    context_window: int
    max_output_tokens: int


@dataclass
class SessionUsage:
    """Token usage and cost for a single session."""
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    permission_denied_tool_count: int = 0


class EconomicScheduler:
    """Tracks and prices token usage across models."""

    MODELS = {
        # Rates match actual Anthropic billing (verified against the error-report
        # session in TestEconomicSchedulerRealWorldSession — the previous
        # 0.80/4.0 Haiku rates under-reported real cost by 20%).
        "claude-haiku-4-5-20251001": ModelCost(
            name="claude-haiku-4-5-20251001",
            input_rate_usd_per_mtok=1.0,
            output_rate_usd_per_mtok=5.0,
            cache_creation_rate_usd_per_mtok=1.25,
            cache_read_rate_usd_per_mtok=0.1,
            context_window=200000,
            max_output_tokens=32000,
        ),
        "claude-sonnet-4-6": ModelCost(
            name="claude-sonnet-4-6",
            input_rate_usd_per_mtok=3.0,
            output_rate_usd_per_mtok=15.0,
            # 1-hour cache write rate (2x input); the fleet's sessions bill at
            # the 1h tier per the error report (5m tier would be 3.75).
            cache_creation_rate_usd_per_mtok=6.0,
            cache_read_rate_usd_per_mtok=0.30,
            context_window=200000,
            max_output_tokens=32000,
        ),
    }

    def calculate_cost(self, model_name: str, usage: SessionUsage) -> float:
        """
        Calculate total cost for a session.

        Args:
            model_name: Model identifier
            usage: Token usage breakdown

        Returns:
            Total cost in USD (rounded to 8 decimals)
        """
        if model_name not in self.MODELS:
            raise ValueError(f"Unknown model: {model_name}")

        model = self.MODELS[model_name]

        input_cost = (usage.input_tokens / 1_000_000) * model.input_rate_usd_per_mtok
        output_cost = (usage.output_tokens / 1_000_000) * model.output_rate_usd_per_mtok
        cache_creation_cost = (
            (usage.cache_creation_input_tokens / 1_000_000)
            * model.cache_creation_rate_usd_per_mtok
        )
        cache_read_cost = (
            (usage.cache_read_input_tokens / 1_000_000)
            * model.cache_read_rate_usd_per_mtok
        )

        total = input_cost + output_cost + cache_creation_cost + cache_read_cost
        return round(total, 8)

    def validate_context_usage(self, model_name: str, total_input: int) -> bool:
        """Check if total input fits within context window."""
        if model_name not in self.MODELS:
            return False
        return total_input <= self.MODELS[model_name].context_window


class TestEconomicSchedulerBasic:
    """Basic cost calculation tests."""

    def test_zero_usage_costs_zero(self):
        """Zero tokens should cost zero."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", usage)
        assert cost == 0.0

    def test_input_tokens_only(self):
        """Only input tokens contribute to cost."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=1_000_000,  # 1M tokens
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", usage)
        # Haiku: 1.0M * 1.00 = 1.00 USD
        assert cost == 1.0

    def test_output_tokens_only(self):
        """Only output tokens contribute to cost."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=0,
            output_tokens=1_000_000,  # 1M tokens
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", usage)
        # Haiku: 1.0M * 5.0 = 5.0 USD
        assert cost == 5.0


class TestEconomicSchedulerCaching:
    """Cache read/creation cost tests."""

    def test_cache_creation_cost(self):
        """Cache creation tokens are charged at creation rate."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=1_000_000,  # 1M tokens
        )
        cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", usage)
        # Haiku: 1.0M * 1.25 = 1.25 USD (5m cache write = 1.25x input)
        assert cost == 1.25

    def test_cache_read_cost(self):
        """Cache read tokens are charged at read rate (90% discount)."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=1_000_000,  # 1M tokens
            cache_creation_input_tokens=0,
        )
        cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", usage)
        # Haiku: 1.0M * 0.1 = 0.1 USD
        assert cost == 0.1

    def test_cache_hit_savings(self):
        """Verify cache reads cost 90% less than creating."""
        scheduler = EconomicScheduler()

        creation_usage = SessionUsage(
            input_tokens=0, output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=10_000_000,
        )
        creation_cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", creation_usage)

        read_usage = SessionUsage(
            input_tokens=0, output_tokens=0,
            cache_read_input_tokens=10_000_000,
            cache_creation_input_tokens=0,
        )
        read_cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", read_usage)

        # Cache read (0.10) is 90% cheaper than the INPUT rate (1.00) and 92%
        # cheaper than the 5m cache-write rate (1.25).
        assert read_cost == pytest.approx(creation_cost * (0.1 / 1.25))
        assert read_cost < creation_cost


class TestEconomicSchedulerMultiModel:
    """Multi-model cost comparison tests."""

    def test_haiku_vs_sonnet_input_cost(self):
        """Sonnet is more expensive than Haiku for input."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=1_000_000,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )

        haiku_cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", usage)
        sonnet_cost = scheduler.calculate_cost("claude-sonnet-4-6", usage)

        # Haiku: 0.80, Sonnet: 3.0
        assert sonnet_cost > haiku_cost
        assert sonnet_cost == 3.0

    def test_haiku_vs_sonnet_cache_read(self):
        """Sonnet has higher cache read rate than Haiku."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=21_351_000,  # From error report
            cache_creation_input_tokens=0,
        )

        haiku_cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", usage)
        sonnet_cost = scheduler.calculate_cost("claude-sonnet-4-6", usage)

        assert sonnet_cost > haiku_cost

    def test_unknown_model_raises(self):
        """Unknown model should raise ValueError."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(input_tokens=100, output_tokens=0,
                            cache_read_input_tokens=0, cache_creation_input_tokens=0)

        with pytest.raises(ValueError, match="Unknown model"):
            scheduler.calculate_cost("claude-gpt-5000", usage)


class TestEconomicSchedulerContextWindow:
    """Context window validation tests."""

    def test_within_context_window(self):
        """Input within context limit should pass."""
        scheduler = EconomicScheduler()
        total_input = 100_000  # Well within 200k
        assert scheduler.validate_context_usage("claude-haiku-4-5-20251001", total_input)

    def test_at_context_window_boundary(self):
        """Input at exact context limit should pass."""
        scheduler = EconomicScheduler()
        total_input = 200_000  # Exactly at limit
        assert scheduler.validate_context_usage("claude-haiku-4-5-20251001", total_input)

    def test_exceeds_context_window(self):
        """Input exceeding context limit should fail."""
        scheduler = EconomicScheduler()
        total_input = 200_001  # One over limit
        assert not scheduler.validate_context_usage("claude-haiku-4-5-20251001", total_input)


class TestEconomicSchedulerRealWorldSession:
    """Tests based on actual error report data from spec."""

    def test_haiku_cost_from_session(self):
        """Verify Haiku cost calculation against session data."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=1113,
            output_tokens=17,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", usage)
        expected = 0.001198  # From error report
        assert abs(cost - expected) < 0.0001

    def test_sonnet_cost_from_session(self):
        """Verify Sonnet cost calculation against session data."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=3,
            output_tokens=382,
            cache_read_input_tokens=21351,
            cache_creation_input_tokens=3496,
        )
        cost = scheduler.calculate_cost("claude-sonnet-4-6", usage)
        expected = 0.0331203  # From error report
        assert abs(cost - expected) < 0.0001

    def test_combined_session_cost(self):
        """Total session cost matches reported cost."""
        scheduler = EconomicScheduler()

        haiku_usage = SessionUsage(
            input_tokens=1113, output_tokens=17,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        )
        haiku_cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", haiku_usage)

        sonnet_usage = SessionUsage(
            input_tokens=3, output_tokens=382,
            cache_read_input_tokens=21351, cache_creation_input_tokens=3496,
        )
        sonnet_cost = scheduler.calculate_cost("claude-sonnet-4-6", sonnet_usage)

        total = haiku_cost + sonnet_cost
        expected_total = 0.0343183  # From error report
        assert abs(total - expected_total) < 0.0001


class TestEconomicSchedulerPermissionAwareness:
    """Tests for permission-aware cost tracking."""

    def test_permission_denial_tracking(self):
        """Sessions with permission denials should be tracked."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=1000,
            output_tokens=100,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            permission_denied_tool_count=1,  # Bash tool denied
        )
        cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", usage)

        # Cost should still be calculated correctly despite permission denial
        assert cost > 0
        assert usage.permission_denied_tool_count == 1

    def test_zero_turns_due_to_permission(self):
        """Sessions cut short by permissions should reflect in token count."""
        scheduler = EconomicScheduler()

        # Minimal usage suggests session was cut short
        usage = SessionUsage(
            input_tokens=3,
            output_tokens=382,
            cache_read_input_tokens=21351,
            cache_creation_input_tokens=3496,
            permission_denied_tool_count=1,
        )
        cost = scheduler.calculate_cost("claude-sonnet-4-6", usage)

        # Should still have some cost despite low input
        assert cost > 0.01


class TestEconomicSchedulerEdgeCases:
    """Edge case and boundary tests."""

    def test_large_token_counts(self):
        """Handles large token counts correctly."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=200_000_000,  # 200M tokens
            output_tokens=32_000,  # Max output
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        cost = scheduler.calculate_cost("claude-haiku-4-5-20251001", usage)
        # Should calculate without overflow
        assert cost > 0
        assert isinstance(cost, float)

    def test_all_cache_read_scenario(self):
        """Session using only cached content."""
        scheduler = EconomicScheduler()
        usage = SessionUsage(
            input_tokens=0,
            output_tokens=1000,
            cache_read_input_tokens=100_000,
            cache_creation_input_tokens=0,
        )
        cost = scheduler.calculate_cost("claude-sonnet-4-6", usage)

        # Mostly cheap cache reads + small output
        expected = ((100_000 / 1_000_000) * 0.30) + ((1000 / 1_000_000) * 15.0)
        assert abs(cost - expected) < 0.0001

    def test_model_context_validation_invalid_model(self):
        """Validation returns False for unknown model."""
        scheduler = EconomicScheduler()
        assert not scheduler.validate_context_usage("unknown-model", 1000)
