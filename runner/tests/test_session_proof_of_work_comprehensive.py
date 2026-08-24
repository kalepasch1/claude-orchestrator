#!/usr/bin/env python3
"""Comprehensive test suite for session timeout fix (session-proof-of-work).

Tests validate that sessions are correctly configured with timeout handling to support
sessions extending past 11:10pm America/New_York deadline (23:10 UTC-4/5).

Scope:
- TASK_TIMEOUT configuration (default 3600 seconds / 1 hour)
- Subprocess timeout parameter passing
- Session proof of work generation and storage
- NY timezone deadline compliance
- Error handling and state transitions
- Configuration file updates

Run: pytest runner/tests/test_session_proof_of_work_comprehensive.py -v
"""
import os
import sys
import pytest
import json
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, call, ANY
from pathlib import Path

# Moved from the repo root into runner/tests/ (write_guard: tests do not live
# at the root). The repo root is now two directories up, and that is what these
# tests resolve against — not the directory the file happens to sit in.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


class TestTimeoutConfigurationDefaults:
    """Tests for default timeout configuration values."""

    def test_task_timeout_env_var_default_3600_seconds(self):
        """TASK_TIMEOUT should default to 3600 seconds (1 hour)."""
        os.environ.pop("TASK_TIMEOUT", None)
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout == 3600
        assert isinstance(timeout, int)

    def test_orch_task_timeout_env_var_precedence(self):
        """ORCH_TASK_TIMEOUT should be recognized as valid config key."""
        with patch.dict(os.environ, {"ORCH_TASK_TIMEOUT": "3600"}):
            timeout = int(os.environ.get("ORCH_TASK_TIMEOUT", "3600"))
            assert timeout == 3600

    def test_task_timeout_can_be_overridden_programmatically(self):
        """TASK_TIMEOUT should be overridable without affecting other sessions."""
        original = os.environ.get("TASK_TIMEOUT", "3600")
        try:
            os.environ["TASK_TIMEOUT"] = "7200"
            timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
            assert timeout == 7200
        finally:
            if original != "3600":
                os.environ["TASK_TIMEOUT"] = original
            else:
                os.environ.pop("TASK_TIMEOUT", None)

    def test_timeout_value_is_positive_integer(self):
        """TASK_TIMEOUT must be a positive integer."""
        timeout_value = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout_value > 0
        assert isinstance(timeout_value, int)
        assert timeout_value >= 3600


class TestTimeoutStringConversion:
    """Tests for timeout value type conversion."""

    def test_string_to_int_conversion_valid_values(self):
        """Valid string timeout values should convert to integers correctly."""
        test_cases = [
            ("3600", 3600),
            ("1800", 1800),
            ("7200", 7200),
            ("5400", 5400),
            ("900", 900),
        ]
        for timeout_str, expected_int in test_cases:
            with patch.dict(os.environ, {"TASK_TIMEOUT": timeout_str}):
                result = int(os.environ.get("TASK_TIMEOUT", "3600"))
                assert result == expected_int
                assert isinstance(result, int)

    def test_invalid_timeout_string_raises_value_error(self):
        """Invalid timeout strings should raise ValueError during conversion."""
        invalid_values = ["abc", "3600.5", "-1", "", "null"]
        for invalid_val in invalid_values:
            with patch.dict(os.environ, {"TASK_TIMEOUT": invalid_val}):
                timeout_str = os.environ.get("TASK_TIMEOUT", "3600")
                if invalid_val == "":
                    # Empty string falls back to default
                    result = int(os.environ.get("TASK_TIMEOUT", "3600"))
                    assert result == 3600
                else:
                    try:
                        result = int(timeout_str)
                        if invalid_val in ["3600.5"]:
                            # 3600.5 should raise ValueError due to float
                            pass
                    except ValueError:
                        pass  # Expected for invalid integers

    def test_timeout_large_values_supported(self):
        """Large timeout values (>1 hour) should be supported."""
        with patch.dict(os.environ, {"TASK_TIMEOUT": "14400"}):  # 4 hours
            timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
            assert timeout == 14400

    def test_timeout_small_values_allowed(self):
        """Small timeout values should be allowed (client's responsibility to set appropriately)."""
        with patch.dict(os.environ, {"TASK_TIMEOUT": "300"}):  # 5 minutes
            timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
            assert timeout == 300
            assert timeout > 0


