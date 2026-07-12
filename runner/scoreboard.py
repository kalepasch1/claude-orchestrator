#!/usr/bin/env python3
"""Fleet scoreboard heartbeat (hourly, 3600s interval).

Writes the small set of numbers that matter for drain mode: queue mix, merge
rate, first-pass rate, spend, token use, and paused minutes.

Persistence: writes a controls heartbeat row (upsert, always latest) AND
appends to the scoreboard table for historical data retained >= 30 days
(configurable via ORCH_SCOREBOARD_RETENTION_DAYS).
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW_H = int(os.environ.get("ORCH_SCOREBOARD_WINDOW_H", "24"))
CONTROL_KEY = "fleet_scoreboard"
RETENTION_DAYS = int(os.environ.get("ORCH_SCOREBOARD_RETENTION_DAYS", "30"))


def _iso_hours_ago(hours):
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat()


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


def _outcome_metrics(rows):
    attempts = len(rows)
    tests_passed = sum(1 for r in rows if r.get("tests_passed"))
    merged = sum(1 for r in rows if r.get("integrated"))
    usd = sum(float(r.get("usd") or 0) for r in rows)
    tokens = sum(int(r.get("input_tokens") or 0) + int(r.get("output_tokens") or 0) for r in rows)
    wall_ms = sum(int(r.get("wall_ms") or 0) for r in rows)
    review_failures = sum(int(r.get("review_failures") or 0) for r in rows)
    first_pass_rate = round(tests_passed / attempts, 4) if attempts else None
    merge_rate = round(merged / attempts, 4) if attempts else None
    return {
        "attempts": attempts,
        "tests_passed": tests_passed,
        "merged": merged,
        "first_pass_rate": first_pass_rate,
        "merge_rate": merge_rate,
        "usd": round(usd, 4),
        "usd_per_merge": round(usd / merged, 4) if merged else None,
        "tokens": tokens,
        "tokens_per_merge": round(tokens / merged, 1) if merged else None,
        "avg_wall_min": round((wall_ms / max(1, attempts)) / 60000, 2) if attempts else None,
        "review_failures": review_failures,
        "review_failures_per_merge": round(review_failures / merged, 3) if merged else None,
    }


def _by_model(rows):
    grouped = {}
    for row in rows:
        key = row.get("model") or row.get("coder") or "unknown"
        grouped.setdefault(str(key), []).append(row)
    return {key: _outcome_metrics(vals) for key, vals in grouped.items()}


def _by_project(rows):
    grouped = {}
    for row in rows:
        key = row.get("project") or "unknown"
        grouped.setdefault(str(key), []).append(row)
    return {key: _outcome_metrics(vals) for key, vals in grouped.items()}


def compute():
    outcomes = _select_outcomes()
    return {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "window_h": WINDOW_H,
        "queue": _queue(),
        "paused_minutes_today": _paused_minutes_today(),
        "overall": _outcome_metrics(outcomes),
        "by_model": _by_model(outcomes),
        "by_project": _by_project(outcomes),
    }


def run():
    payload = compute()
    # Controls heartbeat: upsert single row so dashboard always has latest snapshot
    try:
        db.insert("controls", {"key": CONTROL_KEY, "value": json.dumps(payload, default=str),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass
    # Append to scoreboard table for historical persistence (>= RETENTION_DAYS)
    try:
        db.insert("scoreboard", payload)
    except Exception:
        pass
    # Note: rows older than RETENTION_DAYS should be pruned externally
    # (e.g. Supabase cron or queue_janitor) to bound table growth.
    overall = payload["overall"]
    queue = payload.get("queue") or {}
    print(
        "scoreboard: "
        f"queued={queue.get('queued')} running={queue.get('running')} "
        f"merged={overall.get('merged')}/{overall.get('attempts')} "
        f"merge_rate={overall.get('merge_rate')} "
        f"usd_per_merge={overall.get('usd_per_merge')} "
        f"paused_min_today={payload.get('paused_minutes_today')}"
    )
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
