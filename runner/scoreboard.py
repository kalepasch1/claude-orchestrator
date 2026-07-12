#!/usr/bin/env python3
"""Fleet scoreboard heartbeat.

Writes the small set of numbers that matter for drain mode: queue mix, merge
rate, first-pass rate, spend, token use, and paused minutes. This is read-only
except for a controls heartbeat (and an optional table insert if present).
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
from scoreboard_data import collect_all

WINDOW_H = int(os.environ.get("ORCH_SCOREBOARD_WINDOW_H", "24"))
CONTROL_KEY = "fleet_scoreboard"


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
    data = collect_all()
    outcomes = data["outcomes"]
    return {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "window_h": WINDOW_H,
        "queue": data["queue"],
        "paused_minutes_today": data["paused_minutes"],
        "overall": _outcome_metrics(outcomes),
        "by_model": _by_model(outcomes),
        "by_project": _by_project(outcomes),
    }


def run():
    payload = compute()
    try:
        db.insert("controls", {"key": CONTROL_KEY, "value": json.dumps(payload, default=str),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass
    try:
        db.insert("scoreboard", payload)
    except Exception:
        pass
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
