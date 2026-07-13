#!/usr/bin/env python3
"""metaopt.py - Meta-optimization for orchestrator loop cadence tuning."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
_MIN_POLL = float(os.environ.get("METAOPT_MIN_POLL", "30"))
_MAX_POLL = float(os.environ.get("METAOPT_MAX_POLL", "300"))
_TARGET_Q = int(os.environ.get("METAOPT_TARGET_QUEUE", "10"))
def _queue_depth():
    return int((db.sql("SELECT count(*) as n FROM tasks WHERE state='QUEUED'") or [{"n":0}])[0].get("n",0))
def _throughput():
    return int((db.sql("SELECT count(*) as n FROM outcomes WHERE created_at > now()-interval '1 hour'") or [{"n":0}])[0].get("n",0))
def recommend_cadence():
    d, t = _queue_depth(), _throughput()
    if d > _TARGET_Q * 2: iv = _MIN_POLL
    elif d < _TARGET_Q // 2 and t < 5: iv = _MAX_POLL
    else: iv = max(_MIN_POLL, min(_MAX_POLL, _MAX_POLL / max(0.1, d / max(1, _TARGET_Q))))
    return {"poll_interval_sec": round(iv, 1), "queue_depth": d, "throughput_per_hour": t}
def apply():
    rec = recommend_cadence()
    db.sql("INSERT INTO fleet_config (key,value) VALUES ('METAOPT_CADENCE','%s'::jsonb) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value" % json.dumps(rec).replace("'","''"))
    print(f"metaopt: cadence={rec['poll_interval_sec']}s depth={rec['queue_depth']}")
    return rec
if __name__ == "__main__": apply()