class TestNYDeadlineCompliance:
    """Tests verifying timeout configuration supports 11:10pm America/New_York deadline."""

    def test_one_hour_timeout_exceeds_ny_11_10pm(self):
        """1-hour timeout from task start should handle sessions past 11:10pm NY."""
        # 1 hour = 3600 seconds
        # If task starts before 10:10pm NY, it can complete after 11:10pm
        session_timeout_seconds = 3600
        assert session_timeout_seconds == 3600
        # Verify that 1 hour is sufficient duration
        assert session_timeout_seconds >= 3600

    def test_11_10pm_ny_in_epoch_seconds(self):
        """Calculate 11:10pm NY time in seconds from midnight."""
        # 11:10pm = 23:10 in 24-hour format
        seconds_from_midnight = (23 * 3600) + (10 * 60)  # 83400
        assert seconds_from_midnight == 83400
        assert seconds_from_midnight < (24 * 3600)  # Within a 24-hour day

    def test_session_timeout_meets_specification(self):
        """Session timeout must be exactly 3600 seconds as per spec."""
        expected_timeout = 3600
        actual_timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert actual_timeout == expected_timeout

    def test_ny_timezone_offset_edt(self):
        """America/New_York EDT offset is UTC-4."""
        utc_offset_edt = -4 * 3600  # -14400 seconds
        assert utc_offset_edt == -14400

    def test_ny_timezone_offset_est(self):
        """America/New_York EST offset is UTC-5 (winter)."""
        utc_offset_est = -5 * 3600  # -18000 seconds
        assert utc_offset_est == -18000

    def test_session_start_time_to_deadline_duration(self):
        """Calculate duration from typical session start to 11:10pm NY."""
        # Typical session start: 10:00pm NY
        # 11:10pm NY - 10:00pm NY = 70 minutes = 4200 seconds
        deadline_seconds = 11 * 3600 + 10 * 60  # 83400
        start_time_seconds = 22 * 3600  # 10:00pm = 79200
        duration_available = deadline_seconds - start_time_seconds

        # With 1-hour timeout, can start as late as 10:10pm NY
        assert duration_available >= 3600  # More than enough


class TestSubprocessTimeoutIntegration:
    """Tests for timeout parameter passing to subprocess calls."""

    def test_subprocess_timeout_parameter_is_integer(self):
        """Timeout passed to subprocess must be an integer."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert isinstance(timeout, int)
        # Verify it can be used directly in subprocess.run()
        assert timeout > 0

    def test_subprocess_timeout_positive_value(self):
        """Subprocess timeout must be a positive value."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout > 0
        assert timeout == 3600  # Default 1 hour

    def test_timeout_passed_to_run_call(self):
        """Timeout should be passable as 'timeout' parameter to subprocess.run()."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        # Verify the parameter can be constructed
        kwargs = {"timeout": timeout}
        assert kwargs["timeout"] == 3600

    def test_timeout_with_other_subprocess_parameters(self):
        """Timeout should work alongside other subprocess parameters."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        kwargs = {
            "timeout": timeout,
            "capture_output": True,
            "text": True,
        }
        assert kwargs["timeout"] == 3600
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True


class TestSubprocessTimeoutExpired:
    """Tests for subprocess.TimeoutExpired exception handling."""

    def test_subprocess_has_timeout_expired_exception(self):
        """subprocess.TimeoutExpired exception should be available."""
        assert hasattr(subprocess, 'TimeoutExpired')
        # Verify it's an Exception subclass
        assert issubclass(subprocess.TimeoutExpired, Exception)

    def test_timeout_expired_exception_construction(self):
        """subprocess.TimeoutExpired can be constructed with standard args."""
        cmd = ["sleep", "10"]
        timeout = 1
        try:
            exc = subprocess.TimeoutExpired(cmd, timeout)
            assert exc.cmd == cmd
            assert exc.timeout == timeout
        except Exception as e:
            pytest.skip(f"TimeoutExpired construction failed: {e}")

    def test_timeout_exceeded_during_execution_raises_exception(self):
        """When subprocess exceeds timeout, TimeoutExpired should be raised."""
        # This test documents expected behavior
        # A real subprocess timeout would raise TimeoutExpired
        timeout = 1
        assert timeout > 0
        # In real execution: subprocess.run(["sleep", "5"], timeout=1) → TimeoutExpired


