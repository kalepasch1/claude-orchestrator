#!/usr/bin/env python3
"""
rca_trends.py — track root cause trends over time.

Records RCA snapshots and detects whether failure categories are
improving, worsening, or stable. Feeds into operator dashboards
and alerts when a category spikes.

Env vars:
    ORCH_RCA_TRENDS_ENABLED   "true" to enable (default "true")
    ORCH_RCA_SPIKE_THRESHOLD  % increase to flag as spike (default 50)
    ORCH_RCA_HISTORY_FILE     path to trends history (auto-detected)
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_RCA_TRENDS_ENABLED", "true").lower() in ("1", "true", "yes")
SPIKE_THRESHOLD = float(os.environ.get("ORCH_RCA_SPIKE_THRESHOLD", "50"))
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
HISTORY_FILE = os.environ.get("ORCH_RCA_HISTORY_FILE",
                              os.path.join(HOME, "rca_trends.json"))


def _load_history():
    """Load trend history from disk. Returns list of snapshots."""
    try:
        with open(HISTORY_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_history(history):
    """Save trend history to disk."""
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        # Keep last 100 snapshots
        trimmed = history[-100:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(trimmed, f, indent=2)
    except Exception:
        pass


def record_snapshot(clusters):
    """Record current RCA cluster counts as a trend snapshot."""
    if not ENABLED or not clusters:
        return
    snapshot = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "categories": {c["root_cause"]: c["count"] for c in clusters},
    }
    history = _load_history()
    history.append(snapshot)
    _save_history(history)
    return snapshot


def detect_spikes(clusters):
    """Compare current clusters against recent history to detect spikes.

    Returns list of {'category', 'current', 'previous_avg', 'change_pct', 'status'}.
    """
    if not ENABLED:
        return []

    history = _load_history()
    if len(history) < 2:
        return []

    # Average over last 5 snapshots
    recent = history[-5:]
    avg_counts = {}
    for snap in recent:
        for cat, count in snap.get("categories", {}).items():
            avg_counts.setdefault(cat, []).append(count)
    averages = {cat: sum(vals) / len(vals) for cat, vals in avg_counts.items()}

    current = {c["root_cause"]: c["count"] for c in clusters}
    results = []
    for cat, cur_count in current.items():
        prev_avg = averages.get(cat, 0)
        if prev_avg > 0:
            change_pct = ((cur_count - prev_avg) / prev_avg) * 100
        else:
            change_pct = 100.0 if cur_count > 0 else 0.0

        if change_pct >= SPIKE_THRESHOLD:
            status = "spike"
        elif change_pct <= -SPIKE_THRESHOLD:
            status = "improving"
        else:
            status = "stable"

        results.append({
            "category": cat,
            "current": cur_count,
            "previous_avg": round(prev_avg, 1),
            "change_pct": round(change_pct, 1),
            "status": status,
        })

    results.sort(key=lambda x: -abs(x["change_pct"]))
    return results


def run():
    """CLI entry point — analyze trends and record snapshot."""
    try:
        import rca_engine
        clusters = rca_engine.analyze()
    except Exception as e:
        print(f"rca_trends: failed: {e}")
        return {}

    record_snapshot(clusters)
    spikes = detect_spikes(clusters)
    spike_list = [s for s in spikes if s["status"] == "spike"]
    improving = [s for s in spikes if s["status"] == "improving"]
    print(f"rca_trends: {len(spike_list)} spike(s), {len(improving)} improving")
    for s in spike_list:
        print(f"  SPIKE: {s['category']} {s['current']} (was {s['previous_avg']}, +{s['change_pct']}%)")
    return {"spikes": spike_list, "improving": improving, "all": spikes}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
