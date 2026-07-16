#!/usr/bin/env python3
"""
Test intent_compiler.execute() fail-soft error handling.

Acceptance criteria:
  - All execution failures return a dict with success=False; none raise
  - Timeout (subprocess.TimeoutExpired) is reported as output="timeout"
  - Empty or missing script body is detected before subprocess is invoked
  - Non-zero exit codes and missing success marker both yield success=False
  - Unexpected exceptions from subprocess are captured in "output", not re-raised
  - A successful run (rc=0, "COMPILED_SUCCESS" in stdout) returns success=True
"""
import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import intent_compiler

# Minimal compiled entry used across multiple tests
_COMPILED = {"intent_fp": "test-fp", "script": "#!/bin/bash\necho ok"}


class TestExecuteFailSoft(unittest.TestCase):
    """intent_compiler.execute() must never raise; failures are returned as dicts."""

    # ── missing / empty script ───────────────────────────────────────────────

    def test_empty_script_returns_failure_without_subprocess(self):
        """An entry with no script body must fail immediately, never spawning a process."""
        result = intent_compiler.execute({"intent_fp": "x", "script": ""}, repo=".")
        self.assertFalse(result["success"])
        self.assertIn("no script", result["output"])
        self.assertEqual(result["cost_usd"], 0)

    def test_missing_script_key_returns_failure(self):
        """An entry dict without the 'script' key must not raise a KeyError."""
        result = intent_compiler.execute({"intent_fp": "x"}, repo=".")
        self.assertFalse(result["success"])

    # ── timeout (performance-related failure) ────────────────────────────────

    def test_timeout_returns_failure_not_exception(self):
        """subprocess.TimeoutExpired must be caught and reported as output='timeout'."""
        with patch("intent_compiler.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="bash", timeout=180)):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".", task_id="t1")
        self.assertFalse(result["success"])
        self.assertEqual(result["output"], "timeout")
        self.assertEqual(result["cost_usd"], 0)

    def test_timeout_does_not_propagate_exception(self):
        """execute() must not let TimeoutExpired escape to the caller."""
        with patch("intent_compiler.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="bash", timeout=180)):
            with patch("intent_compiler._compiled_store", return_value={}):
                try:
                    result = intent_compiler.execute(_COMPILED, repo=".")
                except subprocess.TimeoutExpired:
                    self.fail("TimeoutExpired escaped execute()")
        self.assertIsInstance(result, dict)

    # ── non-zero exit code ───────────────────────────────────────────────────

    def test_nonzero_exit_returns_failure(self):
        """A non-zero return code must yield success=False even with stdout."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "some output"
        mock_result.stderr = "error details"
        with patch("intent_compiler.subprocess.run", return_value=mock_result):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".")
        self.assertFalse(result["success"])

    def test_zero_exit_without_marker_returns_failure(self):
        """rc=0 but missing COMPILED_SUCCESS marker must still be failure."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "all done but no marker"
        mock_result.stderr = ""
        with patch("intent_compiler.subprocess.run", return_value=mock_result):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".")
        self.assertFalse(result["success"])

    # ── unexpected exceptions ────────────────────────────────────────────────

    def test_unexpected_exception_captured_in_output(self):
        """Any unexpected exception from subprocess must be captured, not re-raised."""
        with patch("intent_compiler.subprocess.run",
                   side_effect=OSError("disk full")):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".")
        self.assertFalse(result["success"])
        self.assertIn("disk full", result["output"])
        self.assertEqual(result["cost_usd"], 0)

    # ── successful run ───────────────────────────────────────────────────────

    def test_successful_run_returns_true(self):
        """rc=0 + COMPILED_SUCCESS in stdout => success=True, cost=0."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "COMPILED_SUCCESS"
        mock_result.stderr = ""
        with patch("intent_compiler.subprocess.run", return_value=mock_result):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".")
        self.assertTrue(result["success"])
        self.assertEqual(result["cost_usd"], 0)
        self.assertEqual(result["tokens"], 0)


if __name__ == "__main__":
    unittest.main()