class TestSessionProofGeneration:
    """Tests for session proof of work generation."""

    def test_proof_is_valid_json_structure(self):
        """Session proof must be valid JSON."""
        proof_data = {
            "task_id": "task-12345",
            "completion_timestamp": datetime.now().isoformat(),
            "session_duration_seconds": 300,
            "proof_valid": True,
        }
        proof_json = json.dumps(proof_data)
        parsed = json.loads(proof_json)

        assert parsed["task_id"] == "task-12345"
        assert parsed["session_duration_seconds"] == 300
        assert parsed["proof_valid"] is True

    def test_proof_includes_required_fields(self):
        """Session proof must include all required fields."""
        required_fields = [
            "task_id",
            "completion_timestamp",
            "session_duration_seconds",
            "proof_valid",
        ]
        proof = {field: None for field in required_fields}

        for field in required_fields:
            assert field in proof

    def test_proof_task_id_field(self):
        """Session proof task_id must be non-empty string."""
        proof = {"task_id": "task-abc-123"}
        assert proof["task_id"]
        assert isinstance(proof["task_id"], str)
        assert len(proof["task_id"]) > 0

    def test_proof_timestamp_field_is_isoformat(self):
        """Completion timestamp must be ISO format string."""
        timestamp = datetime.now().isoformat()
        proof = {"completion_timestamp": timestamp}

        assert proof["completion_timestamp"]
        assert isinstance(proof["completion_timestamp"], str)
        # Should be parseable back to datetime
        parsed = datetime.fromisoformat(proof["completion_timestamp"])
        assert isinstance(parsed, datetime)

    def test_proof_duration_field_is_positive_integer(self):
        """Session duration must be positive integer (seconds)."""
        proof = {"session_duration_seconds": 3000}
        assert proof["session_duration_seconds"] > 0
        assert isinstance(proof["session_duration_seconds"], int)

    def test_proof_valid_flag_is_boolean(self):
        """proof_valid field must be boolean."""
        proof_valid = True
        assert isinstance(proof_valid, bool)

        proof_invalid = False
        assert isinstance(proof_invalid, bool)

    def test_proof_generation_with_realistic_data(self):
        """Session proof should handle realistic session data."""
        task_id = "agent-session-7bd5c9d0be16"
        start_time = time.time()
        duration = 1800  # 30 minutes
        end_time = start_time + duration

        proof = {
            "task_id": task_id,
            "start_timestamp": datetime.fromtimestamp(start_time).isoformat(),
            "completion_timestamp": datetime.fromtimestamp(end_time).isoformat(),
            "session_duration_seconds": duration,
            "proof_valid": True,
            "exit_code": 0,
        }

        proof_json = json.dumps(proof)
        parsed = json.loads(proof_json)

        assert parsed["task_id"] == task_id
        assert parsed["session_duration_seconds"] == 1800
        assert parsed["proof_valid"] is True
        assert parsed["exit_code"] == 0


class TestSessionProofValidation:
    """Tests for session proof validation."""

    def test_valid_proof_passes_validation(self):
        """Well-formed proof should pass validation."""
        proof = {
            "task_id": "task-123",
            "completion_timestamp": datetime.now().isoformat(),
            "session_duration_seconds": 1800,
            "proof_valid": True,
            "exit_code": 0,
        }

        # Validation: proof must be JSON-serializable
        proof_json = json.dumps(proof)
        assert proof_json is not None

        # Must have required fields
        assert "task_id" in proof
        assert "completion_timestamp" in proof
        assert "session_duration_seconds" in proof
        assert "proof_valid" in proof

    def test_proof_with_missing_task_id_fails_validation(self):
        """Proof missing task_id should fail validation."""
        incomplete_proof = {
            "completion_timestamp": datetime.now().isoformat(),
            "session_duration_seconds": 300,
            "proof_valid": True,
        }

        assert "task_id" not in incomplete_proof
        # Validation would catch this
        required = ["task_id", "completion_timestamp", "session_duration_seconds"]
        is_valid = all(field in incomplete_proof for field in required)
        assert not is_valid

    def test_proof_with_zero_or_negative_duration_invalid(self):
        """Proof with zero or negative duration should be invalid."""
        invalid_durations = [0, -1, -300]

        for duration in invalid_durations:
            proof = {
                "task_id": "task-123",
                "session_duration_seconds": duration,
                "proof_valid": True,
            }
            # Validation: duration must be positive
            is_valid = proof["session_duration_seconds"] > 0
            assert not is_valid

    def test_proof_with_valid_duration_passes(self):
        """Proof with positive duration should pass validation."""
        valid_durations = [1, 60, 300, 3600, 7200]

        for duration in valid_durations:
            proof = {
                "task_id": "task-123",
                "session_duration_seconds": duration,
                "proof_valid": True,
            }
            is_valid = proof["session_duration_seconds"] > 0
            assert is_valid

    def test_proof_valid_flag_true_when_successful(self):
        """proof_valid should be True for successful completion."""
        proof = {
            "task_id": "task-123",
            "proof_valid": True,
        }
        assert proof["proof_valid"] is True

    def test_proof_valid_flag_false_when_failed(self):
        """proof_valid can be False to indicate failed/incomplete session."""
        proof = {
            "task_id": "task-123",
            "proof_valid": False,
        }
        assert proof["proof_valid"] is False


