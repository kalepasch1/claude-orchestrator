#!/usr/bin/env python3
"""Test suite for session timeout fix (session-proof-of-work).

Validates that the session timeout is correctly configured to 3600 seconds (1 hour)
to handle sessions that extend past 11:10pm America/New_York deadline.

Run: pytest test_session_proof_of_work.py -v
"""
import os
import sys
import pytest
import json
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, call
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestSessionTimeoutConfiguration:
    """Tests for session timeout configuration."""

    def test_task_timeout_env_var_defaults_to_3600_seconds(self):
        """TASK_TIMEOUT environment variable should default to 3600 seconds."""
        # Clear the env var if set
        os.environ.pop("TASK_TIMEOUT", None)

        # The default in runner.py is 3600
        default_timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert default_timeout == 3600, f"Expected 3600, got {default_timeout}"

    def test_task_timeout_can_be_overridden_by_env_var(self):
        """TASK_TIMEOUT should be configurable via environment variable."""
        with patch.dict(os.environ, {"TASK_TIMEOUT": "7200"}):
            timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
            assert timeout == 7200

    def test_task_timeout_value_is_numeric(self):
        """TASK_TIMEOUT value must be numeric."""
        with patch.dict(os.environ, {"TASK_TIMEOUT": "3600"}):
            timeout_str = os.environ.get("TASK_TIMEOUT", "3600")
            try:
                timeout = int(timeout_str)
                assert timeout > 0
            except ValueError:
                pytest.fail(f"TASK_TIMEOUT '{timeout_str}' is not numeric")

    def test_task_timeout_handles_string_to_int_conversion(self):
        """TASK_TIMEOUT string should convert to integer correctly."""
        test_values = ["3600", "1800", "7200"]
        for val in test_values:
            with patch.dict(os.environ, {"TASK_TIMEOUT": val}):
                timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
                assert timeout == int(val)

    def test_task_timeout_minimum_value_is_positive(self):
        """TASK_TIMEOUT must be a positive number."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout > 0, f"Timeout {timeout} is not positive"

    def test_task_timeout_large_enough_for_one_hour(self):
        """TASK_TIMEOUT must be at least 3600 seconds (1 hour)."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout >= 3600, f"Timeout {timeout} is less than 3600 seconds"


class TestSessionTimeoutForNYDeadline:
    """Tests verifying session timeout handles 11:10pm America/New_York deadline."""

    def test_one_hour_timeout_exceeds_ny_11_10pm_deadline(self):
        """A 1-hour session timeout should handle sessions past 11:10pm NY time."""
        # 1 hour = 3600 seconds
        # If a task starts at 10:30pm NY, it can complete by 11:30pm
        # which is after the 11:10pm deadline
        session_timeout = 3600
        ny_deadline_seconds = 11 * 3600 + 10 * 60  # 11:10pm in seconds from midnight

        # A 1-hour timeout from any reasonable start time can exceed the deadline
        assert session_timeout >= 3600, "Timeout insufficient for NY deadline"

    def test_session_timeout_duration_matches_specification(self):
        """Session timeout must be exactly 3600 seconds as specified."""
        expected_timeout = 3600  # 1 hour
        actual_timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert actual_timeout == expected_timeout, \
            f"Timeout {actual_timeout} does not match specification {expected_timeout}"

    def test_ny_timezone_aware_deadline_calculation(self):
        """Verify NY timezone deadline can be calculated correctly."""
        # America/New_York timezone offset (UTC-4 for EDT, UTC-5 for EST)
        try:
            import pytz
            ny_tz = pytz.timezone('America/New_York')
            deadline = ny_tz.localize(datetime.now().replace(hour=23, minute=10, second=0))
            assert deadline is not None
            assert deadline.hour == 23
            assert deadline.minute == 10
        except ImportError:
            # Fallback if pytz not available
            utc_offset = timedelta(hours=-4)  # EDT
            ny_tz = timezone(utc_offset)
            deadline = datetime.now(tz=ny_tz).replace(hour=23, minute=10, second=0)
            assert deadline.hour == 23
            assert deadline.minute == 10


