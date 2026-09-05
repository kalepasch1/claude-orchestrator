import pytest
from datetime import datetime, timedelta
from runner.contracts import validate_kpi_record, KPIRecord, DeployStatus


class TestKPIRecordValidation:
    def test_valid_record_minimal(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }
        is_valid, error = validate_kpi_record(record)
        assert is_valid
        assert error is None

    def test_valid_record_complete(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "in_progress",
            "duration_seconds": 45.5,
            "error_message": None,
        }
        is_valid, error = validate_kpi_record(record)
        assert is_valid
        assert error is None

    def test_valid_record_with_error_message(self):
        record = {
            "deploy_id": "deploy-456",
            "timestamp": "2026-09-03T14:30:00+02:00",
            "status": "failed",
            "duration_seconds": 120.0,
            "error_message": "Deployment failed: timeout",
        }
        is_valid, error = validate_kpi_record(record)
        assert is_valid
        assert error is None

    def test_missing_deploy_id(self):
        record = {
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "deploy_id is required" in error

    def test_empty_deploy_id(self):
        record = {
            "deploy_id": "",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "deploy_id" in error

    def test_deploy_id_not_string(self):
        record = {
            "deploy_id": 123,
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "deploy_id must be a string" in error

    def test_missing_timestamp(self):
        record = {
            "deploy_id": "deploy-123",
            "status": "succeeded",
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "timestamp is required" in error

    def test_empty_timestamp(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "",
            "status": "succeeded",
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "timestamp" in error

    def test_timestamp_not_iso8601(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026/09/03 12:00:00",
            "status": "succeeded",
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "ISO-8601" in error or "valid ISO-8601" in error

    def test_timestamp_valid_iso8601_formats(self):
        valid_timestamps = [
            "2026-09-03T12:00:00Z",
            "2026-09-03T12:00:00+00:00",
            "2026-09-03T12:00:00-05:00",
            "2026-09-03T12:00:00.123Z",
            "2026-09-03T12:00:00.123456+02:00",
        ]
        for ts in valid_timestamps:
            record = {
                "deploy_id": "deploy-123",
                "timestamp": ts,
                "status": "succeeded",
            }
            is_valid, error = validate_kpi_record(record)
            assert is_valid, f"Timestamp {ts} should be valid: {error}"

    def test_timestamp_future_date(self):
        future = (datetime.now() + timedelta(days=365)).isoformat() + "Z"
        record = {
            "deploy_id": "deploy-123",
            "timestamp": future,
            "status": "succeeded",
        }
        is_valid, error = validate_kpi_record(record)
        assert is_valid

    def test_missing_status(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "status is required" in error

    def test_invalid_status_value(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "pending",
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "status" in error

    def test_valid_status_values(self):
        for status in ["started", "in_progress", "succeeded", "failed"]:
            record = {
                "deploy_id": "deploy-123",
                "timestamp": "2026-09-03T12:00:00Z",
                "status": status,
            }
            is_valid, error = validate_kpi_record(record)
            assert is_valid, f"Status {status} should be valid: {error}"

    def test_status_not_string(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": 1,
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "status must be a string" in error

    def test_negative_duration_seconds(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
            "duration_seconds": -10.0,
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "duration_seconds cannot be negative" in error

    def test_zero_duration_seconds(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
            "duration_seconds": 0,
        }
        is_valid, error = validate_kpi_record(record)
        assert is_valid

    def test_duration_seconds_not_number(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
            "duration_seconds": "45.5",
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "duration_seconds must be a number" in error

    def test_error_message_not_string(self):
        record = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "failed",
            "error_message": 123,
        }
        is_valid, error = validate_kpi_record(record)
        assert not is_valid
        assert "error_message must be a string" in error

    def test_record_not_dict(self):
        is_valid, error = validate_kpi_record("not a dict")
        assert not is_valid
        assert "must be a dictionary" in error

    def test_kpi_record_from_dict(self):
        data = {
            "deploy_id": "deploy-123",
            "timestamp": "2026-09-03T12:00:00Z",
            "status": "succeeded",
            "duration_seconds": 45.5,
            "error_message": None,
        }
        record = KPIRecord.from_dict(data)
        assert record.deploy_id == "deploy-123"
        assert record.timestamp == "2026-09-03T12:00:00Z"
        assert record.status == DeployStatus.SUCCEEDED
        assert record.duration_seconds == 45.5

    def test_kpi_record_to_dict(self):
        record = KPIRecord(
            deploy_id="deploy-123",
            timestamp="2026-09-03T12:00:00Z",
            status=DeployStatus.SUCCEEDED,
            duration_seconds=45.5,
            error_message=None,
        )
        data = record.to_dict()
        assert data["deploy_id"] == "deploy-123"
        assert data["timestamp"] == "2026-09-03T12:00:00Z"
        assert data["status"] == "succeeded"
        assert data["duration_seconds"] == 45.5
        assert data["error_message"] is None
