"""Data-collection layer for the fleet scoreboard.

Exports collect_all() -> dict with keys:
  - outcomes: list of outcome rows
  - queue: dict of queue counters
  - paused_minutes: float of paused minutes today
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW_H = int(os.environ.get("ORCH_SCOREBOARD_WINDOW_H", "24"))


def _iso_hours_ago(hours):
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat()


def _parse_ts(value):
    if not value:
        return None
    raw = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed
    except Exception:
        return None


def _select_outcomes():
    params = {
        "select": "project,model,coder,tests_passed,integrated,usd,wall_ms,input_tokens,output_tokens,review_failures,created_at",
        "created_at": f"gte.{_iso_hours_ago(WINDOW_H)}",
        "limit": "5000",
    }
    try:
        return db.select("outcomes", params) or []
    except Exception:
        fallback = {
            "select": "project,model,tests_passed,integrated,usd,wall_ms,created_at",
            "created_at": f"gte.{_iso_hours_ago(WINDOW_H)}",
            "limit": "5000",
        }
        return db.select("outcomes", fallback) or []


def _queue():
    try:
        import queue_counters
        return queue_counters.exact_counts(db_client=db)
    except Exception as e:
        try:
            import importlib.util
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue_counters.py")
            spec = importlib.util.spec_from_file_location("queue_counters_fallback", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.exact_counts(db_client=db)
        except Exception as e2:
            return {"error": f"{e}; fallback: {e2}"[:300], "states": {}}


def _paused_minutes_today():
    try:
        rows = db.select("controls", {"select": "paused,scope,updated_at,updated_by",
                                      "scope": "eq.global",
                                      "order": "updated_at.asc",
                                      "limit": "1000"}) or []
    except Exception:
        return None
    if not rows:
        return 0
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0.0
    paused_since = None
    for row in rows:
        ts = _parse_ts(row.get("updated_at"))
        if not ts:
            continue
        if row.get("paused"):
            paused_since = max(ts, start)
        elif paused_since:
            end = max(ts, start)
            if end > paused_since:
                total += (end - paused_since).total_seconds()
            paused_since = None
    if paused_since:
        total += (now - paused_since).total_seconds()
    return round(total / 60.0, 1)


def collect_all():
    """Return raw data-collection results as a dict.

    Keys:
      outcomes  – list of outcome row dicts
      queue     – dict of queue counters
      paused_minutes – float (minutes paused today) or None
    """
    return {
        "outcomes": _select_outcomes(),
        "queue": _queue(),
        "paused_minutes": _paused_minutes_today(),
    }
