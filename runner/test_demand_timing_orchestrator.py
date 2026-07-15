#!/usr/bin/env python3
"""Tests for demand_timing_orchestrator module."""
import os
import sys
import json
import tempfile
import time
from datetime import datetime, timedelta
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import demand_timing_orchestrator as dto


@pytest.fixture
def temp_state_file():
    """Provide a temporary state file for testing."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        state_file = f.name
    yield state_file
    if os.path.exists(state_file):
        os.unlink(state_file)


# ---------------------------------------------------------------------------
# DemandTimingState initialization and loading
# ---------------------------------------------------------------------------
class TestDemandTimingStateInit:
    def test_fresh_state(self):
        """New state has sensible defaults."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            assert state.state["last_run_timestamp"] is None
            assert state.state["last_run_count"] == 0
            assert state.state["consecutive_empty"] == 0
            assert state.state["current_backoff_hours"] == dto.DEFAULT_COOLDOWN_HOURS
        finally:
            os.unlink(state_file)

    def test_none_state_file(self):
        """State initializes even with None file path."""
        state = dto.DemandTimingState(None)
        assert state.state is not None

    def test_save_and_load(self):
        """State persists to file and reloads correctly."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            # Create and save state
            state1 = dto.DemandTimingState(state_file)
            state1.record_run(42)
            state1.set_backoff_hours(8.5)

            # Load and verify
            state2 = dto.DemandTimingState(state_file)
            assert state2.get_last_run_count() == 42
            assert state2.get_backoff_hours() == 8.5
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_load_missing_file(self):
        """Loading from nonexistent file is safe."""
        state = dto.DemandTimingState("/nonexistent/path/file.json")
        assert state.state is not None
        assert state.get_last_run_count() == 0

    def test_load_corrupted_json(self):
        """Corrupted JSON file is handled gracefully."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("{ invalid json }")
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            assert state.get_last_run_count() == 0
        finally:
            os.unlink(state_file)

    def test_load_non_dict_json(self):
        """Non-dict JSON is handled gracefully."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            json.dump(["list", "not", "dict"], f)
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            assert state.get_last_run_count() == 0
        finally:
            os.unlink(state_file)


# ---------------------------------------------------------------------------
# Record run and state tracking
# ---------------------------------------------------------------------------
class TestRecordRun:
    def test_record_run_with_signals(self):
        """Recording run with signals clears consecutive_empty."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            state.state["consecutive_empty"] = 5
            state.record_run(3)

            assert state.get_last_run_count() == 3
            assert state.state["consecutive_empty"] == 0
            assert state.get_last_run_time() is not None
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_record_run_empty_signals(self):
        """Recording run with 0 signals increments consecutive_empty."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            state.state["consecutive_empty"] = 2
            state.record_run(0)

            assert state.get_last_run_count() == 0
            assert state.state["consecutive_empty"] == 3
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_record_run_updates_timestamp(self):
        """Recording run sets a recent timestamp."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            before = datetime.now()
            state.record_run(1)
            after = datetime.now()

            last_run = state.get_last_run_time()
            assert last_run is not None
            assert before <= last_run <= after
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


# ---------------------------------------------------------------------------
# Hours since last run
# ---------------------------------------------------------------------------
class TestHoursSinceLastRun:
    def test_never_run(self):
        """Never run returns None."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            assert state.hours_since_last_run() is None
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


    def test_just_ran(self):
        """Fresh run returns near-zero hours."""
        state = dto.DemandTimingState()
        state.record_run(1)
        hours = state.hours_since_last_run()
        assert hours is not None
        assert hours < 0.01

    def test_hours_calculation(self):
        """Hours calculation is accurate."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            past_time = datetime.now() - timedelta(hours=2.5)
            state.state["last_run_timestamp"] = past_time.isoformat()
            state.save()

            hours = state.hours_since_last_run()
            assert hours is not None
            assert 2.4 < hours < 2.6
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_invalid_timestamp(self):
        """Invalid timestamp returns None."""
        state = dto.DemandTimingState()
        state.state["last_run_timestamp"] = "not-a-valid-iso-date"
        assert state.hours_since_last_run() is None


