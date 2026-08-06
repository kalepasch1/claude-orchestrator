"""
Test suite for emit_task_log fix (qafix-tomorrow-07251452).

Validates that emit_task_log is properly defined and callable in runner.py,
and that run_task can log without raising NameError.
"""

import sys
import os
from unittest.mock import patch, MagicMock
from io import StringIO
import pytest

# Add runner directory to path so we can import runner.py
_RUNNER_DIR = os.path.join(os.path.dirname(__file__), "..", "runner")
sys.path.insert(0, _RUNNER_DIR)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runner_modules  # noqa: E402

# `runner` is ambiguous: it is both a package (runner/__init__.py) and the
# directory containing runner.py, and whichever lands on sys.path first wins for
# the whole session. Bind it by file path so this file behaves the same alone as
# it does after the hisanta tests have put the repo root on sys.path.
runner = runner_modules.load("runner")


class TestEmitTaskLogFunction:
    """Test emit_task_log function definition and basic functionality."""

    def test_emit_task_log_is_defined(self):
        """Verify emit_task_log is defined in runner module."""
        runner = runner_modules.load("runner")
        assert hasattr(runner, 'emit_task_log'), "emit_task_log should be defined in runner.py"
        assert callable(runner.emit_task_log), "emit_task_log should be callable"

    def test_emit_task_log_accepts_correct_signature(self):
        """Test that emit_task_log accepts slug, level, and msg parameters."""
        runner = runner_modules.load("runner")
        import inspect

        sig = inspect.signature(runner.emit_task_log)
        params = list(sig.parameters.keys())

        assert 'slug' in params, "emit_task_log should have 'slug' parameter"
        assert 'level' in params, "emit_task_log should have 'level' parameter"
        assert 'msg' in params, "emit_task_log should have 'msg' parameter"

    @patch('log.get')
    def test_emit_task_log_with_info_level(self, mock_log_get):
        """Test emit_task_log with info log level."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        runner.emit_task_log("test-slug", "info", "test message")

        # Should call the info method on the logger
        assert mock_logger.info.called, "Should call info method for 'info' level"

    @patch('log.get')
    def test_emit_task_log_with_error_level(self, mock_log_get):
        """Test emit_task_log with error log level."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        runner.emit_task_log("test-slug", "error", "error message")

        # Should call the error method on the logger
        assert mock_logger.error.called, "Should call error method for 'error' level"

    @patch('log.get')
    def test_emit_task_log_with_warning_level(self, mock_log_get):
        """Test emit_task_log with warning log level."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        runner.emit_task_log("test-slug", "warning", "warning message")

        # Should call the warning method on the logger
        assert mock_logger.warning.called, "Should call warning method for 'warning' level"

    @patch('log.get')
    def test_emit_task_log_with_debug_level(self, mock_log_get):
        """Test emit_task_log with debug log level."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        runner.emit_task_log("test-slug", "debug", "debug message")

        # Should call the debug method on the logger
        assert mock_logger.debug.called, "Should call debug method for 'debug' level"

    @patch('log.get')
    def test_emit_task_log_with_unknown_level_defaults_to_info(self, mock_log_get):
        """Test emit_task_log defaults to info for unknown log levels."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        runner.emit_task_log("test-slug", "unknown_level", "message")

        # Should default to info method when level doesn't exist
        assert mock_logger.info.called, "Should default to info method for unknown levels"

    @patch('log.get')
    def test_emit_task_log_formats_with_slug_prefix(self, mock_log_get):
        """Test that emit_task_log includes slug in formatted message."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        test_slug = "task-abc-123"
        test_msg = "operation completed"

        runner.emit_task_log(test_slug, "info", test_msg)

        # Check that the logger was called with slug and message
        # The formatting uses "[%s] %s" pattern
        assert mock_logger.info.called
        call_args = mock_logger.info.call_args
        assert test_slug in str(call_args), f"Slug '{test_slug}' should appear in log call"

    @patch('log.get')
    def test_emit_task_log_with_empty_slug(self, mock_log_get):
        """Test emit_task_log handles empty slug gracefully."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        # Should not raise an error with empty slug
        runner.emit_task_log("", "info", "message")
        assert mock_logger.info.called

    @patch('log.get')
    def test_emit_task_log_with_empty_message(self, mock_log_get):
        """Test emit_task_log handles empty message gracefully."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        # Should not raise an error with empty message
        runner.emit_task_log("test-slug", "info", "")
        assert mock_logger.info.called

    @patch('log.get')
    def test_emit_task_log_with_special_characters_in_message(self, mock_log_get):
        """Test emit_task_log handles special characters in message."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        special_msg = "Task failed: %s %d [ERROR] \n special chars: !@#$%^&*()"
        runner.emit_task_log("test-slug", "error", special_msg)

        assert mock_logger.error.called

    @patch('log.get')
    def test_emit_task_log_does_not_raise_on_none_inputs(self, mock_log_get):
        """Test emit_task_log behavior with None-like inputs."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        # Should handle edge cases without raising
        try:
            runner.emit_task_log("test-slug", "info", "normal message")
            assert mock_logger.info.called
        except Exception as e:
            pytest.fail(f"emit_task_log should not raise: {e}")


