import re
from datetime import datetime
from enum import Enum
from typing import Optional
from dataclasses import dataclass, asdict


class DeployStatus(str, Enum):
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class KPIRecord:
    deploy_id: str
    timestamp: str
    status: DeployStatus
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict):
        if isinstance(data.get("status"), str):
            data["status"] = DeployStatus(data["status"])
        return cls(**data)

    def to_dict(self):
        return {
            "deploy_id": self.deploy_id,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
        }


def validate_kpi_record(data: dict) -> tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "KPI record must be a dictionary"

    if "deploy_id" not in data or not data["deploy_id"]:
        return False, "deploy_id is required and cannot be empty"

    if not isinstance(data["deploy_id"], str):
        return False, "deploy_id must be a string"

    if "timestamp" not in data or not data["timestamp"]:
        return False, "timestamp is required and cannot be empty"

    if not isinstance(data["timestamp"], str):
        return False, "timestamp must be a string"

    iso_8601_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
    if not re.match(iso_8601_pattern, data["timestamp"]):
        return False, "timestamp must be in ISO-8601 format"

    try:
        datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
    except ValueError:
        return False, "timestamp is not a valid ISO-8601 datetime"

    if "status" not in data:
        return False, "status is required"

    status_value = data["status"]
    if isinstance(status_value, str):
        if status_value not in [s.value for s in DeployStatus]:
            return False, f"status must be one of {[s.value for s in DeployStatus]}, got {status_value}"
    else:
        return False, "status must be a string"

    if "duration_seconds" in data and data["duration_seconds"] is not None:
        if not isinstance(data["duration_seconds"], (int, float)):
            return False, "duration_seconds must be a number"
        if data["duration_seconds"] < 0:
            return False, "duration_seconds cannot be negative"

    if "error_message" in data and data["error_message"] is not None:
        if not isinstance(data["error_message"], str):
            return False, "error_message must be a string"

    return True, None