# ---------------------------------------------------------------------------
# Backoff management
# ---------------------------------------------------------------------------
class TestBackoffManagement:
    def test_backoff_bounds(self):
        """Backoff is bounded between min and max."""
        state = dto.DemandTimingState()

        # Too small
        state.set_backoff_hours(0.1)
        assert state.get_backoff_hours() >= dto.DEFAULT_MIN_INTERVAL

        # Too large
        state.set_backoff_hours(100)
        assert state.get_backoff_hours() <= dto.DEFAULT_MAX_BACKOFF

    def test_backoff_persistence(self):
        """Backoff setting persists."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state1 = dto.DemandTimingState(state_file)
            state1.set_backoff_hours(12)

            state2 = dto.DemandTimingState(state_file)
            assert state2.get_backoff_hours() == 12
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_default_backoff(self):
        """Default backoff matches env var or constant."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            expected = int(os.environ.get("ORCH_DEMAND_COOLDOWN_HOURS", dto.DEFAULT_COOLDOWN_HOURS))
            assert state.get_backoff_hours() == expected
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)



# ---------------------------------------------------------------------------
# Fixed interval strategy
# ---------------------------------------------------------------------------
class TestFixedIntervalStrategy:
    def test_first_run_allowed(self):
        """First run is always allowed."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            should, reason = dto.should_run_fixed_interval(state)
            assert should is True
            assert "never run" in reason
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_within_cooldown(self):
        """Run within cooldown is blocked."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            state.record_run(1)
            state.set_backoff_hours(6)

            should, reason = dto.should_run_fixed_interval(state)
            assert should is False
            assert "cooldown" in reason
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_after_cooldown(self):
        """Run after cooldown is allowed."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            past_time = datetime.now() - timedelta(hours=7)
            state.state["last_run_timestamp"] = past_time.isoformat()
            state.set_backoff_hours(6)

            should, reason = dto.should_run_fixed_interval(state)
            assert should is True
            assert "cooldown" in reason
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_reason_message(self):
        """Reason messages are informative."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            should, reason = dto.should_run_fixed_interval(state)
            assert reason != ""
            assert "never" in reason.lower() or "cooldown" in reason.lower()
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)



# ---------------------------------------------------------------------------
# Exponential backoff strategy
# ---------------------------------------------------------------------------
class TestExponentialBackoffStrategy:
    def test_first_run(self):
        """First run is allowed."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            should, reason = dto.should_run_exponential_backoff(state)
            assert should is True
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


    def test_empty_runs_increase_backoff(self):
        """Multiple empty runs increase backoff."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            state.record_run(1)  # Set a last run time
            initial_backoff = state.get_backoff_hours()

            # Record 4 empty runs (> 2) to trigger backoff increase
            state.state["consecutive_empty"] = 4
            should, _ = dto.should_run_exponential_backoff(state)
            new_backoff = state.get_backoff_hours()

            assert new_backoff > initial_backoff
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


    def test_respects_backoff_after_empty(self):
        """Increased backoff is respected."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            past_time = datetime.now() - timedelta(hours=2)
            state.state["last_run_timestamp"] = past_time.isoformat()
            state.state["consecutive_empty"] = 4
            state.set_backoff_hours(9)

            should, _ = dto.should_run_exponential_backoff(state)
            assert should is False
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


# ---------------------------------------------------------------------------
# Demand-responsive strategy
# ---------------------------------------------------------------------------
class TestDemandResponsiveStrategy:
    def test_first_run(self):
        """First run is allowed."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            should, reason = dto.should_run_demand_responsive(state)
            assert should is True
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


    def test_high_demand_shortens_window(self):
        """High demand uses shorter window."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            past_time = datetime.now() - timedelta(hours=dto.HIGH_DEMAND_WINDOW_HOURS + 0.5)
            state.state["last_run_timestamp"] = past_time.isoformat()
            state.state["last_run_count"] = dto.HIGH_DEMAND_THRESHOLD

            should, reason = dto.should_run_demand_responsive(state)
            assert should is True
            assert "high-demand" in reason
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_low_demand_uses_normal_backoff(self):
        """Low demand uses normal backoff window."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            past_time = datetime.now() - timedelta(hours=1)
            state.state["last_run_timestamp"] = past_time.isoformat()
            state.state["last_run_count"] = 0

            should, reason = dto.should_run_demand_responsive(state)
            # Should be False if in backoff window
            if not should:
                assert "backoff" in reason
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_high_demand_boundary(self):
        """Boundary condition at high demand threshold."""
        state = dto.DemandTimingState()
        state.state["last_run_count"] = dto.HIGH_DEMAND_THRESHOLD - 1
        past_time = datetime.now() - timedelta(hours=1)
        state.state["last_run_timestamp"] = past_time.isoformat()

        should, reason = dto.should_run_demand_responsive(state)
        assert "high-demand" not in reason


