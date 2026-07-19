#!/usr/bin/env python3
"""
fleet_health.py — Fleet health dashboard data for autoscaling decisions.

Aggregates executor heartbeats, queue pressure, and throughput into a
single health snapshot used by autoscale_signal and the dashboard.
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

def executor_status():
    """Return status of all known executors from heartbeats."""
    try:
        rows = db.select("fleet_config", {
            "select": "key,value",
            "key": "like.COWORK_EXECUTOR_%_LAST_RUN",
        }) or []
    except Exception:
        return []
    now = time.time()
    executors = []
    for r in rows:
        try:
            val = json.loads(r["value"]) if isinstance(r["value"], str) else r["value"]
            ts = val.get("ts", "")
            claimed = val.get("claimed", 0)
            done = val.get("done", 0)
            # Parse ISO timestamp
            import datetime
            dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age_s = now - dt.timestamp()
            status = "alive" if age_s < 600 else ("stale" if age_s < 3600 else "dead")
            executors.append({
                "name": r["key"],
                "status": status,
                "last_seen_seconds_ago": int(age_s),
                "claimed": claimed,
                "done": done,
            })
        except Exception:
            executors.append({"name": r["key"], "status": "unknown", "last_seen_seconds_ago": -1})
    return executors

def health_snapshot():
    """Full fleet health snapshot."""
    execs = executor_status()
    alive = sum(1 for e in execs if e["status"] == "alive")
    try:
        q = db.sql("SELECT state, count(*) as cnt FROM tasks GROUP BY state") or []
        states = {r["state"]: int(r["cnt"]) for r in q}
    except Exception:
        states = {}
    return {
        "executors": {"total": len(execs), "alive": alive, "stale": sum(1 for e in execs if e["status"] == "stale")},
        "queue": states,
        "queued": states.get("QUEUED", 0),
        "running": states.get("RUNNING", 0),
        "done_total": states.get("DONE", 0) + states.get("MERGED", 0),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

if __name__ == "__main__":
    print(json.dumps(health_snapshot(), indent=2, default=str))
