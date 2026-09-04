import logging
import time
from typing import Optional, Callable
from runner.contracts import validate_kpi_record, KPIRecord

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1
TIMEOUT_SECONDS = 2


class KPIWriter:
    def __init__(self, write_func: Optional[Callable] = None):
        self.write_func = write_func or self._default_write

    def _default_write(self, record: dict) -> bool:
        logger.debug(f"Default KPI write: {record}")
        return True

    def write_kpi(self, record: dict) -> bool:
        is_valid, error = validate_kpi_record(record)
        if not is_valid:
            logger.warning(f"KPI validation failed: {error}")
            return False

        return self._write_with_retry(record)

    def _write_with_retry(self, record: dict) -> bool:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = self._execute_write(record)
                if result:
                    return True
                logger.warning(f"KPI write attempt {attempt}/{MAX_RETRIES} returned False")
            except Exception as e:
                logger.warning(
                    f"KPI write attempt {attempt}/{MAX_RETRIES} failed: {type(e).__name__}: {e}"
                )

            if attempt < MAX_RETRIES:
                backoff = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                time.sleep(backoff)

        logger.warning(f"KPI write failed after {MAX_RETRIES} attempts, continuing deployment")
        return False

    def _execute_write(self, record: dict) -> bool:
        try:
            return self.write_func(record)
        except Exception as e:
            raise


def write_deploy_kpi(
    deploy_id: str,
    timestamp: str,
    status: str,
    duration_seconds: Optional[float] = None,
    error_message: Optional[str] = None,
    write_func: Optional[Callable] = None,
) -> bool:
    record = {
        "deploy_id": deploy_id,
        "timestamp": timestamp,
        "status": status,
        "duration_seconds": duration_seconds,
        "error_message": error_message,
    }

    writer = KPIWriter(write_func)
    return writer.write_kpi(record)
