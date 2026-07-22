"""
Tests for code execution failure handling in intent_compiler.execute().

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
                    intent_compiler.execute(_COMPILED, repo=".", task_id="t1")
                except subprocess.TimeoutExpired:
                    self.fail("TimeoutExpired escaped from execute()")

    # ── runtime / subprocess exceptions ─────────────────────────────────────

    def test_oserror_from_subprocess_returns_failure(self):
        """OSError (e.g. bash not found) must be caught; output contains error text."""
        err = OSError("bash: No such file or directory")
        with patch("intent_compiler.subprocess.run", side_effect=err):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".", task_id="t2")
        self.assertFalse(result["success"])
        self.assertIn("bash", result["output"])

    def test_generic_exception_from_subprocess_returns_failure(self):
        """Any unexpected exception from subprocess.run must be swallowed."""
        err = RuntimeError("unexpected subprocess error")
        with patch("intent_compiler.subprocess.run", side_effect=err):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".", task_id="t3")
        self.assertFalse(result["success"])
        self.assertIn("unexpected subprocess error", result["output"])

    def test_exception_output_is_truncated_to_300_chars(self):
        """Long exception messages are capped so the output field stays bounded."""
        long_msg = "x" * 500
        with patch("intent_compiler.subprocess.run", side_effect=Exception(long_msg)):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".", task_id="t4")
        self.assertFalse(result["success"])
        self.assertLessEqual(len(result["output"]), 300)

    # ── non-zero exit code (syntax/runtime errors in the script) ────────────

    def test_nonzero_returncode_yields_failure(self):
        """A script that exits non-zero must produce success=False (fail-soft)."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "bash: syntax error near unexpected token 'fi'"
        with patch("intent_compiler.subprocess.run", return_value=mock_result):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".", task_id="t5")
        self.assertFalse(result["success"])

    def test_zero_returncode_but_missing_success_marker_is_failure(self):
        """rc=0 without the 'COMPILED_SUCCESS' sentinel is treated as failure."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "something ran but forgot the marker"
        mock_result.stderr = ""
        with patch("intent_compiler.subprocess.run", return_value=mock_result):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".", task_id="t6")
        self.assertFalse(result["success"])

    def test_script_syntax_error_exit_code_127(self):
        """Exit code 127 (command not found / syntax error via bash -c) is a failure."""
        mock_result = MagicMock()
        mock_result.returncode = 127
        mock_result.stdout = ""
        mock_result.stderr = "command not found"
        with patch("intent_compiler.subprocess.run", return_value=mock_result):
            with patch("intent_compiler._compiled_store", return_value={}):
                result = intent_compiler.execute(_COMPILED, repo=".", task_id="t7")
        self.assertFalse(result["success"])

    # ── successful execution (golden path) ──────────────────────────────────

    def test_success_requires_rc0_and_sentinel(self):
        """Only rc=0 AND 'COMPILED_SUCCESS' in stdout produces success=True."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "doing work\nCOMPILED_SUCCESS\n"
        mock_result.stderr = ""
        with patch("intent_compiler.subprocess.run", return_value=mock_result):
            with patch("intent_compiler._compiled_store", return_value={}):
                with patch("intent_compiler._save_compiled"):
                    result = intent_compiler.execute(_COMPILED, repo=".", task_id="t8")
        self.assertTrue(result["success"])
        self.assertEqual(result["cost_usd"], 0)
        self.assertEqual(result["tokens"], 0)

    # ── db unavailability (fail-soft on store lookup) ────────────────────────

    def test_db_failure_in_store_lookup_does_not_raise(self):
        """If the db store lookup throws, get_compiled() must return None, not raise."""
        with patch("intent_compiler.db.select", side_effect=Exception("db down")):
            result = intent_compiler._compiled_store()
        # Returns empty dict — the safe default
        self.assertEqual(result, {})

    def test_get_compiled_swallows_import_error(self):
        """If intent_graph is unavailable, get_compiled() returns None gracefully."""
        task = {"prompt": "some task", "id": "task-1"}
        with patch.dict("sys.modules", {"intent_graph": None}):
            result = intent_compiler.get_compiled(task, repo=".")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
