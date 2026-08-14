"""
Tests for auto_filer.py — HTTP 409 Conflict handler for concurrent file writes.
"""
import os
import sys
import tempfile
import time
from unittest.mock import patch, MagicMock

RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import auto_filer


def test_409_first_attempt_then_retry_succeeds(tmp_path):
    """Test: 409 on first attempt, succeeds on retry."""
    filepath = str(tmp_path / "test_409_retry.txt")
    content = b"test content"

    # Mock open() to raise OSError with "resource busy" on first call, then succeed
    call_count = [0]
    original_open = open

    def mock_open_func(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise OSError("[Errno 16] Device or resource busy")
        return original_open(*args, **kwargs)

    # Reset stats before test
    auto_filer.reset_stats()

    with patch("builtins.open", side_effect=mock_open_func):
        success, error = auto_filer.write_with_conflict_retry(filepath, content)

    assert success is True, f"Expected success, got error: {error}"
    assert os.path.exists(filepath), "File should exist after retry"
    with open(filepath, "rb") as fh:
        assert fh.read() == content, "File content should match"

    stats = auto_filer.stats()
    assert stats["conflicts_detected"] >= 1, "Should detect 409 conflict"
    assert stats["retries_succeeded"] >= 1, "Should record retry success"


def test_409_exhausts_retries_logs_escalation(tmp_path):
    """Test: 409 on every attempt, retries exhausted and escalation logged."""
    filepath = str(tmp_path / "test_409_exhausted.txt")
    content = b"test content"

    # Mock open() to always raise "resource busy"
    def mock_open_always_fail(*args, **kwargs):
        raise OSError("[Errno 16] Device or resource busy: '%s'" % filepath)

    # Set low retry count for faster test
    with patch.dict(os.environ, {"ORCH_CONFLICT_BACKOFF_MAX_RETRIES": "1"}):
        auto_filer.CONFLICT_BACKOFF_MAX_RETRIES = 1
        auto_filer.reset_stats()

        with patch("builtins.open", side_effect=mock_open_always_fail):
            success, error = auto_filer.write_with_conflict_retry(filepath, content)

        assert success is False, "Expected failure after retries"
        assert "exhausted retries" in error.lower(), f"Expected escalation message, got: {error}"

        stats = auto_filer.stats()
        assert stats["conflicts_detected"] >= 1, "Should detect 409 conflict"
        assert stats["retries_exhausted"] >= 1, "Should record exhausted retries"

        # Restore original value
        auto_filer.CONFLICT_BACKOFF_MAX_RETRIES = int(
            os.environ.get("ORCH_CONFLICT_BACKOFF_MAX_RETRIES", "3")
        )


def test_409_on_concurrent_streams_logs_hint(tmp_path):
    """Test: 409 on concurrent streams, logs hint from on_409_hint callback."""
    filepath = str(tmp_path / "test_409_concurrent.txt")
    content = b"test content"

    call_count = [0]
    original_open = open

    def mock_open_with_hint(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise OSError("[Errno 16] Resource busy")
        return original_open(*args, **kwargs)

    hint_called = [False]

    def get_hint(fpath):
        hint_called[0] = True
        return "process_xyz_pid_1234"

    auto_filer.reset_stats()

    with patch("builtins.open", side_effect=mock_open_with_hint):
        success, error = auto_filer.write_with_conflict_retry(
            filepath, content, on_409_hint=get_hint
        )

    assert success is True, f"Expected success, got error: {error}"
    assert hint_called[0], "on_409_hint callback should have been called"
    assert os.path.exists(filepath), "File should exist after retry"

    stats = auto_filer.stats()
    assert stats["conflicts_detected"] >= 1, "Should detect 409 conflict"
    # Last conflict path should be recorded
    assert filepath in stats["last_conflict_path"], "Should record conflict path"


def test_non_conflict_error_returns_immediately(tmp_path):
    """Test: Non-conflict errors return immediately without retry."""
    filepath = str(tmp_path / "test_non_conflict.txt")
    content = b"test content"

    # Mock open() to raise a different error (permission denied, not resource busy)
    def mock_open_perm_error(*args, **kwargs):
        raise PermissionError("[Errno 13] Permission denied")

    auto_filer.reset_stats()

    with patch("builtins.open", side_effect=mock_open_perm_error):
        success, error = auto_filer.write_with_conflict_retry(filepath, content)

    assert success is False, "Expected failure"
    assert "Permission denied" in error, f"Expected permission error, got: {error}"

    stats = auto_filer.stats()
    # Should NOT record as conflict, should NOT retry
    assert stats["conflicts_detected"] == 0, "Permission error is not a 409 conflict"


def test_exponential_backoff_formula(tmp_path):
    """Test: Exponential backoff follows correct formula."""
    # Test backoff delays
    delays = [
        auto_filer._exponential_backoff(0),  # 2^0 * 2 = 2
        auto_filer._exponential_backoff(1),  # 2^1 * 2 = 4
        auto_filer._exponential_backoff(2),  # 2^2 * 2 = 8
    ]

    base = auto_filer.CONFLICT_BACKOFF_BASE_DELAY
    max_delay = auto_filer.CONFLICT_BACKOFF_MAX_DELAY

    assert delays[0] == base, f"Expected {base}, got {delays[0]}"
    assert delays[1] == base * 2, f"Expected {base * 2}, got {delays[1]}"
    assert delays[2] == min(base * 4, max_delay), f"Expected {min(base * 4, max_delay)}, got {delays[2]}"


def test_empty_filepath_returns_error(tmp_path):
    """Test: Empty filepath returns error immediately."""
    auto_filer.reset_stats()

    success, error = auto_filer.write_with_conflict_retry("", b"content")

    assert success is False, "Expected failure for empty filepath"
    assert "empty" in error.lower(), f"Expected empty error message, got: {error}"
    assert auto_filer.stats()["conflicts_detected"] == 0, "Should not record as conflict"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
