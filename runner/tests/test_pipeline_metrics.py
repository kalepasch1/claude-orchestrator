#!/usr/bin/env python3
"""Tests for pipeline_metrics.py - observability metrics for test pipelines."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import pipeline_metrics


class RecordMetricTest(unittest.TestCase):
    """Test metric recording with fail-soft error handling."""

    def test_record_metric_success(self):
        """Successfully record a metric."""
        with patch("pipeline_metrics.db.insert") as mock_insert:
            pipeline_metrics.record("test-slug", "deploy", True, 1500, "approved")
            mock_insert.assert_called_once()
            args = mock_insert.call_args[0]
            assert args[0] == "pipeline_metrics"
            row = args[1]
            assert row["slug"] == "test-slug"
            assert row["task_type"] == "deploy"
            assert row["passed"] is True

    def test_record_metric_db_error_is_silent(self):
        """DB error during record() is logged but doesn't raise."""
        with patch("pipeline_metrics.db.insert") as mock_insert:
            mock_insert.side_effect = ConnectionError("DB unreachable")
            # Should not raise
            pipeline_metrics.record("test-slug", "deploy", True, 1500, "approved")
            mock_insert.assert_called_once()

    def test_record_metric_db_error_logs_warning(self):
        """DB error during record() is logged with context."""
        with patch("pipeline_metrics.db.insert") as mock_insert:
            with patch("pipeline_metrics._log.warning") as mock_warn:
                mock_insert.side_effect = ValueError("bad data")
                pipeline_metrics.record("test-slug", "deploy", True, 1500, "approved")
                mock_warn.assert_called_once()
                call_args = mock_warn.call_args[0]
                assert "db.insert failed" in call_args[0]
                assert "test-slug" in call_args
                assert "deploy" in call_args

    def test_record_metric_default_values(self):
        """Record metric with default/empty values."""
        with patch("pipeline_metrics.db.insert") as mock_insert:
            pipeline_metrics.record(None, None, False, 0, None)
            mock_insert.assert_called_once()
            row = mock_insert.call_args[0][1]
            assert row["slug"] == ""
            assert row["task_type"] == "unknown"
            assert row["passed"] is False
            assert row["gate_decision"] == ""


class GetHealthTest(unittest.TestCase):
    """Test health aggregation with fail-soft error handling."""

    def test_get_health_success(self):
        """Successfully retrieve health metrics."""
        mock_rows = [
            {"task_type": "deploy", "passed": True, "duration_ms": 1000, "gate_decision": "approved"},
            {"task_type": "deploy", "passed": False, "duration_ms": 2000, "gate_decision": "rejected"},
            {"task_type": "qafix", "passed": True, "duration_ms": 500, "gate_decision": "approved"},
        ]
        with patch("pipeline_metrics.db.select") as mock_select:
            mock_select.return_value = mock_rows
            result = pipeline_metrics.get_health(60, None)
            assert result["lookback_minutes"] == 60
            assert "deploy" in result["by_task_type"]
            deploy = result["by_task_type"]["deploy"]
            assert deploy["total"] == 2
            assert deploy["passed"] == 1
            assert deploy["failed"] == 1

    def test_get_health_db_error_returns_empty(self):
        """DB error during get_health() returns empty result (fail-soft)."""
        with patch("pipeline_metrics.db.select") as mock_select:
            mock_select.side_effect = TimeoutError("DB timeout")
            result = pipeline_metrics.get_health(60, None)
            assert result["by_task_type"] == {}

    def test_get_health_db_error_logs_warning(self):
        """DB error during get_health() is logged."""
        with patch("pipeline_metrics.db.select") as mock_select:
            with patch("pipeline_metrics._log.warning") as mock_warn:
                mock_select.side_effect = RuntimeError("DB connection lost")
                pipeline_metrics.get_health(120, "deploy")
                mock_warn.assert_called_once()
                call_args = mock_warn.call_args[0]
                assert "db.select failed" in call_args[0]
                assert 120 in call_args

    def test_get_health_with_task_type_filter(self):
        """Filter health metrics by task type."""
        mock_rows = [
            {"task_type": "deploy", "passed": True, "duration_ms": 1000, "gate_decision": "approved"},
        ]
        with patch("pipeline_metrics.db.select") as mock_select:
            mock_select.return_value = mock_rows
            result = pipeline_metrics.get_health(60, "deploy")
            # Verify the task_type parameter was passed to db.select
            select_call = mock_select.call_args[0]
            assert select_call[1].get("task_type") == "eq.deploy"

    def test_get_health_empty_rows(self):
        """Handle empty result set gracefully."""
        with patch("pipeline_metrics.db.select") as mock_select:
            mock_select.return_value = []
            result = pipeline_metrics.get_health(60, None)
            assert result["by_task_type"] == {}

    def test_get_health_missing_fields(self):
        """Handle rows with missing fields gracefully."""
        mock_rows = [
            {"task_type": "deploy", "passed": True},  # missing duration_ms, gate_decision
            {"passed": False, "duration_ms": 2000},  # missing task_type
        ]
        with patch("pipeline_metrics.db.select") as mock_select:
            mock_select.return_value = mock_rows
            result = pipeline_metrics.get_health(60, None)
            assert "deploy" in result["by_task_type"]
            assert "unknown" in result["by_task_type"]


if __name__ == "__main__":
    unittest.main()