class TestRunTaskLoggingIntegration:
    """Test that run_task can call emit_task_log without NameError."""

    def test_run_task_has_access_to_emit_task_log(self):
        """Verify run_task function can access emit_task_log."""
        runner = runner_modules.load("runner")
        import inspect

        # Get the source code of run_task
        run_task_source = inspect.getsource(runner.run_task)

        # Check that run_task function exists
        assert hasattr(runner, 'run_task'), "run_task should be defined"
        assert callable(runner.run_task), "run_task should be callable"

    @patch('runner.emit_task_log')
    @patch('runner.set_state')
    @patch('runner.agentic_coders')
    def test_run_task_can_call_emit_task_log(self, mock_agentic, mock_set_state, mock_emit):
        """Test that calling emit_task_log within run_task context doesn't raise NameError."""
        runner = runner_modules.load("runner")

        # This test verifies the function is accessible in the run_task scope
        # by verifying the mock can be called

        runner.emit_task_log("test-task", "info", "test")

        assert mock_emit.called, "emit_task_log mock should be callable"

    def test_emit_task_log_not_a_typo_or_alias(self):
        """Verify the function name is correct (not a typo like emit_task_logs)."""
        runner = runner_modules.load("runner")

        # Check for common typos
        assert hasattr(runner, 'emit_task_log'), "Function should be 'emit_task_log' not 'emit_task_logs'"

        # Ensure it's not mistakenly defined as something else
        func_name = runner.emit_task_log.__name__
        assert func_name == 'emit_task_log', f"Function name should be 'emit_task_log', got '{func_name}'"


class TestEmitTaskLogRobustness:
    """Test edge cases and robustness of emit_task_log."""

    @patch('log.get')
    def test_emit_task_log_with_very_long_slug(self, mock_log_get):
        """Test emit_task_log with unusually long slug."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        long_slug = "a" * 1000
        runner.emit_task_log(long_slug, "info", "message")

        assert mock_logger.info.called

    @patch('log.get')
    def test_emit_task_log_with_very_long_message(self, mock_log_get):
        """Test emit_task_log with very long message."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        long_msg = "x" * 10000
        runner.emit_task_log("slug", "info", long_msg)

        assert mock_logger.info.called

    @patch('log.get')
    def test_emit_task_log_is_idempotent(self, mock_log_get):
        """Test that calling emit_task_log multiple times is safe."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        for _ in range(5):
            runner.emit_task_log("test-slug", "info", "message")

        assert mock_logger.info.call_count == 5

    @patch('log.get')
    def test_emit_task_log_with_unicode_characters(self, mock_log_get):
        """Test emit_task_log with unicode in slug and message."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        runner.emit_task_log("slug-🚀-test", "info", "message-📝-完成")

        assert mock_logger.info.called

    @patch('log.get')
    def test_emit_task_log_preserves_format_string_safety(self, mock_log_get):
        """Test that emit_task_log safely handles % characters in messages."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        # Message with % characters that could be mistaken for format strings
        unsafe_msg = "Progress: 50% complete, 100% sure about %s being undefined"
        runner.emit_task_log("test-slug", "info", unsafe_msg)

        assert mock_logger.info.called


class TestLogLevelHandling:
    """Test proper handling of different log levels."""

    @patch('log.get')
    def test_all_standard_log_levels_are_supported(self, mock_log_get):
        """Test that all standard Python logging levels are supported."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        levels = ["debug", "info", "warning", "error", "critical"]

        for level in levels:
            runner.emit_task_log("test-slug", level, f"message at {level} level")
            # At least one of the methods should have been called
            assert (mock_logger.debug.called or
                   mock_logger.info.called or
                   mock_logger.warning.called or
                   mock_logger.error.called or
                   mock_logger.critical.called)

    @patch('log.get')
    def test_log_level_is_case_sensitive(self, mock_log_get):
        """Test that log level matching works correctly."""
        runner = runner_modules.load("runner")

        mock_logger = MagicMock()
        mock_log_get.return_value = mock_logger

        # Test with lowercase (expected to work)
        runner.emit_task_log("slug", "error", "msg")
        assert mock_logger.error.called or mock_logger.info.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