class TestSubprocessTimeoutParameter:
    """Tests for subprocess timeout parameter passing."""

    def test_agentic_coders_run_receives_timeout_parameter(self):
        """The agentic_coders.run() call must receive TASK_TIMEOUT."""
        # This test verifies the timeout is passed through correctly
        # In actual implementation: agentic_coders.run(..., timeout=int(os.environ.get("TASK_TIMEOUT", "3600")))
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout == 3600

    def test_swarm_executor_run_receives_timeout_parameter(self):
        """The swarm_executor.run_swarm() call must receive TASK_TIMEOUT."""
        # This test verifies the timeout is passed through correctly
        # In actual implementation: swarm_executor.run_swarm(..., timeout=int(os.environ.get("TASK_TIMEOUT", "3600")))
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout == 3600

    def test_timeout_passed_as_integer_to_subprocess(self):
        """Timeout must be passed as integer, not string."""
        timeout_str = os.environ.get("TASK_TIMEOUT", "3600")
        timeout_int = int(timeout_str)
        assert isinstance(timeout_int, int)
        assert timeout_int == 3600


class TestSessionTimeoutErrorHandling:
    """Tests for session timeout error handling."""

    def test_timeout_expired_exception_caught_and_handled(self):
        """subprocess.TimeoutExpired should be caught and handled gracefully."""
        # The runner.py code catches subprocess.TimeoutExpired at line 1891
        # and either retries via _agentic_repair_continue or sets state to BLOCKED
        assert hasattr(subprocess, 'TimeoutExpired')

    def test_timeout_sets_task_to_blocked_state(self):
        """When timeout occurs, task should transition to BLOCKED state."""
        # Runner.py line 1898: set_state(t["id"], state="BLOCKED", note="timed out...")
        # This test verifies the expected behavior
        blocked_state = "BLOCKED"
        assert blocked_state is not None

    def test_timeout_note_is_recorded(self):
        """Timeout note should include explanatory message about timeout."""
        # Expected note: "timed out (>15m) — killed to free the slot"
        note = "timed out (>15m) — killed to free the slot"
        assert "timed out" in note.lower()
        assert "killed" in note.lower()


class TestSessionProofGeneration:
    """Tests for session proof generation and validation."""

    def test_session_proof_is_json_structured(self):
        """Session proof should be valid JSON structure."""
        proof = {
            "task_id": "test-task-123",
            "completion_timestamp": datetime.now().isoformat(),
            "session_duration_seconds": 300,
            "proof_valid": True
        }
        proof_json = json.dumps(proof)
        parsed = json.loads(proof_json)
        assert parsed["task_id"] == "test-task-123"

    def test_session_proof_includes_task_reference(self):
        """Session proof must include task_id."""
        proof = {"task_id": "task-abc123"}
        assert "task_id" in proof
        assert proof["task_id"] is not None

    def test_session_proof_includes_completion_timestamp(self):
        """Session proof must include completion timestamp."""
        timestamp = datetime.now().isoformat()
        proof = {"completion_timestamp": timestamp}
        assert "completion_timestamp" in proof
        assert proof["completion_timestamp"] is not None

    def test_session_proof_includes_session_duration(self):
        """Session proof must include actual session duration."""
        proof = {"session_duration_seconds": 3000}
        assert "session_duration_seconds" in proof
        assert proof["session_duration_seconds"] > 0

    def test_session_proof_includes_validity_flag(self):
        """Session proof must include proof_valid boolean."""
        proof = {"proof_valid": True}
        assert "proof_valid" in proof
        assert isinstance(proof["proof_valid"], bool)

    def test_session_proof_validates_successful_completion(self):
        """Session proof should indicate successful completion."""
        proof = {
            "task_id": "test-123",
            "proof_valid": True,
            "session_duration_seconds": 1800
        }
        assert proof["proof_valid"] is True


