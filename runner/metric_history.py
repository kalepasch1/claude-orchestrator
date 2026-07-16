#!/usr/bin/env python3
"""
metric_history.py – Time-series metric history for the monitoring dashboard.

Records orchestrator metrics at regular intervals, stores them in a local
JSONL file, and provides trend analysis (moving averages, spike detection,
percentile calculations) for dashboard visualizations.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.
"""
import os, sys, json, datetime, threading, statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HISTORY_DIR = os.path.expanduser("~/.claude-orchestrator/metric-history")
RETENTION_DAYS = int(os.environ.get("ORCH_METRIC_RETENTION_DAYS", "30"))
SPIKE_THRESHOLD = float(os.environ.get("ORCH_SPIKE_THRESHOLD", "2.0"))  # std devs

_lock = threading.Lock()
_STATE = {
    "snapshots_recorded": 0,
    "last_snapshot": None,
}


def _ensure_dir():
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
    except OSError:
        pass


def _log_path(date=None):
    if date is None:
        date = datetime.date.today()
    return os.path.join(HISTORY_DIR, f"metrics-{date.isoformat()}.jsonl")


def record_snapshot(metrics):
    """
    Record a metrics snapshot to the time-series store.

    Args:
        metrics: dict of metric_name -> numeric value
    """
    _ensure_dir()
    now = datetime.datetime.utcnow().isoformat() + "Z"
    entry = {"timestamp": now, "metrics": metrics}

    try:
        with open(_log_path(), "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass

    with _lock:
        _STATE["snapshots_recorded"] += 1
        _STATE["last_snapshot"] = now

    return entry


def read_history(metric_name, hours=24):
    """
    Read time-series data for a specific metric.

    Returns list of {timestamp, value} sorted by time.
    """
    _ensure_dir()
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    points = []

    try:
        # Read today and yesterday's files at minimum
        dates_to_check = set()
        d = datetime.date.today()
        for _ in range(min(int(hours / 24) + 2, RETENTION_DAYS)):
            dates_to_check.add(d)
            d -= datetime.timedelta(days=1)

        for date in sorted(dates_to_check):
            path = _log_path(date)
            if not os.path.exists(path):
                continue
            try:
                with open(path) as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            ts = entry.get("timestamp", "")
                            val = entry.get("metrics", {}).get(metric_name)
                            if val is not None:
                                entry_time = datetime.datetime.fromisoformat(ts.rstrip("Z"))
                                if entry_time >= cutoff:
                                    points.append({"timestamp": ts, "value": float(val)})
                        except (json.JSONDecodeError, ValueError):
                            continue
            except OSError:
                continue
    except OSError:
        pass

    return sorted(points, key=lambda p: p["timestamp"])


def moving_average(metric_name, hours=24, window=5):
    """Compute moving average for a metric over a time window."""
    points = read_history(metric_name, hours)
    if len(points) < window:
        return points

    values = [p["value"] for p in points]
    ma_values = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        avg = sum(values[start:i + 1]) / (i - start + 1)
        ma_values.append({
            "timestamp": points[i]["timestamp"],
            "value": points[i]["value"],
            "moving_avg": round(avg, 3),
        })
    return ma_values


def detect_spikes(metric_name, hours=24):
    """
    Detect anomalous spikes in metric values.

    Returns list of spike events where value exceeds SPIKE_THRESHOLD
    standard deviations from the mean.
    """
    points = read_history(metric_name, hours)
    if len(points) < 5:
        return []

    values = [p["value"] for p in points]
    mean = statistics.mean(values)
    try:
        stdev = statistics.stdev(values)
    except statistics.StatisticsError:
        return []

    if stdev == 0:
        return []

    spikes = []
    for p in points:
        z_score = abs(p["value"] - mean) / stdev
        if z_score > SPIKE_THRESHOLD:
            spikes.append({
                "timestamp": p["timestamp"],
                "value": p["value"],
                "z_score": round(z_score, 2),
                "mean": round(mean, 3),
                "stdev": round(stdev, 3),
            })
    return spikes


def percentiles(metric_name, hours=24):
    """Compute percentile distribution for a metric."""
    points = read_history(metric_name, hours)
    if not points:
        return {}
    values = sorted(p["value"] for p in points)
    n = len(values)
    return {
        "count": n,
        "min": values[0],
        "p25": values[int(n * 0.25)] if n > 3 else values[0],
        "p50": values[int(n * 0.50)] if n > 1 else values[0],
        "p75": values[int(n * 0.75)] if n > 3 else values[-1],
        "p95": values[int(n * 0.95)] if n > 19 else values[-1],
        "max": values[-1],
        "mean": round(statistics.mean(values), 3),
    }


def cleanup_old():
    """Remove metric files older than retention period."""
    _ensure_dir()
    cutoff = datetime.date.today() - datetime.timedelta(days=RETENTION_DAYS)
    removed = 0
    try:
        for f in os.listdir(HISTORY_DIR):
            if not f.startswith("metrics-") or not f.endswith(".jsonl"):
                continue
            try:
                date_str = f.replace("metrics-", "").replace(".jsonl", "")
                file_date = datetime.date.fromisoformat(date_str)
                if file_date < cutoff:
                    os.remove(os.path.join(HISTORY_DIR, f))
                    removed += 1
            except (ValueError, OSError):
                continue
    except OSError:
        pass
    return removed


def stats():
    with _lock:
        return dict(_STATE)


def run():
    """Entry point: collect current metrics and record snapshot."""
    metrics = {}
    try:
        import db
        rows = db.sql("SELECT state, count(*)::int AS cnt FROM tasks GROUP BY state") or []
        for r in rows:
            metrics[f"tasks_{r['state'].lower()}"] = r["cnt"]
        metrics["tasks_total"] = sum(r["cnt"] for r in rows)
    except Exception:
        pass

    record_snapshot(metrics)
    cleanup_old()
    return {"recorded": True, "metrics": metrics}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
