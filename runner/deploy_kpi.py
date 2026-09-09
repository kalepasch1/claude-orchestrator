import json
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
        """Persist the KPI row, and report honestly whether it landed.

        This used to log at DEBUG and `return True`. Nothing was written
        anywhere, and every caller that did not pass its own `write_func` was
        told the KPI had been recorded — so a deploy-KPI dashboard built on this
        would have shown an empty table while the writer reported success on
        every deploy. A write path that discards its input must not return the
        value that means "stored".

        Persistence goes to `coordination_tasks`, the fleet's KV table, under
        task_type `deploy_kpi`; that is where the other cross-cutting records in
        this repo live and it needs no migration.

        Fail-soft in the sense that matters here: a KPI write must never take
        down a deploy, so every failure is swallowed and reported as False. The
        retry wrapper above already treats False as "try again", and after
        exhaustion logs and continues.
        """
        try:
            import db  # runner-local; imported lazily so importing this
                       # module never requires a reachable database
        except Exception:
            try:
                from runner import db  # package-relative fallback
            except Exception:
                logger.warning("KPI write: no persistence backend available")
                return False

        try:
            db.insert("coordination_tasks", {
                "task_type": "deploy_kpi",
                "payload": json.dumps(record)[:8000],
            }, upsert=False)
            return True
        except Exception as e:
            logger.warning(
                f"KPI write to coordination_tasks failed: {type(e).__name__}: {e}")
            return False

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
