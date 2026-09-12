"""deploy_kpi_surface.py — Read deploy-KPI rows and compute dashboard summaries.

Reads from ``coordination_tasks`` where ``task_type = 'deploy_kpi'``.  Each
row's ``payload`` is a JSON KPI record: deploy_id, timestamp, status,
duration_seconds, error_message.

Fail-soft throughout: an unreachable or empty table renders an empty surface,
never raises.
"""
from __future__ import annotations

import json
import logging
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_HOURS = 24


@dataclass
class DeployKPISummary:
    """Dashboard-ready summary of deploy KPI rows."""
    window_hours: int = DEFAULT_WINDOW_HOURS
    total_deploys: int = 0
    succeeded: int = 0
    failed: int = 0
    success_rate: Optional[float] = None
    median_duration_seconds: Optional[float] = None
    recent_failures: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_kpi_rows(rows: list[dict]) -> list[dict]:
    """Extract and parse payload JSON from coordination_tasks rows."""
    records = []
    for row in rows:
        payload = row.get("payload")
        if not payload:
            continue
        try:
            rec = json.loads(payload) if isinstance(payload, str) else payload
            if isinstance(rec, dict):
                records.append(rec)
        except (json.JSONDecodeError, TypeError):
            logger.debug("deploy_kpi_surface: skipping malformed payload: %s",
                         str(payload)[:120])
    return records


def _filter_by_window(records: list[dict], window_hours: int) -> list[dict]:
    """Keep only records whose timestamp falls within the trailing window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    filtered = []
    for rec in records:
        ts_str = rec.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                filtered.append(rec)
        except (ValueError, TypeError, AttributeError):
            # No valid timestamp — include so it counts in totals
            filtered.append(rec)
    return filtered


def summarize(records: list[dict], window_hours: int = DEFAULT_WINDOW_HOURS) -> DeployKPISummary:
    """Compute the dashboard summary from a list of parsed KPI records.

    Pure-logic core separated from DB access so tests can call it with
    seeded data directly.
    """
    windowed = _filter_by_window(records, window_hours)

    total = len(windowed)
    succeeded = sum(1 for r in windowed
                    if str(r.get("status", "")).lower() == "succeeded")
    failed = total - succeeded

    durations = [
        r["duration_seconds"]
        for r in windowed
        if r.get("duration_seconds") is not None
        and isinstance(r.get("duration_seconds"), (int, float))
        and r["duration_seconds"] >= 0
    ]
    median_dur = statistics.median(durations) if durations else None

    # Recent failures: most recent first, capped at 10
    failures = [
        r for r in windowed
        if str(r.get("status", "")).lower() != "succeeded"
    ]

    def _ts_sort_key(r):
        try:
            return datetime.fromisoformat(
                r.get("timestamp", "").replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            return datetime.min.replace(tzinfo=timezone.utc)

    failures.sort(key=_ts_sort_key, reverse=True)
    recent_failures = [
        {
            "deploy_id": f.get("deploy_id", ""),
            "timestamp": f.get("timestamp", ""),
            "error_message": f.get("error_message", ""),
            "status": f.get("status", ""),
        }
        for f in failures[:10]
    ]

    return DeployKPISummary(
        window_hours=window_hours,
        total_deploys=total,
        succeeded=succeeded,
        failed=failed,
        success_rate=round(succeeded / total, 4) if total > 0 else None,
        median_duration_seconds=(round(median_dur, 2)
                                 if median_dur is not None else None),
        recent_failures=recent_failures,
    )


def read_deploy_kpi_summary(
    window_hours: int = DEFAULT_WINDOW_HOURS,
    db_module=None,
) -> DeployKPISummary:
    """Read deploy-KPI rows from the DB and return a dashboard summary.

    Fail-soft: returns an empty summary on any error.
    """
    if db_module is None:
        try:
            import db as db_module
        except ImportError:
            try:
                from runner import db as db_module
            except ImportError:
                logger.warning("deploy_kpi_surface: no db module available")
                return DeployKPISummary(window_hours=window_hours)

    try:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=window_hours)).isoformat()
        rows = db_module.select("coordination_tasks", {
            "task_type": "eq.deploy_kpi",
            "created_at": f"gte.{cutoff}",
            "order": "created_at.desc",
            "limit": "1000",
        }) or []
    except Exception as e:
        logger.warning("deploy_kpi_surface: DB read failed: %s: %s",
                       type(e).__name__, e)
        return DeployKPISummary(window_hours=window_hours)

    records = _parse_kpi_rows(rows)
    return summarize(records, window_hours)