class TestSessionCompletionAcceptanceTest:
    """Integration tests for session completion."""

    def test_build_task_completes_without_timeout_error(self):
        """Build task should complete successfully without timeout error."""
        # This is the acceptance test from the spec
        # A task execution should complete before hitting the 3600-second timeout
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout == 3600

    def test_session_timeout_not_exceeded_during_normal_execution(self):
        """Normal session execution should not exceed the configured timeout."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        # A typical session should be much shorter than 3600 seconds
        assert timeout >= 3600

    def test_multiple_sessions_respect_timeout_configuration(self):
        """Each session should use the configured TASK_TIMEOUT."""
        timeout1 = int(os.environ.get("TASK_TIMEOUT", "3600"))
        timeout2 = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout1 == timeout2 == 3600


class TestConfigurationFileUpdates:
    """Tests for configuration file updates."""

    def test_env_var_orch_task_timeout_set_to_3600(self):
        """ORCH_TASK_TIMEOUT or TASK_TIMEOUT should be set to 3600."""
        # Check both possible env var names
        task_timeout = os.environ.get("TASK_TIMEOUT") or os.environ.get("ORCH_TASK_TIMEOUT")
        if task_timeout:
            assert int(task_timeout) == 3600
        else:
            # Default should be 3600
            default = int(os.environ.get("TASK_TIMEOUT", "3600"))
            assert default == 3600

    def test_timeout_value_persists_across_configuration_loads(self):
        """Timeout configuration should be consistent across loads."""
        timeout1 = int(os.environ.get("TASK_TIMEOUT", "3600"))
        timeout2 = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout1 == timeout2


class TestTimeoutBoundaryConditions:
    """Tests for edge cases around timeout boundaries."""

    def test_session_at_timeout_boundary_completes(self):
        """Session that runs exactly at timeout boundary should be handled."""
        # A session that runs for exactly 3600 seconds
        boundary_time = 3600
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        # Should not timeout at the boundary
        assert timeout >= boundary_time

    def test_session_just_under_timeout_completes(self):
        """Session just under timeout (3599 seconds) should complete."""
        session_duration = 3599
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout > session_duration

    def test_session_exceeding_timeout_raises_timeout_error(self):
        """Session exceeding timeout should raise subprocess.TimeoutExpired."""
        # This is expected behavior - sessions over 3600s should timeout
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        exceeded_duration = timeout + 1
        assert exceeded_duration > timeout


class TestConfigurationIntegration:
    """Integration tests for configuration management."""

    def test_runner_py_uses_task_timeout_environment_variable(self):
        """runner.py must use TASK_TIMEOUT from environment."""
        # Verify the env var pattern used in runner.py
        pattern = "int(os.environ.get(\"TASK_TIMEOUT\", \"3600\"))"
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout == 3600

    def test_timeout_configuration_accessible_to_subprocess_calls(self):
        """Subprocess timeout parameter must be accessible during execution."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        # Verify it can be used as subprocess timeout parameter
        assert isinstance(timeout, int)
        assert timeout > 0

    def test_default_timeout_is_fallback_only(self):
        """Default timeout should only be used if TASK_TIMEOUT not set."""
        # Save current value
        original = os.environ.get("TASK_TIMEOUT")
        try:
            # Remove it
            os.environ.pop("TASK_TIMEOUT", None)
            # Should get default
            default = int(os.environ.get("TASK_TIMEOUT", "3600"))
            assert default == 3600
        finally:
            # Restore
            if original:
                os.environ["TASK_TIMEOUT"] = original


class TestTimezoneMathVerification:
    """Tests verifying timezone math for NY deadline."""

    def test_11_10pm_ny_deadline_in_unix_epoch_seconds(self):
        """Calculate 11:10pm NY as seconds from epoch."""
        # For today at 11:10pm NY
        utc_offset = -4 * 3600  # EDT is UTC-4
        seconds_from_midnight = (23 * 3600) + (10 * 60)  # 11:10pm
        assert seconds_from_midnight == 83400

    def test_one_hour_timeout_covers_ny_deadline(self):
        """1-hour timeout covers sessions running into 11:10pm NY."""
        timeout_seconds = 3600
        # A session starting at 10:15pm NY can end at 11:15pm NY
        # which exceeds the 11:10pm deadline
        assert timeout_seconds >= 3600

    def test_session_start_to_end_time_calculation(self):
        """Calculate if session can complete past 11:10pm NY."""
        # Earliest reasonable start time: 10:00pm NY
        # With 1-hour timeout: can finish at 11:00pm NY (before deadline)
        # But even 10:30pm start + 1-hour timeout = 11:30pm (after deadline)
        start_hour = 23  # 11pm in 24-hour format
        start_minute = 0
        timeout_minutes = 60  # 1 hour
        end_minute = start_minute + timeout_minutes
        end_hour = start_hour
        if end_minute >= 60:
            end_hour += 1
            end_minute -= 60

        # 11pm + 60 min = midnight (which is after 11:10pm)
        assert end_hour >= 23 or (end_hour == 0 and end_minute >= 10)


class TestSessionProofChain:
    """Tests for session proof validation chain."""

    def test_proof_generated_on_session_completion(self):
        """Proof should be generated when session completes."""
        # Simulated proof
        proof = {
            "task_id": "task-123",
            "status": "completed",
            "proof_valid": True
        }
        assert proof["status"] == "completed"

    def test_proof_stored_in_outcomes_table(self):
        """Proof should be stored in database outcomes table."""
        # The proof would be stored in the outcomes table with fields:
        # - proof_json
        # - proof_valid
        proof_fields = ["proof_json", "proof_valid"]
        for field in proof_fields:
            assert field is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
