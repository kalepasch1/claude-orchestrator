#!/usr/bin/env python3
"""
anomaly.py - the self-loop watching its OWN vitals. Compares the recent window of
outcomes against the trailing baseline for failure-rate, cost-per-task, and rate-limit
frequency. If any spikes beyond threshold, files an alert approval card so you catch
regressions early instead of after a big bill or a stalled fleet.

Run on a schedule (e.g. hourly). Stateless; reads `outcomes` from Supabase.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

RECENT = int(os.environ.get("ANOMALY_RECENT", "30"))     # last N tasks
SPIKE = float(os.environ.get("ANOMALY_SPIKE", "1.75"))   # x baseline to alert


def _rate(rows, pred):
    """Return the fraction of rows satisfying pred, or 0.0 if rows is empty."""
    return (sum(1 for r in rows if pred(r)) / len(rows)) if rows else 0.0


def check():
    """Compare recent task outcomes against a trailing baseline for anomaly detection.

    Returns dict with 'ok' (bool), 'alerts' (list of spike descriptions), and 'metrics'.
    Files an approval card for each detected anomaly so operators are notified early."""
    try:
        rows = db.select("outcomes", {"select": "*", "order": "created_at.desc", "limit": "300"}) or []
    except Exception as e:
        return {"ok": True, "note": f"telemetry unavailable ({e})"}
    if len(rows) < RECENT * 2:
        return {"ok": True, "note": "not enough data yet"}
    recent, base = rows[:RECENT], rows[RECENT:]
    metrics = {
        "fail_rate": (_rate(recent, lambda r: not r.get("tests_passed")),
                      _rate(base, lambda r: not r.get("tests_passed"))),
        "rate_limit_rate": (_rate(recent, lambda r: r.get("rate_limited")),
                            _rate(base, lambda r: r.get("rate_limited"))),
        "cost_per_task": (sum(float(r.get("usd") or 0) for r in recent) / len(recent),
                          sum(float(r.get("usd") or 0) for r in base) / max(1, len(base))),
    }
    alerts = []
    for name, (now, baseline) in metrics.items():
        if baseline > 0 and now > baseline * SPIKE:
            alerts.append(f"{name}: {now:.3f} vs baseline {baseline:.3f} ({now/baseline:.1f}x)")
    for a in alerts:
        db.insert("approvals", {"project": "ORCHESTRATOR", "kind": "self",
            "title": "Anomaly detected in orchestrator vitals",
            "why": a, "value": "Catch regressions before they cost time/money.",
            "risk": "Investigate; may indicate a bad self-change, a flaky model, or an outage.",
            "command": ""})
    return {"ok": not alerts, "alerts": alerts, "metrics": metrics}


if __name__ == "__main__":
    print(check())
