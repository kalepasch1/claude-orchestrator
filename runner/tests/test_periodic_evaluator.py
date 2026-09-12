#!/usr/bin/env python3
"""Tests for periodic_evaluator module."""
import os
import sys
import json
import tempfile
from unittest.mock import patch, MagicMock

import pytest

RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import periodic_evaluator
import counterfactual_replay as cfr


@pytest.fixture(autouse=True)
def reset_state():
    cfr.invalidate()
    yield
    cfr.invalidate()


class TestPeriodicEvaluatorRun:
    """Test periodic evaluator execution."""

    def test_run_returns_dict_with_ok_status(self):
        """Periodic evaluator returns a dict with status."""
        with patch.dict(os.environ, {"ORCH_COUNTERFACTUAL_ENABLED": "true"}):
            result = periodic_evaluator.run()
            assert isinstance(result, dict)
            assert result.get("status") == "ok"
            assert "duration_sec" in result
            assert "stats" in result
            assert "timestamp" in result

    def test_run_returns_disabled_when_not_enabled(self):
        """Periodic evaluator returns disabled status when feature is off."""
        with patch.dict(os.environ, {"ORCH_COUNTERFACTUAL_ENABLED": "false"}):
            result = periodic_evaluator.run()
            assert result.get("status") == "disabled"

    def test_run_includes_stats(self):
        """Periodic evaluator includes replay statistics."""
        with patch.dict(os.environ, {"ORCH_COUNTERFACTUAL_ENABLED": "true"}):
            result = periodic_evaluator.run()
            stats = result.get("stats", {})
            assert "replayed" in stats
            assert "changed" in stats
            assert "errors" in stats

    def test_run_handles_errors_gracefully(self):
        """Periodic evaluator handles errors and returns error status."""
        with patch.dict(os.environ, {"ORCH_COUNTERFACTUAL_ENABLED": "true"}):
            with patch("counterfactual_replay._acquire_storage") as mock_acquire:
                mock_acquire.side_effect = Exception("Test error")
                result = periodic_evaluator.run()
                assert result.get("status") == "error"
                assert "error" in result
                assert "duration_sec" in result

    def test_run_measures_duration(self):
        """Periodic evaluator measures execution duration."""
        with patch.dict(os.environ, {"ORCH_COUNTERFACTUAL_ENABLED": "true"}):
            result = periodic_evaluator.run()
            duration = result.get("duration_sec", 0)
            assert isinstance(duration, (int, float))
            assert duration >= 0

    def test_run_includes_timestamp(self):
        """Periodic evaluator includes ISO format timestamp."""
        with patch.dict(os.environ, {"ORCH_COUNTERFACTUAL_ENABLED": "true"}):
            result = periodic_evaluator.run()
            timestamp = result.get("timestamp")
            assert timestamp is not None
            assert "T" in timestamp  # ISO format check


class TestPeriodicEvaluatorIntegration:
    """Integration tests for periodic evaluator."""

    def test_run_completes_without_decisions(self):
        """Periodic evaluator runs successfully with no decision history."""
        with patch.dict(os.environ, {"ORCH_COUNTERFACTUAL_ENABLED": "true"}):
            result = periodic_evaluator.run()
            assert result.get("status") == "ok"
            stats = result.get("stats", {})
            assert stats.get("replayed", 0) == 0

    def test_main_execution(self):
        """Test direct module execution via __main__."""
        with patch.dict(os.environ, {"ORCH_COUNTERFACTUAL_ENABLED": "true"}):
            with patch("periodic_evaluator.run") as mock_run:
                mock_run.return_value = {"status": "ok", "stats": {}}
                # Verify the module structure supports execution
                assert hasattr(periodic_evaluator, "run")
