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
from scoreboard_metrics import compute_metrics

WINDOW_H = int(os.environ.get("ORCH_SCOREBOARD_WINDOW_H", "24"))
CONTROL_KEY = "fleet_scoreboard"


def compute():
    data = collect_all()
    metrics = compute_metrics(data["outcomes"])
    return {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "window_h": WINDOW_H,
        "queue": data["queue"],
        "paused_minutes_today": data["paused_minutes"],
        **metrics,
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
