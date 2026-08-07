#!/usr/bin/env python3
"""
test_darwin_determinations.py - Comprehensive test suite for darwin_determinations module.

Tests cover:
  1. Mock path with all env vars unset (default behavior)
  2. Live path enabled but API key invalid (fallback to mock)
  3. Live path with custom model
  4. Error handling and logging
  5. Backwards compatibility (public signature unchanged)
"""
import os
import sys
import unittest
import logging
from unittest.mock import patch, MagicMock
import tempfile
import json

# Add runner to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import darwin_determinations


class TestDarwinDeterminationsMock(unittest.TestCase):
    """Test cases for mock (default) path."""

    def setUp(self):
        """Clear all DARWIN_* env vars before each test."""
        for key in ("DARWIN_LIVE", "DARWIN_API_KEY", "DARWIN_MODEL", "ANTHROPIC_API_KEY"):
            if key in os.environ:
                del os.environ[key]

    def test_mock_path_default(self):
        """Test: DARWIN_LIVE unset, DARWIN_API_KEY unset, DARWIN_MODEL unset.
        Expected: Mock path runs, result is deterministic."""
        result = darwin_determinations.determine()
        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")

    def test_mock_path_live_disabled_explicitly(self):
        """Test: DARWIN_LIVE=0 (explicitly disabled).
        Expected: Mock path runs (flag is off)."""
        os.environ["DARWIN_LIVE"] = "0"
        result = darwin_determinations.determine()
        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")

    def test_mock_path_live_with_trailing_whitespace(self):
        """Test: DARWIN_LIVE='1  ' (with trailing whitespace).
        Expected: Live path is enabled (whitespace is stripped)."""
        os.environ["DARWIN_LIVE"] = "1  "
        with patch("darwin_determinations._live_determine") as mock_live:
            mock_live.return_value = "LIVE_RESULT"
            result = darwin_determinations.determine()
            mock_live.assert_called_once()

    def test_backwards_compatibility_no_args(self):
        """Test: determine() can be called with no arguments.
        Expected: Public signature is unchanged."""
        # This should not raise
        result = darwin_determinations.determine()
        self.assertIsInstance(result, str)

    def test_mock_determine_direct(self):
        """Test: _mock_determine() returns deterministic result."""
        result = darwin_determinations._mock_determine()
        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")


