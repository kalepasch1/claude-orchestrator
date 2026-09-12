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


def _why_empty():
    """Why did router_stats return nothing? Answered as data, not as silence.

    router_stats scores a rolling window of `outcomes`. Empty therefore means one
    of three quite different things, and a reader must be able to tell them apart:
    the fleet is idle (paused, or nothing queued), the window is simply too short
    for a slow period, or the outcomes feed itself has stopped. Returns a dict —
    never raises, because a diagnostic that can take down the writer it explains
    is worse than no diagnostic.
    """
    detail = {"window_h": getattr(_router_stats_module(), "WINDOW_H", None)}
    try:
        import db
        rows = db.select("outcomes", {"select": "created_at",
                                      "order": "created_at.desc",
                                      "limit": "1"}) or []
    except Exception as exc:
        detail["cause"] = "outcomes_unreadable"
        detail["error"] = str(exc)[:200]
        return detail

    if not rows:
        detail["cause"] = "outcomes_table_empty"
        return detail

    newest = rows[0].get("created_at")
    detail["newest_outcome_at"] = newest
    detail["cause"] = "no_outcomes_in_window"
    detail["newest_outcome_age_h"] = _age_hours(newest)
    return detail


def _age_hours(timestamp):
    """Hours since an ISO timestamp, or None if it cannot be parsed."""
    try:
        import datetime
        then = datetime.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return round((now - then).total_seconds() / 3600.0, 1)
    except Exception:
        return None


def _router_stats_module():
    try:
        import router_stats
        return router_stats
    except Exception:
        return None


def _rebuild_routes():
    """(table, error). Never raises.

    persist_snapshot() used to `return None` when the rebuild failed, so a dead
    collector wrote NOTHING and the file showed a clean gap indistinguishable
    from an idle fleet. An unwritten failure is an unnoticed one — hand the error
    back so it can be recorded instead.
    """
    try:
        import router_stats
        return router_stats._rebuild(), None
    except Exception as exc:
        log.warning("scoreboard: router_stats._rebuild failed: %s", exc)
        return {}, str(exc)[:200]


def persist_snapshot():
    """Take a router_stats snapshot and append it to the scoreboard file."""
    table, rebuild_error = _rebuild_routes()

    snapshot = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "epoch": time.time(),
        "routes": {},
    }

    # An empty snapshot used to be written bare, as {"routes": {}}. Between
    # 2026-08-22 and 2026-08-30 that produced 634 consecutive hollow records —
    # and nothing in them said whether the fleet had simply done no work or the
    # collector itself had died. Reading the file back, the two are identical,
    # which is the worst property a diagnostic can have. Say which it is.
    if not table:
        snapshot["empty_reason"] = (
            {"cause": "router_stats_unavailable", "error": rebuild_error}
            if rebuild_error else _why_empty())

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

    try:
        # _ensure_dir() used to run outside this guard, so an unwritable or
        # non-directory _SCOREBOARD_DIR raised straight out of persist_snapshot()
        # and took run() — a scheduled fleet job — down with it. Persisting is
        # best effort; the snapshot is still returned to the caller.
        _ensure_dir()
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
