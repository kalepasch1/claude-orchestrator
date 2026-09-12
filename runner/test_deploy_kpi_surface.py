"""Tests for deploy_kpi_surface — the reader/summary half of deploy KPI.

Seeds N deploy_kpi records (a mix of succeeded/failed) through a stubbed db,
calls the summary function, and asserts counts, success rate, and ordering of
recent failures.
"""
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from runner.deploy_kpi_surface import (
    DeployKPISummary,
    summarize,
    read_deploy_kpi_summary,
    _parse_kpi_rows,
)


def _ts(hours_ago: float = 0) -> str:
    """ISO-8601 timestamp `hours_ago` hours before now."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(deploy_id, status="succeeded", hours_ago=0,
            duration=45.0, error_message=None):
    return {
        "deploy_id": deploy_id,
        "timestamp": _ts(hours_ago),
        "status": status,
        "duration_seconds": duration,
        "error_message": error_message,
    }


def _wrap_as_rows(records):
    """Wrap KPI records as coordination_tasks rows with JSON payload."""
    return [{"payload": json.dumps(r)} for r in records]


# ── summarize() pure-logic tests ──────────────────────────────────────

class TestSummarizeEmpty:
    def test_empty_records(self):
        s = summarize([], window_hours=24)
        assert s.total_deploys == 0
        assert s.succeeded == 0
        assert s.failed == 0
        assert s.success_rate is None
        assert s.median_duration_seconds is None
        assert s.recent_failures == []

    def test_to_dict_returns_dict(self):
        s = summarize([])
        d = s.to_dict()
        assert isinstance(d, dict)
        assert "total_deploys" in d


class TestSummarizeMixed:
    def test_counts_and_rate(self):
        records = [
            _record("d1", "succeeded", hours_ago=1, duration=30),
            _record("d2", "succeeded", hours_ago=2, duration=50),
            _record("d3", "succeeded", hours_ago=3, duration=40),
            _record("d4", "failed", hours_ago=4, duration=120,
                    error_message="Timeout during build"),
            _record("d5", "failed", hours_ago=5, duration=90,
                    error_message="OOM in container"),
        ]
        s = summarize(records, window_hours=24)
        assert s.total_deploys == 5
        assert s.succeeded == 3
        assert s.failed == 2
        assert s.success_rate == 0.6

    def test_median_duration(self):
        records = [
            _record("d1", duration=10),
            _record("d2", duration=20),
            _record("d3", duration=30),
            _record("d4", duration=40),
            _record("d5", duration=50),
        ]
        s = summarize(records, window_hours=24)
        assert s.median_duration_seconds == 30.0

    def test_median_duration_even_count(self):
        records = [
            _record("d1", duration=10),
            _record("d2", duration=20),
            _record("d3", duration=30),
            _record("d4", duration=40),
        ]
        s = summarize(records, window_hours=24)
        assert s.median_duration_seconds == 25.0

    def test_recent_failures_ordered_newest_first(self):
        records = [
            _record("d1", "failed", hours_ago=10, error_message="old error"),
            _record("d2", "failed", hours_ago=2, error_message="new error"),
            _record("d3", "failed", hours_ago=5, error_message="mid error"),
        ]
        s = summarize(records, window_hours=24)
        assert len(s.recent_failures) == 3
        assert s.recent_failures[0]["deploy_id"] == "d2"
        assert s.recent_failures[0]["error_message"] == "new error"
        assert s.recent_failures[1]["deploy_id"] == "d3"
        assert s.recent_failures[2]["deploy_id"] == "d1"

    def test_recent_failures_capped_at_10(self):
        records = [
            _record(f"d{i}", "failed", hours_ago=i, error_message=f"err {i}")
            for i in range(15)
        ]
        s = summarize(records, window_hours=24)
        assert len(s.recent_failures) == 10

    def test_all_succeeded(self):
        records = [_record(f"d{i}", "succeeded") for i in range(5)]
        s = summarize(records, window_hours=24)
        assert s.success_rate == 1.0
        assert s.failed == 0
        assert s.recent_failures == []

    def test_all_failed(self):
        records = [
            _record(f"d{i}", "failed", error_message=f"err{i}")
            for i in range(3)
        ]
        s = summarize(records, window_hours=24)
        assert s.success_rate == 0.0
        assert s.succeeded == 0
        assert s.failed == 3


class TestSummarizeEdgeCases:
    def test_missing_duration_excluded_from_median(self):
        records = [
            _record("d1", duration=10),
            _record("d2", duration=None),
            _record("d3", duration=30),
        ]
        s = summarize(records, window_hours=24)
        assert s.median_duration_seconds == 20.0

    def test_negative_duration_excluded(self):
        records = [
            _record("d1", duration=10),
            _record("d2", duration=-5),
            _record("d3", duration=30),
        ]
        s = summarize(records, window_hours=24)
        assert s.median_duration_seconds == 20.0

    def test_window_filters_old_records(self):
        records = [
            _record("d1", "succeeded", hours_ago=1),
            _record("d2", "succeeded", hours_ago=2),
            _record("d3", "succeeded", hours_ago=25),  # outside 24h window
            _record("d4", "failed", hours_ago=48),      # outside 24h window
        ]
        s = summarize(records, window_hours=24)
        assert s.total_deploys == 2
        assert s.succeeded == 2

    def test_missing_timestamp_included(self):
        records = [
            {"deploy_id": "d1", "status": "succeeded", "duration_seconds": 10},
        ]
        s = summarize(records, window_hours=24)
        assert s.total_deploys == 1

    def test_string_duration_excluded(self):
        records = [
            _record("d1", duration="fast"),
            _record("d2", duration=20),
        ]
        s = summarize(records, window_hours=24)
        assert s.median_duration_seconds == 20.0


# ── _parse_kpi_rows tests ────────────────────────────────────────────

class TestParseKPIRows:
    def test_valid_json_payload(self):
        rows = [{"payload": '{"deploy_id": "d1", "status": "succeeded"}'}]
        records = _parse_kpi_rows(rows)
        assert len(records) == 1
        assert records[0]["deploy_id"] == "d1"

    def test_dict_payload_passthrough(self):
        rows = [{"payload": {"deploy_id": "d1", "status": "succeeded"}}]
        records = _parse_kpi_rows(rows)
        assert len(records) == 1

    def test_empty_payload_skipped(self):
        rows = [{"payload": ""}, {"payload": None}, {}]
        records = _parse_kpi_rows(rows)
        assert len(records) == 0

    def test_malformed_json_skipped(self):
        rows = [{"payload": "not json{"}]
        records = _parse_kpi_rows(rows)
        assert len(records) == 0

    def test_non_dict_json_skipped(self):
        rows = [{"payload": "[1,2,3]"}]
        records = _parse_kpi_rows(rows)
        assert len(records) == 0


# ── read_deploy_kpi_summary integration tests ────────────────────────

class TestReadDeployKPISummary:
    def test_with_stubbed_db(self):
        records = [
            _record("d1", "succeeded", hours_ago=1, duration=30),
            _record("d2", "succeeded", hours_ago=2, duration=50),
            _record("d3", "failed", hours_ago=3, duration=120,
                    error_message="Build timeout"),
        ]
        rows = _wrap_as_rows(records)

        mock_db = Mock()
        mock_db.select = Mock(return_value=rows)

        s = read_deploy_kpi_summary(window_hours=24, db_module=mock_db)

        assert s.total_deploys == 3
        assert s.succeeded == 2
        assert s.failed == 1
        assert s.success_rate == pytest.approx(0.6667, abs=0.001)
        assert s.median_duration_seconds == 50.0
        assert len(s.recent_failures) == 1
        assert s.recent_failures[0]["error_message"] == "Build timeout"

    def test_db_unavailable_returns_empty(self):
        mock_db = Mock()
        mock_db.select = Mock(side_effect=Exception("Connection refused"))

        s = read_deploy_kpi_summary(db_module=mock_db)

        assert s.total_deploys == 0
        assert s.success_rate is None
        assert s.recent_failures == []

    def test_empty_table_returns_empty(self):
        mock_db = Mock()
        mock_db.select = Mock(return_value=[])

        s = read_deploy_kpi_summary(db_module=mock_db)

        assert s.total_deploys == 0
        assert s.success_rate is None

    def test_no_db_module_returns_empty(self):
        s = read_deploy_kpi_summary(db_module=None)
        # Will fail to import db (not in test env), returns empty
        assert isinstance(s, DeployKPISummary)
        assert s.total_deploys == 0


class TestReadDeployKPISummaryAcceptance:
    """Acceptance test per the task spec: seed N deploy_kpi rows through a
    stubbed db, call the read/summary function, assert counts, success rate,
    and ordering of recent failures."""

    def test_acceptance_mixed_deploys(self):
        records = [
            _record("deploy-001", "succeeded", hours_ago=1, duration=32.5),
            _record("deploy-002", "succeeded", hours_ago=2, duration=41.0),
            _record("deploy-003", "succeeded", hours_ago=3, duration=28.0),
            _record("deploy-004", "succeeded", hours_ago=4, duration=55.0),
            _record("deploy-005", "succeeded", hours_ago=5, duration=38.0),
            _record("deploy-006", "succeeded", hours_ago=6, duration=44.0),
            _record("deploy-007", "failed", hours_ago=1.5, duration=180.0,
                    error_message="OOM in container during build"),
            _record("deploy-008", "failed", hours_ago=3.5, duration=95.0,
                    error_message="Test suite timeout"),
            _record("deploy-009", "failed", hours_ago=7, duration=60.0,
                    error_message="Vercel deploy hook 500"),
            _record("deploy-010", "started", hours_ago=0.5, duration=None,
                    error_message=None),
        ]
        rows = _wrap_as_rows(records)

        mock_db = Mock()
        mock_db.select = Mock(return_value=rows)

        s = read_deploy_kpi_summary(window_hours=24, db_module=mock_db)

        # Counts
        assert s.total_deploys == 10
        assert s.succeeded == 6
        assert s.failed == 4  # 3 failed + 1 started
        assert s.success_rate == 0.6

        # Median duration (of records with valid duration):
        # 28, 32.5, 38, 41, 44, 55, 60, 95, 180 → median = 44.0
        assert s.median_duration_seconds == 44.0

        # Recent failures: newest first
        assert len(s.recent_failures) == 4
        assert s.recent_failures[0]["deploy_id"] == "deploy-010"  # 0.5h ago
        assert s.recent_failures[1]["deploy_id"] == "deploy-007"  # 1.5h ago
        assert s.recent_failures[2]["deploy_id"] == "deploy-008"  # 3.5h ago
        assert s.recent_failures[3]["deploy_id"] == "deploy-009"  # 7h ago
        assert s.recent_failures[1]["error_message"] == "OOM in container during build"