class TestDarwinDeterminationsLive(unittest.TestCase):
    """Test cases for live model path."""

    def setUp(self):
        """Clear all DARWIN_* env vars before each test."""
        for key in ("DARWIN_LIVE", "DARWIN_API_KEY", "DARWIN_MODEL", "ANTHROPIC_API_KEY"):
            if key in os.environ:
                del os.environ[key]

    def test_live_path_with_valid_key(self):
        """Test: DARWIN_LIVE=1, DARWIN_API_KEY='valid_key', DARWIN_MODEL unset.
        Expected: Live path attempts call with default model."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"

        # Mock the Anthropic client
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="LIVE_RESULT")]
        mock_client.messages.create.return_value = mock_message

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = darwin_determinations.determine()
            self.assertEqual(result, "LIVE_RESULT")
            # Verify client was called with the API key
            mock_client.messages.create.assert_called_once()

    def test_live_path_with_custom_model(self):
        """Test: DARWIN_LIVE=1, DARWIN_API_KEY='valid_key', DARWIN_MODEL='custom-model-id'.
        Expected: Live path attempts call with custom-model-id."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"
        os.environ["DARWIN_MODEL"] = "custom-model-id"

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="LIVE_RESULT")]
        mock_client.messages.create.return_value = mock_message

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = darwin_determinations.determine()
            # Verify the custom model was passed
            call_kwargs = mock_client.messages.create.call_args[1]
            self.assertEqual(call_kwargs["model"], "custom-model-id")

    def test_live_path_without_api_key(self):
        """Test: DARWIN_LIVE=1, DARWIN_API_KEY unset.
        Expected: Live path attempts call with ambient credentials."""
        os.environ["DARWIN_LIVE"] = "1"

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="LIVE_RESULT")]
        mock_client.messages.create.return_value = mock_message

        with patch("anthropic.Anthropic", return_value=mock_client) as mock_anthropic:
            result = darwin_determinations.determine()
            self.assertEqual(result, "LIVE_RESULT")
            # Verify client was created without explicit api_key
            mock_anthropic.assert_called_once_with()

    def test_live_path_with_invalid_key_fallback(self):
        """Test: DARWIN_LIVE=1, DARWIN_API_KEY='invalid_key'.
        Expected: Exception caught, mock fallback silently runs, logged to stderr."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "invalid_key"

        # Mock Anthropic to raise an exception
        with patch("anthropic.Anthropic", side_effect=Exception("Invalid API key")):
            with patch("darwin_determinations.log") as mock_log:
                result = darwin_determinations.determine()
                # Should fall back to mock
                self.assertEqual(result, "MOCK_DETERMINATION_RESULT")
                # Should log the error
                mock_log.error.assert_called_once()
                error_call_args = mock_log.error.call_args[0]
                self.assertIn("[DARWIN]", error_call_args[0])
                self.assertIn("falling back to mock", error_call_args[0])

    def test_live_path_with_default_model(self):
        """Test: DARWIN_LIVE=1, DARWIN_API_KEY='valid_key', DARWIN_MODEL unset.
        Expected: Uses default model claude-haiku-4-5-20251001."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="LIVE_RESULT")]
        mock_client.messages.create.return_value = mock_message

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = darwin_determinations.determine()
            # Verify default model was used
            call_kwargs = mock_client.messages.create.call_args[1]
            self.assertEqual(call_kwargs["model"], "claude-haiku-4-5-20251001")

    def test_live_path_empty_response(self):
        """Test: DARWIN_LIVE=1, API returns empty content.
        Expected: Returns LIVE_DETERMINATION_EMPTY."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = []
        mock_client.messages.create.return_value = mock_message

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = darwin_determinations.determine()
            self.assertEqual(result, "LIVE_DETERMINATION_EMPTY")

    def test_live_path_import_error(self):
        """Test: DARWIN_LIVE=1, anthropic module import fails.
        Expected: Exception caught, mock fallback silently runs."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"

        # Mock the import error by making Anthropic raise ImportError
        def create_client(*args, **kwargs):
            raise ImportError("No module named 'anthropic'")

        with patch("anthropic.Anthropic", side_effect=create_client):
            with patch("darwin_determinations.log") as mock_log:
                result = darwin_determinations.determine()
                self.assertEqual(result, "MOCK_DETERMINATION_RESULT")
                mock_log.error.assert_called_once()

    def test_live_path_network_error(self):
        """Test: DARWIN_LIVE=1, network error during API call.
        Expected: Exception caught, mock fallback silently runs."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("Connection timeout")

        with patch("anthropic.Anthropic", return_value=mock_client):
            with patch("darwin_determinations.log") as mock_log:
                result = darwin_determinations.determine()
                self.assertEqual(result, "MOCK_DETERMINATION_RESULT")
                mock_log.error.assert_called_once()


class TestDarwinDeterminationsTruthTable(unittest.TestCase):
    """Test suite covering the env var truth table."""

    def setUp(self):
        """Clear all DARWIN_* env vars before each test."""
        for key in ("DARWIN_LIVE", "DARWIN_API_KEY", "DARWIN_MODEL", "ANTHROPIC_API_KEY"):
            if key in os.environ:
                del os.environ[key]

    def test_truth_table_unset_unset_unset(self):
        """Truth table row 1: DARWIN_LIVE=unset, DARWIN_API_KEY=unset, DARWIN_MODEL=unset.
        Expected: Mock path runs, result is deterministic."""
        result = darwin_determinations.determine()
        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")

    def test_truth_table_0_any_any(self):
        """Truth table row 2: DARWIN_LIVE=0, DARWIN_API_KEY=any, DARWIN_MODEL=any.
        Expected: Mock path runs (flag is off)."""
        os.environ["DARWIN_LIVE"] = "0"
        os.environ["DARWIN_API_KEY"] = "dummy_key"
        os.environ["DARWIN_MODEL"] = "dummy_model"
        result = darwin_determinations.determine()
        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")

    def test_truth_table_1_valid_key_unset(self):
        """Truth table row 3: DARWIN_LIVE=1, DARWIN_API_KEY=valid key, DARWIN_MODEL=unset.
        Expected: Live path attempts call with default model."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "sk-valid-key"

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="LIVE_RESULT")]
        mock_client.messages.create.return_value = mock_message

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = darwin_determinations.determine()
            self.assertEqual(result, "LIVE_RESULT")
            # Verify default model was used
            call_kwargs = mock_client.messages.create.call_args[1]
            self.assertEqual(call_kwargs["model"], "claude-haiku-4-5-20251001")

    def test_truth_table_1_valid_key_custom_model(self):
        """Truth table row 4: DARWIN_LIVE=1, DARWIN_API_KEY=valid key, DARWIN_MODEL=custom.
        Expected: Live path attempts call with custom model."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "sk-valid-key"
        os.environ["DARWIN_MODEL"] = "custom-model-id"

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="LIVE_RESULT")]
        mock_client.messages.create.return_value = mock_message

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = darwin_determinations.determine()
            call_kwargs = mock_client.messages.create.call_args[1]
            self.assertEqual(call_kwargs["model"], "custom-model-id")

    def test_truth_table_1_unset_any(self):
        """Truth table row 5: DARWIN_LIVE=1, DARWIN_API_KEY=unset, DARWIN_MODEL=any.
        Expected: Live path attempts call with ambient credentials."""
        os.environ["DARWIN_LIVE"] = "1"

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="LIVE_RESULT")]
        mock_client.messages.create.return_value = mock_message

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = darwin_determinations.determine()
            self.assertEqual(result, "LIVE_RESULT")
            # Verify Anthropic was called without explicit api_key arg
            # Note: we can't easily check Anthropic's call args via patch, but we validated above
            pass

    def test_truth_table_1_invalid_key_any(self):
        """Truth table row 6: DARWIN_LIVE=1, DARWIN_API_KEY=invalid key, DARWIN_MODEL=any.
        Expected: Exception caught, mock fallback silently runs, logged to stderr."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "invalid_key"

        with patch("anthropic.Anthropic", side_effect=Exception("Invalid key")):
            with patch("darwin_determinations.log") as mock_log:
                result = darwin_determinations.determine()
                self.assertEqual(result, "MOCK_DETERMINATION_RESULT")
                mock_log.error.assert_called_once()
                error_message = str(mock_log.error.call_args)
                self.assertIn("[DARWIN]", error_message)


