"""
scoreboard.py — persist routing scores and serve a dashboard view.

Reads router_stats periodically, writes snapshots to a local JSONL file,
and provides a summary view for the web console.
"""
import os, sys, json, time, logging, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)

_SCOREBOARD_DIR = os.environ.get("ORCH_SCOREBOARD_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".runtime"))
_SCOREBOARD_FILE = os.path.join(_SCOREBOARD_DIR, "scoreboard.jsonl")
_SNAPSHOT_INTERVAL = int(os.environ.get("ORCH_SCOREBOARD_INTERVAL_S", "300"))


def _ensure_dir():
    os.makedirs(_SCOREBOARD_DIR, exist_ok=True)


def persist_snapshot():
    """Take a router_stats snapshot and append it to the scoreboard file."""
    try:
        import router_stats
        table = router_stats._rebuild()
    except Exception as e:
        log.debug("scoreboard: router_stats._rebuild failed: %s", e)
        return None

    snapshot = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "epoch": time.time(),
        "routes": {},
    }

    for kind, rows in table.items():
        snapshot["routes"][kind] = [
            {
                "coder": r["coder"],
                "score": r["score"],
                "rate": r.get("rate", 0),
                "deployed_rate": r.get("deployed_rate", 0),
                "n": r.get("n", 0),
                "usd_per_merge": r.get("usd_per_merge", 0),
                "objective": r.get("objective", "unknown"),
            }
            for r in rows[:5]  # top 5 per kind
        ]

    _ensure_dir()
    try:
        with open(_SCOREBOARD_FILE, "a") as f:
            f.write(json.dumps(snapshot, default=str) + "\n")
        log.info("scoreboard: persisted snapshot with %d route kinds", len(snapshot["routes"]))
    except Exception as e:
        log.warning("scoreboard: write failed: %s", e)

    return snapshot


def read_history(max_entries=50):
    """Read the most recent scoreboard snapshots."""
    if not os.path.exists(_SCOREBOARD_FILE):
        return []

    entries = []
    try:
        with open(_SCOREBOARD_FILE) as f:
            lines = f.readlines()
        for line in lines[-max_entries:]:
            try:
                entries.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    except Exception:
        pass

    return entries


def dashboard_summary():
    """Generate a dashboard summary from the latest snapshot."""
    history = read_history(max_entries=1)
    if not history:
        return {"status": "no data", "routes": {}}

    latest = history[-1]
    summary = {
        "timestamp": latest.get("timestamp"),
        "route_count": sum(len(v) for v in latest.get("routes", {}).values()),
        "top_coders": {},
    }

    for kind, rows in latest.get("routes", {}).items():
        if rows:
            top = rows[0]
            summary["top_coders"][kind] = {
                "coder": top["coder"],
                "score": top["score"],
                "rate": top.get("rate", 0),
                "n": top.get("n", 0),
            }

    return summary


def trend(kind, coder, max_entries=20):
    """Get score trend for a specific coder+kind over time."""
    history = read_history(max_entries=max_entries)
    points = []
    for entry in history:
        routes = entry.get("routes", {}).get(kind, [])
        for r in routes:
            if r["coder"] == coder:
                points.append({
                    "timestamp": entry.get("timestamp"),
                    "score": r["score"],
                    "rate": r.get("rate", 0),
                    "n": r.get("n", 0),
                })
                break
    return points


def run():
    """Periodic job entry point."""
    return persist_snapshot()


if __name__ == "__main__":
    snapshot = persist_snapshot()
    if snapshot:
        print(json.dumps(dashboard_summary(), indent=2, default=str))
    else:
        print("No router_stats data available")
