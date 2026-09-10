import math
import re
from datetime import datetime
from enum import Enum
from typing import Optional
from dataclasses import dataclass, asdict, fields


class DeployStatus(str, Enum):
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# Precomputed once. `validate_kpi_record` runs on every deploy and built this
# list on each call — twice on the failure path, to make the message.
_STATUS_VALUES = frozenset(s.value for s in DeployStatus)
_STATUS_VALUES_TEXT = ", ".join(sorted(_STATUS_VALUES))

# Compiled once for the same reason. `re.match` with a string pattern consults
# the module cache on every call; a module-level compile skips that entirely.
_ISO_8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$")


@dataclass
class KPIRecord:
    deploy_id: str
    timestamp: str
    status: DeployStatus
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict):
        """Build a record from a plain dict, without editing the caller's dict.

        Two defects fixed here:

        * It mutated its argument. `data["status"] = DeployStatus(...)` wrote an
          enum back into the caller's own dictionary, so code that built a record
          and then re-read its own `record["status"]` — or passed the same dict
          on to be serialised — got an enum where it had put a string. The dict
          is now copied before anything is changed.

        * It accepted only an exactly-shaped dict. An unrecognised key raised
          TypeError from `cls(**data)` and an unknown status raised ValueError
          from the enum. These records come from a deploy path whose whole
          discipline is that telemetry must never fail the deploy, so an extra
          field added upstream should not raise inside it. Unknown keys are now
          ignored and an unknown status raises the same ValueError as before —
          the status IS the record, so a wrong one is not something to shrug at.
        """
        if not isinstance(data, dict):
            raise TypeError("KPIRecord.from_dict expects a dict, got %s"
                            % type(data).__name__)
        known = {f.name for f in fields(cls)}
        payload = {k: v for k, v in data.items() if k in known}
        status = payload.get("status")
        if isinstance(status, str) and not isinstance(status, DeployStatus):
            payload["status"] = DeployStatus(status)
        return cls(**payload)

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

    if not _ISO_8601_RE.match(data["timestamp"]):
        return False, "timestamp must be in ISO-8601 format"

    try:
        datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
    except ValueError:
        return False, "timestamp is not a valid ISO-8601 datetime"

    if "status" not in data:
        return False, "status is required"

    status_value = data["status"]
    if isinstance(status_value, str):
        if status_value not in _STATUS_VALUES:
            return False, (f"status must be one of [{_STATUS_VALUES_TEXT}], "
                           f"got {status_value}")
    else:
        return False, "status must be a string"

    if "duration_seconds" in data and data["duration_seconds"] is not None:
        duration = data["duration_seconds"]
        # bool is a subclass of int, so `isinstance(True, (int, float))` was
        # True and `duration_seconds=True` validated as a number — then landed
        # in the payload as `true`, which is not a duration in any reading.
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            return False, "duration_seconds must be a number"
        # NaN and infinity are floats and pass every comparison test: `nan < 0`
        # is False, so the negative check waved them through. A deploy that took
        # NaN seconds corrupts any average computed over the column, and JSON has
        # no way to represent either.
        if math.isnan(duration) or math.isinf(duration):
            return False, "duration_seconds must be a finite number"
        if duration < 0:
            return False, "duration_seconds cannot be negative"

    if "error_message" in data and data["error_message"] is not None:
        if not isinstance(data["error_message"], str):
            return False, "error_message must be a string"

    return True, None
