"""Tests for runner/log.py structured logging module."""
import logging
import os
import sys
import unittest
from unittest import mock

# Ensure the runner package is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import log  # noqa: E402


class TestGet(unittest.TestCase):
    """Tests for log.get()."""

    def test_returns_logger_instance(self):
        logger = log.get("test.module")
        self.assertIsInstance(logger, logging.Logger)

    def test_same_name_returns_same_logger(self):
        a = log.get("test.identity")
        b = log.get("test.identity")
        self.assertIs(a, b)

    def test_different_names_return_different_loggers(self):
        a = log.get("test.alpha")
        b = log.get("test.beta")
        self.assertIsNot(a, b)


class TestWithTask(unittest.TestCase):
    """Tests for log.with_task()."""

    def test_returns_logger_adapter(self):
        logger = log.get("test.adapter")
        adapter = log.with_task(logger, "task-42")
        self.assertIsInstance(adapter, logging.LoggerAdapter)

    def test_adapter_carries_task_id(self):
        logger = log.get("test.adapter.extra")
        adapter = log.with_task(logger, "task-99")
        self.assertEqual(adapter.extra["task_id"], "task-99")


class TestEnsureConfigured(unittest.TestCase):
    """Tests for _ensure_configured() idempotency and env handling."""

    def test_idempotent(self):
        # Calling twice should not raise.
        log._ensure_configured()
        log._ensure_configured()

    def test_log_level_env_respected(self):
        # Reset the module-level flag so _ensure_configured re-runs.
        log._configured = False
        with mock.patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            with mock.patch("logging.basicConfig") as mock_bc:
                log._ensure_configured()
                mock_bc.assert_called_once()
                call_kwargs = mock_bc.call_args[1]
                self.assertEqual(call_kwargs["level"], logging.DEBUG)
        # Restore so other tests are not affected.
        log._configured = False
        log._ensure_configured()

    def test_invalid_log_level_falls_back_to_info(self):
        log._configured = False
        with mock.patch.dict(os.environ, {"LOG_LEVEL": "BOGUS"}):
            with mock.patch("logging.basicConfig") as mock_bc:
                log._ensure_configured()
                call_kwargs = mock_bc.call_args[1]
                self.assertEqual(call_kwargs["level"], logging.INFO)
        log._configured = False
        log._ensure_configured()


if __name__ == "__main__":
    unittest.main()
