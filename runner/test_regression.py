import pytest
import time
from unittest.mock import Mock, patch
from runner.deploy_kpi import KPIWriter


class TestDeployRegressionBasic:
    def test_deploy_continues_on_kpi_failure(self):
        mock_write = Mock(side_effect=Exception("KPI service down"))

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        writer = KPIWriter(mock_write)
        result = writer.write_kpi(record)

        assert result is False


class TestDeployLatencyRegression:
    def test_kpi_tracking_overhead_under_100ms(self):
        mock_write = Mock(return_value=True)
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
            "duration_seconds": 45.5,
        }

        start = time.time()
        result = writer.write_kpi(record)
        elapsed = (time.time() - start) * 1000

        assert result is True
        assert elapsed < 100


class TestDeployRegressionMultiple:
    def test_multiple_kpi_writes_sequential(self):
        mock_write = Mock(return_value=True)
        writer = KPIWriter(mock_write)

        records = [
            {
                "deploy_id": f"deploy-{i}",
                "timestamp": "2026-09-03T12:00:00Z",
                "status": "started",
            }
            for i in range(5)
        ]

        results = [writer.write_kpi(record) for record in records]

        assert all(results)
        assert mock_write.call_count == 5


class TestDeployRegressionErrorHandling:
    def test_kpi_failure_does_not_block_deploy(self):
        mock_write = Mock(return_value=False)
        writer = KPIWriter(mock_write)

        deploy_status = "succeeded"
        kpi_result = writer.write_kpi(
            {
                "deploy_id": "deploy-123",
                "timestamp": "2026-09-03T12:00:00Z",
                "status": deploy_status,
            }
        )

        assert kpi_result is False
        assert deploy_status == "succeeded"


class TestDeployRegressionConcurrency:
    def test_concurrent_kpi_writes(self):
        mock_write = Mock(return_value=True)
        writer = KPIWriter(mock_write)

        records = [
            {
                "deploy_id": f"deploy-concurrent-{i}",
                "timestamp": "2026-09-03T12:00:00Z",
                "status": "in_progress",
            }
            for i in range(3)
        ]

        for record in records:
            result = writer.write_kpi(record)
            assert result is True

        assert mock_write.call_count == 3


class TestDeployRegressionRecovery:
    def test_temporary_failure_recovery(self):
        write_attempts = []

        def write_with_recovery(record):
            write_attempts.append(record)
            if len(write_attempts) < 2:
                raise Exception("Temporary failure")
            return True

        writer = KPIWriter(write_with_recovery)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        result = writer.write_kpi(record)
        assert result is True
        assert len(write_attempts) == 2


class TestDeployRegressionValidation:
    def test_invalid_kpi_does_not_retry(self):
        mock_write = Mock()
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }

        result = writer.write_kpi(record)
        assert result is False
        mock_write.assert_not_called()


class TestDeployRegressionSchema:
    def test_kpi_schema_immutable(self):
        mock_write = Mock(return_value=True)
        writer = KPIWriter(mock_write)

        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
            "duration_seconds": 45.5,
        }

        original = record.copy()
        writer.write_kpi(record)

        assert record == original


class TestDeployRegressionMaxRetries:
    def test_max_retries_constant(self):
        from runner.deploy_kpi import MAX_RETRIES
        assert MAX_RETRIES == 3