class TestDarwinDeterminationsIntegration(unittest.TestCase):
    """Integration tests."""

    def setUp(self):
        """Clear all DARWIN_* env vars before each test."""
        for key in ("DARWIN_LIVE", "DARWIN_API_KEY", "DARWIN_MODEL", "ANTHROPIC_API_KEY"):
            if key in os.environ:
                del os.environ[key]

    def test_integration_fallback_on_missing_module(self):
        """Integration: Missing anthropic module -> fallback works."""
        os.environ["DARWIN_LIVE"] = "1"

        # Simulate missing anthropic module by making the import raise
        def raise_import_error(*args, **kwargs):
            raise ImportError("No module named 'anthropic'")

        with patch("anthropic.Anthropic", side_effect=raise_import_error):
            with patch("darwin_determinations.log"):
                result = darwin_determinations.determine()
                self.assertEqual(result, "MOCK_DETERMINATION_RESULT")

    def test_integration_multiple_calls_consistent(self):
        """Integration: Multiple calls to determine() with same config return consistent results."""
        # First call with mock path
        result1 = darwin_determinations.determine()
        result2 = darwin_determinations.determine()
        self.assertEqual(result1, result2)
        self.assertEqual(result1, "MOCK_DETERMINATION_RESULT")

    def test_integration_live_to_mock_fallback(self):
        """Integration: Live path failure gracefully falls back to mock."""
        os.environ["DARWIN_LIVE"] = "1"

        # Simulate API call failure
        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.create.side_effect = RuntimeError("API Error")
            with patch("darwin_determinations.log"):
                result = darwin_determinations.determine()
                self.assertEqual(result, "MOCK_DETERMINATION_RESULT")


class TestDarwinDeterminationsLogging(unittest.TestCase):
    """Test logging behavior."""

    def setUp(self):
        """Clear all DARWIN_* env vars before each test."""
        for key in ("DARWIN_LIVE", "DARWIN_API_KEY", "DARWIN_MODEL", "ANTHROPIC_API_KEY"):
            if key in os.environ:
                del os.environ[key]

    def test_error_logging_format(self):
        """Test: Error logging includes exception type and message."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "invalid"

        with patch("anthropic.Anthropic", side_effect=ValueError("Bad value")):
            with patch("darwin_determinations.log") as mock_log:
                darwin_determinations.determine()
                # Verify logging call
                mock_log.error.assert_called_once()
                call_args = mock_log.error.call_args
                # Check the format string and arguments
                self.assertIn("[DARWIN]", call_args[0][0])
                self.assertIn("falling back to mock", call_args[0][0])
                # Check that exception info is in the args
                self.assertIn("ValueError", str(call_args[0]))

    def test_no_logging_on_mock_path(self):
        """Test: Mock path does not produce log messages."""
        with patch("darwin_determinations.log") as mock_log:
            darwin_determinations.determine()
            mock_log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
