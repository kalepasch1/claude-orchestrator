#!/usr/bin/env python3
"""Fleet scoreboard – persistence layer.

Assembles payload from collect_all + compute_metrics, upserts to controls,
appends to scoreboard table, prints summary.

NOTE: scoreboard rows are pruned by RETENTION_DAYS (default 90) via
scheduled DB maintenance; see fleet_config / db_maintenance for details.
"""
import datetime, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
from scoreboard_data import collect_all
from scoreboard_metrics import compute_metrics

WINDOW_H = int(os.environ.get("ORCH_SCOREBOARD_WINDOW_H", "24"))
CONTROL_KEY = "fleet_scoreboard"


def compute():
    data = collect_all()
    return {"generated_at": datetime.datetime.utcnow().isoformat(),
            "window_h": WINDOW_H, "queue": data["queue"],
            "paused_minutes_today": data["paused_minutes"],
            **compute_metrics(data["outcomes"])}


def run():
    payload = compute()
    for table, row in [("controls", {"key": CONTROL_KEY,
                                      "value": json.dumps(payload, default=str),
                                      "updated_at": "now()"}),
                       ("scoreboard", payload)]:
        try:
            db.insert(table, row, upsert=(table == "controls"))
        except Exception:
            pass
    o, q = payload["overall"], payload.get("queue") or {}
    print(f"scoreboard: queued={q.get('queued')} running={q.get('running')} "
          f"merged={o.get('merged')}/{o.get('attempts')} "
          f"merge_rate={o.get('merge_rate')} usd/merge={o.get('usd_per_merge')} "
          f"paused_min={payload.get('paused_minutes_today')}")
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