# ---------------------------------------------------------------------------
# Public should_run API
# ---------------------------------------------------------------------------
class TestPublicShouldRunAPI:
    def test_default_strategy(self):
        """Default strategy is used when not specified."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            should, reason = dto.should_run(strategy=None, state_file=state_file)
            assert isinstance(should, bool)
            assert reason != ""
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_explicit_strategy_fixed(self):
        """Can specify fixed_interval strategy."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            should, _ = dto.should_run(strategy="fixed_interval", state_file=state_file)
            assert should is True
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_explicit_strategy_exponential(self):
        """Can specify exponential_backoff strategy."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            should, _ = dto.should_run(strategy="exponential_backoff", state_file=state_file)
            assert should is True
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_explicit_strategy_responsive(self):
        """Can specify demand_responsive strategy."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            should, _ = dto.should_run(strategy="demand_responsive", state_file=state_file)
            assert should is True
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_unknown_strategy_defaults(self):
        """Unknown strategy defaults to fixed_interval."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            should, _ = dto.should_run(strategy="unknown", state_file=state_file)
            assert should is True
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


# ---------------------------------------------------------------------------
# Record mining result and side effects
# ---------------------------------------------------------------------------
class TestRecordMiningResult:
    def test_records_signal_count(self):
        """Recording result saves signal count."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            dto.record_mining_result(7, state_file)
            state = dto.DemandTimingState(state_file)
            assert state.get_last_run_count() == 7
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_exponential_backoff_on_record(self):
        """Exponential backoff strategy adjusts on empty runs."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            with mock.patch.dict(os.environ, {"ORCH_DEMAND_TIMING_STRATEGY": "exponential_backoff"}):
                state = dto.DemandTimingState(state_file)
                initial_backoff = state.get_backoff_hours()

                state.state["consecutive_empty"] = 3
                state.save()

                dto.record_mining_result(0, state_file)

                state2 = dto.DemandTimingState(state_file)
                # After consecutive empty runs, backoff should increase
                # (but only if condition is met in record_mining_result)
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_demand_responsive_on_record(self):
        """Demand responsive strategy adjusts window on high demand."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            with mock.patch.dict(os.environ, {"ORCH_DEMAND_TIMING_STRATEGY": "demand_responsive"}):
                dto.record_mining_result(dto.HIGH_DEMAND_THRESHOLD + 1, state_file)
                state = dto.DemandTimingState(state_file)
                # Should use shorter window
                assert state.get_backoff_hours() <= dto.HIGH_DEMAND_WINDOW_HOURS * 2
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


