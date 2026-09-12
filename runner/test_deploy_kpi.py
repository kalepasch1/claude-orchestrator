import pytest
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
    def test_default_write_function(self):
        writer = KPIWriter()

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        result = writer.write_kpi(record)
        assert result is True
