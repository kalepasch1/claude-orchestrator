import pytest
import json
import sys
import time
from unittest.mock import Mock, patch, call
from runner.deploy_kpi import KPIWriter, write_deploy_kpi, MAX_RETRIES


class TestKPIWriterSuccess:
    def test_write_kpi_success(self):
        mock_write = Mock(return_value=True)
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
            "duration_seconds": 45.5,
        }

        result = writer.write_kpi(record)
        assert result is True
        mock_write.assert_called_once_with(record)

    def test_write_deploy_kpi_convenience_function(self):
        mock_write = Mock(return_value=True)

        result = write_deploy_kpi(
            deploy_id="deploy-123",
            timestamp="2026-09-03T12:00:00Z",
            status="succeeded",
            duration_seconds=45.5,
            write_func=mock_write,
        )

        assert result is True
        assert mock_write.called


class TestKPIWriterFailSoft:
    def test_invalid_record_fails_soft(self):
        mock_write = Mock(return_value=True)
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        result = writer.write_kpi(record)
        assert result is False
        mock_write.assert_not_called()

    def test_write_destination_unavailable_fails_soft(self):
        mock_write = Mock(side_effect=Exception("Connection refused"))
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        result = writer.write_kpi(record)
        assert result is False
        assert mock_write.call_count == MAX_RETRIES

    def test_write_returns_false_fails_soft(self):
        mock_write = Mock(return_value=False)
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        result = writer.write_kpi(record)
        assert result is False
        assert mock_write.call_count == MAX_RETRIES


class TestKPIWriterRetry:
    def test_retry_on_exception_then_success(self):
        mock_write = Mock(side_effect=[Exception("Error"), Exception("Error"), True])
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        result = writer.write_kpi(record)
        assert result is True
        assert mock_write.call_count == 3

    def test_retry_on_false_then_success(self):
        mock_write = Mock(side_effect=[False, False, True])
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        result = writer.write_kpi(record)
        assert result is True
        assert mock_write.call_count == 3

    def test_retry_success_on_first_attempt(self):
        mock_write = Mock(return_value=True)
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        result = writer.write_kpi(record)
        assert result is True
        assert mock_write.call_count == 1

    def test_retry_exhaustion_logs_warning(self):
        mock_write = Mock(side_effect=Exception("Network error"))
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        with patch("runner.deploy_kpi.logger") as mock_logger:
            result = writer.write_kpi(record)
            assert result is False
            assert mock_logger.warning.call_count >= 4


class TestKPIWriterIdempotency:
    def test_idempotent_write(self):
        mock_write = Mock(return_value=True)
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
            "duration_seconds": 45.5,
        }

        result1 = writer.write_kpi(record)
        result2 = writer.write_kpi(record)

        assert result1 is True
        assert result2 is True
        assert mock_write.call_count == 2


class TestKPIWriterDataConsistency:
    def test_kpi_record_data_consistency(self):
        captured_record = None

        def capture_write(record):
            nonlocal captured_record
            captured_record = record
            return True

        writer = KPIWriter(capture_write)

        record = {
            "deploy_id": "deploy-456",
            "timestamp": "2026-09-03T14:30:00+02:00",
            "status": "failed",
            "duration_seconds": 120.0,
            "error_message": "Timeout during deployment",
        }

        result = writer.write_kpi(record)
        assert result is True
        assert captured_record == record


class TestKPIWriterRetryBackoff:
    def test_exponential_backoff_timing(self):
        mock_write = Mock(side_effect=Exception("Error"))
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        start = time.time()
        result = writer.write_kpi(record)
        elapsed = time.time() - start

        assert result is False
        assert elapsed >= 3


class TestDefaultKPIWriter:
    """The default write path, corrected.

    This class previously asserted `write_kpi(...) is True` against a
    `_default_write` that logged at DEBUG and returned True without writing
    anything anywhere. The assertion passed and the contract was false: any
    caller that did not supply its own `write_func` was told the KPI had been
    recorded, so a dashboard built on this writer would have shown an empty
    table while every deploy reported a successful KPI write.

    The default now persists to `coordination_tasks` and returns whether the row
    actually landed. These tests pin both directions, because the failure that
    hid here was a success value, not an exception.
    """

    RECORD = {
        "deploy_id": "deploy-123",
        "timestamp": "2026-09-03T12:00:00Z",
        "status": "succeeded",
    }

    def test_a_row_is_written_and_success_is_reported(self, monkeypatch):
        import runner.deploy_kpi as dk

        written = []

        class FakeDb:
            @staticmethod
            def insert(table, row, upsert=False):
                written.append((table, row))
                return row

        monkeypatch.setitem(sys.modules, "db", FakeDb)

        assert KPIWriter().write_kpi(dict(self.RECORD)) is True
        assert len(written) == 1
        table, row = written[0]
        assert table == "coordination_tasks"
        assert row["task_type"] == "deploy_kpi"
        assert json.loads(row["payload"])["deploy_id"] == "deploy-123"

    def test_an_unreachable_backend_reports_failure_rather_than_success(
            self, monkeypatch):
        """The regression this class exists for.

        Returning True here is what made the writer look healthy while storing
        nothing. False is the honest answer; the retry wrapper treats it as
        "try again" and, after exhaustion, logs and lets the deploy continue.
        """
        import runner.deploy_kpi as dk

        class DownDb:
            @staticmethod
            def insert(table, row, upsert=False):
                raise RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY")

        monkeypatch.setitem(sys.modules, "db", DownDb)
        monkeypatch.setattr(dk.time, "sleep", lambda s: None)

        assert KPIWriter().write_kpi(dict(self.RECORD)) is False

    def test_a_write_failure_never_raises_into_the_deploy(self, monkeypatch):
        # A KPI is telemetry. It must not be able to fail a deployment.
        import runner.deploy_kpi as dk

        class Exploding:
            @staticmethod
            def insert(table, row, upsert=False):
                raise MemoryError("boom")

        monkeypatch.setitem(sys.modules, "db", Exploding)
        monkeypatch.setattr(dk.time, "sleep", lambda s: None)

        assert KPIWriter().write_kpi(dict(self.RECORD)) is False

    def test_the_payload_is_bounded(self, monkeypatch):
        # coordination_tasks.payload is a text column shared by the whole fleet;
        # an unbounded error_message would be a way to fill it.
        written = []

        class FakeDb:
            @staticmethod
            def insert(table, row, upsert=False):
                written.append(row)
                return row

        monkeypatch.setitem(sys.modules, "db", FakeDb)
        record = dict(self.RECORD, status="failed", error_message="x" * 50000)

        KPIWriter().write_kpi(record)
        assert len(written[0]["payload"]) <= 8000

    def test_an_invalid_record_is_rejected_before_any_write_is_attempted(
            self, monkeypatch):
        attempts = []

        class FakeDb:
            @staticmethod
            def insert(table, row, upsert=False):
                attempts.append(row)
                return row

        monkeypatch.setitem(sys.modules, "db", FakeDb)

        assert KPIWriter().write_kpi({"deploy_id": "", "timestamp": "",
                                      "status": "succeeded"}) is False
        assert attempts == [], "a record that failed validation was still written"