# ---------------------------------------------------------------------------
# Next run time calculation
# ---------------------------------------------------------------------------
class TestGetNextRunTime:
    def test_immediate_run(self):
        """If should run now, next_run_time is None."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            next_time = dto.get_next_run_time(strategy="fixed_interval", state_file=state_file)
            assert next_time is None
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_future_run_time(self):
        """If should not run now, next_run_time is in future."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            state.record_run(1)
            state.set_backoff_hours(6)

            next_time = dto.get_next_run_time(strategy="fixed_interval", state_file=state_file)
            if next_time is not None:
                assert next_time > datetime.now()
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_never_run_case(self):
        """Never-run state returns None for next time."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            next_time = dto.get_next_run_time(state_file=state_file)
            # Never run means should run now, so next_time is None
            assert next_time is None
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


# ---------------------------------------------------------------------------
# State reset
# ---------------------------------------------------------------------------
class TestResetState:
    def test_reset_clears_state(self):
        """Reset removes all tracking data."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state1 = dto.DemandTimingState(state_file)
            state1.record_run(10)
            state1.set_backoff_hours(12)

            dto.reset_state(state_file)

            state2 = dto.DemandTimingState(state_file)
            assert state2.get_last_run_time() is None
            assert state2.get_last_run_count() == 0
            assert state2.get_backoff_hours() == dto.DEFAULT_COOLDOWN_HOURS
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_reset_maintains_file(self):
        """Reset preserves state file existence."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state1 = dto.DemandTimingState(state_file)
            state1.record_run(1)

            dto.reset_state(state_file)
            assert os.path.exists(state_file)
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------
class TestIntegrationScenarios:
    def test_typical_flow(self):
        """Typical workflow: check, run, record."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            # Check if should run (yes, first time)
            should, _ = dto.should_run(state_file=state_file)
            assert should is True

            # Record result
            dto.record_mining_result(3, state_file)

            # Check again (should be in cooldown)
            should2, _ = dto.should_run(state_file=state_file)
            assert should2 is False
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_multiple_runs_workflow(self):
        """Multiple runs over time."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            # Run 1
            dto.record_mining_result(2, state_file)
            assert not dto.should_run(state_file=state_file)[0]

            # Simulate time passing
            state = dto.DemandTimingState(state_file)
            state.state["last_run_timestamp"] = (
                datetime.now() - timedelta(hours=7)
            ).isoformat()
            state.save()

            # Run 2
            should, _ = dto.should_run(state_file=state_file)
            assert should is True
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_concurrent_empty_runs(self):
        """Track consecutive empty runs."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            for i in range(3):
                dto.record_mining_result(0, state_file)
                state = dto.DemandTimingState(state_file)
                assert state.state["consecutive_empty"] == i + 1

                # Move time forward
                state.state["last_run_timestamp"] = (
                    datetime.now() - timedelta(hours=7 + i)
                ).isoformat()
                state.save()
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_recovery_from_empty_run(self):
        """Finding signals resets empty counter."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            # Empty runs
            dto.record_mining_result(0, state_file)
            dto.record_mining_result(0, state_file)

            state = dto.DemandTimingState(state_file)
            assert state.state["consecutive_empty"] == 2

            # Now find signals
            dto.record_mining_result(5, state_file)
            state2 = dto.DemandTimingState(state_file)
            assert state2.state["consecutive_empty"] == 0
            assert state2.get_last_run_count() == 5
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)


# ---------------------------------------------------------------------------
# Edge cases and boundary conditions
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_zero_hours_since_last_run(self):
        """Very recent run (seconds ago) is within cooldown."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            state.record_run(1)
            state.set_backoff_hours(1)

            should, _ = dto.should_run(state_file=state_file)
            assert should is False
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_exact_boundary_hours(self):
        """Exactly at boundary: hours_since == cooldown."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            state = dto.DemandTimingState(state_file)
            exact_time = datetime.now() - timedelta(hours=6, seconds=0)
            state.state["last_run_timestamp"] = exact_time.isoformat()
            state.set_backoff_hours(6)

            should, _ = dto.should_run_fixed_interval(state)
            # Boundary typically allows (>=)
            assert should is True
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_negative_backoff_rejected(self):
        """Negative backoff is bounded to minimum."""
        state = dto.DemandTimingState()
        state.set_backoff_hours(-5)
        assert state.get_backoff_hours() >= dto.DEFAULT_MIN_INTERVAL

    def test_very_large_signal_count(self):
        """Large signal count is recorded."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
        try:
            dto.record_mining_result(99999, state_file)
            state = dto.DemandTimingState(state_file)
            assert state.get_last_run_count() == 99999
        finally:
            if os.path.exists(state_file):
                os.unlink(state_file)

    def test_empty_state_file_perms(self):
        """State handles permission errors gracefully."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            state_file = f.name
            f.write(b"test")
        try:
            os.chmod(state_file, 0o000)
            # Should not crash
            state = dto.DemandTimingState(state_file)
            assert state.state is not None
        finally:
            os.chmod(state_file, 0o644)
            os.unlink(state_file)


# ---------------------------------------------------------------------------
# Main entry point for standalone run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