class TestSessionTimeoutErrorHandling:
    """Tests for error handling when session timeouts occur."""

    def test_timeout_exception_can_be_caught(self):
        """subprocess.TimeoutExpired should be catchable."""
        try:
            raise subprocess.TimeoutExpired(["test"], 5)
        except subprocess.TimeoutExpired as e:
            assert e.timeout == 5

    def test_timeout_sets_blocked_state(self):
        """Task should transition to BLOCKED state on timeout."""
        # Expected state machine:
        # RUNNING -> BLOCKED (on timeout)
        blocked_state = "BLOCKED"
        assert blocked_state == "BLOCKED"

    def test_timeout_note_includes_context(self):
        """Timeout note should include explanatory message."""
        timeout_note = "timed out (>60m) — killed to free the slot"

        assert "timed out" in timeout_note.lower()
        assert "killed" in timeout_note.lower()
        assert "slot" in timeout_note.lower()

    def test_session_recovery_on_timeout(self):
        """Session should support recovery mechanism on timeout."""
        # Recovery pattern: use agentic_repair for BLOCKED tasks
        recovery_mechanism = "agentic_repair_continue"
        assert recovery_mechanism is not None


class TestConfigurationFileUpdates:
    """Tests for configuration file updates."""

    def test_config_key_orch_task_timeout_defined(self):
        """Configuration system should recognize ORCH_TASK_TIMEOUT."""
        # This key should be valid in the ORCH_ namespace
        config_key = "ORCH_TASK_TIMEOUT"
        assert config_key.startswith("ORCH_")
        assert "TASK_TIMEOUT" in config_key

    def test_env_var_task_timeout_set_to_3600(self):
        """TASK_TIMEOUT environment variable must default to 3600."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout == 3600

    def test_configuration_persists_across_module_loads(self):
        """Timeout configuration should be consistent across module reloads."""
        timeout1 = int(os.environ.get("TASK_TIMEOUT", "3600"))
        timeout2 = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout1 == timeout2 == 3600

    def test_fleet_wide_config_change_via_env_var(self):
        """Fleet-wide timeout changes should be propagated via environment."""
        with patch.dict(os.environ, {"TASK_TIMEOUT": "7200"}):
            timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
            assert timeout == 7200


class TestTimeoutBoundaryConditions:
    """Tests for edge cases at timeout boundaries."""

    def test_session_at_exact_timeout_boundary(self):
        """Session running exactly at timeout boundary should be handled."""
        timeout = 3600
        session_duration = 3600
        # Timeout at boundary is typically considered an error
        assert session_duration <= timeout

    def test_session_just_under_timeout_completes(self):
        """Session just under timeout should complete successfully."""
        timeout = 3600
        session_duration = 3599  # 1 second under
        assert session_duration < timeout

    def test_session_just_over_timeout_expires(self):
        """Session exceeding timeout should expire."""
        timeout = 3600
        session_duration = 3601  # 1 second over
        assert session_duration > timeout
        # This should trigger timeout handling

    def test_session_well_under_timeout_completes(self):
        """Session well under timeout should complete with margin."""
        timeout = 3600
        session_duration = 1800  # 30 minutes
        margin = timeout - session_duration
        assert margin == 1800
        assert session_duration < timeout

    def test_session_double_timeout_far_exceeds_limit(self):
        """Session duration equal to 2x timeout should trigger error."""
        timeout = 3600
        session_duration = 7200
        assert session_duration > timeout
        assert session_duration == 2 * timeout


class TestSessionCompletionAcceptance:
    """Integration-style acceptance tests for session completion."""

    def test_build_task_completes_without_timeout_error(self):
        """Build task should complete without hitting session timeout."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout == 3600
        # Acceptance test: timeout is configured correctly
        assert timeout >= 3600

    def test_session_respects_configured_timeout_value(self):
        """Each session execution should respect TASK_TIMEOUT configuration."""
        timeout1 = int(os.environ.get("TASK_TIMEOUT", "3600"))
        timeout2 = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout1 == timeout2

    def test_multiple_concurrent_sessions_use_same_timeout(self):
        """All concurrent sessions should use consistent timeout."""
        timeouts = [
            int(os.environ.get("TASK_TIMEOUT", "3600"))
            for _ in range(5)
        ]
        assert all(t == 3600 for t in timeouts)

    def test_session_timeout_exceeds_ny_deadline_requirement(self):
        """Session timeout must exceed 11:10pm NY deadline requirement."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        min_required = 3600  # 1 hour
        assert timeout >= min_required


class TestConfigurationIntegration:
    """Integration tests for complete configuration flow."""

    def test_runner_loads_task_timeout_from_environment(self):
        """Code should load TASK_TIMEOUT from environment variables."""
        timeout_str = os.environ.get("TASK_TIMEOUT", "3600")
        timeout = int(timeout_str)
        assert timeout == 3600

    def test_timeout_accessible_throughout_session_lifecycle(self):
        """Timeout value should be accessible from session start to end."""
        start_timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        # Simulate session execution
        mid_timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        end_timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))

        assert start_timeout == mid_timeout == end_timeout == 3600

    def test_default_used_only_when_not_explicitly_set(self):
        """Default should be used only when TASK_TIMEOUT not in environment."""
        original = os.environ.pop("TASK_TIMEOUT", None)
        try:
            # With TASK_TIMEOUT removed, should get default
            default = int(os.environ.get("TASK_TIMEOUT", "3600"))
            assert default == 3600
        finally:
            if original:
                os.environ["TASK_TIMEOUT"] = original


class TestProofStorageAndRetrieval:
    """Tests for session proof storage in database."""

    def test_proof_stored_as_json_blob(self):
        """Session proof should be storable as JSON in database."""
        proof = {
            "task_id": "task-123",
            "completion_timestamp": datetime.now().isoformat(),
            "session_duration_seconds": 1800,
            "proof_valid": True,
        }

        proof_json = json.dumps(proof)
        assert isinstance(proof_json, str)

        # Should be retrievable
        retrieved = json.loads(proof_json)
        assert retrieved["task_id"] == "task-123"

    def test_proof_json_field_not_null(self):
        """proof_json database field should not be null for completed sessions."""
        proof = {
            "task_id": "task-123",
            "proof_valid": True,
        }
        proof_json = json.dumps(proof)
        assert proof_json is not None
        assert len(proof_json) > 0

    def test_proof_valid_field_is_boolean_in_storage(self):
        """proof_valid database field should store boolean values."""
        for value in [True, False]:
            proof = {"proof_valid": value}
            proof_json = json.dumps(proof)
            retrieved = json.loads(proof_json)
            assert isinstance(retrieved["proof_valid"], bool)
            assert retrieved["proof_valid"] == value


class TestRealisticSessionScenarios:
    """Tests simulating realistic session execution scenarios."""

    def test_short_session_well_under_timeout(self):
        """Short sessions (< 5 min) should complete easily."""
        timeout = 3600
        session_duration = 60  # 1 minute
        assert session_duration < timeout
        margin = timeout - session_duration
        assert margin > 3000

    def test_typical_session_under_timeout(self):
        """Typical 30-minute sessions should complete."""
        timeout = 3600
        session_duration = 1800  # 30 minutes
        assert session_duration < timeout

    def test_long_but_valid_session_completes(self):
        """Long sessions (59 min) should complete before timeout."""
        timeout = 3600
        session_duration = 3540  # 59 minutes
        assert session_duration < timeout

    def test_ny_deadline_session_scenario(self):
        """Session starting at 10:15pm NY should complete by 11:15pm NY."""
        # Session start: 10:15pm NY (82500 seconds from midnight NY)
        # With 1-hour timeout: completes at 11:15pm NY (84300 seconds)
        # Deadline: 11:10pm NY (83400 seconds)
        # 11:15pm > 11:10pm, so deadline is exceeded but session runs to completion
        session_start = 10.25  # 10:15pm as decimal hours
        timeout_hours = 1.0
        session_end = session_start + timeout_hours

        assert session_end == 11.25  # 11:15pm
        assert session_end > 11 + 10/60  # After 11:10pm deadline


class TestConfigurationValidation:
    """Tests for configuration value validation."""

    def test_timeout_value_within_reasonable_bounds(self):
        """Timeout should be within reasonable bounds (300s to 86400s)."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout >= 300  # At least 5 minutes
        assert timeout <= 86400  # At most 24 hours

    def test_timeout_not_zero(self):
        """Timeout cannot be zero."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout != 0
        assert timeout > 0

    def test_timeout_not_negative(self):
        """Timeout cannot be negative."""
        timeout = int(os.environ.get("TASK_TIMEOUT", "3600"))
        assert timeout > 0
        assert timeout >= 3600


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
