#!/usr/bin/env python3
"""
anomaly.py - the self-loop watching its OWN vitals. Compares the recent window of
outcomes against the trailing baseline for failure-rate, cost-per-task, and rate-limit
frequency. If any spikes beyond threshold, files an alert approval card so you catch
regressions early instead of after a big bill or a stalled fleet.

Run on a schedule (e.g. hourly). Stateless; reads `outcomes` from Supabase.
"""
from __future__ import annotations
import os, sys
from typing import Any, Callable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

__all__ = ["check"]

RECENT = int(os.environ.get("ANOMALY_RECENT", "30"))     # last N tasks
SPIKE = float(os.environ.get("ANOMALY_SPIKE", "1.75"))   # x baseline to alert

#: Metrics measured as a fraction of the window (0.0-1.0). Only these can be
#: judged against an absolute floor, because only these have a unit that means
#: the same thing on every fleet: "share of recent tasks".
RATE_METRICS = ("fail_rate", "rate_limit_rate")

#: What counts as a spike when the baseline is EXACTLY zero.
#:
#: THE HEALTHIEST BASELINE DISABLED THE ALARM. The comparison is
#: `baseline > 0 and now > baseline * SPIKE`, and the `baseline > 0` guard is
#: needed — nothing is 1.75x of zero. But it also means a metric that goes from
#: 0% to 100% raises nothing at all, and 0% is what a healthy fleet's baseline
#: looks like. The worst possible regression, on the best possible fleet, was
#: the one case this watchdog could not see: the first 30 tasks after a bad
#: self-change failing outright read as "ok".
#:
#: A floor rather than "any nonzero value" because 1 failure in a 30-task window
#: is 0.033 and alerting on it would page for every blip on a perfect fleet.
ZERO_BASELINE_RATE = float(os.environ.get("ANOMALY_ZERO_BASELINE_RATE", "0.2"))


def _rate(rows: list[dict[str, Any]], pred: Callable[[dict[str, Any]], bool]) -> float:
    """Return fraction of rows matching pred (0.0 if empty)."""
    return (sum(1 for r in rows if pred(r)) / len(rows)) if rows else 0.0


def check() -> dict[str, Any]:
    try:
        rows = db.select("outcomes", {"select": "*", "order": "created_at.desc", "limit": "300"}) or []
    except Exception as e:
        return {"ok": True, "note": f"telemetry unavailable ({e})"}
    if len(rows) < RECENT * 2:
        return {"ok": True, "note": "not enough data yet"}
    recent, base = rows[:RECENT], rows[RECENT:]
    def _avg_duration(rows):
        durations = [float(r["duration_s"]) for r in rows if r.get("duration_s")]
        return sum(durations) / max(1, len(durations)) if durations else 0.0

    metrics = {
        "fail_rate": (_rate(recent, lambda r: not r.get("tests_passed")),
                      _rate(base, lambda r: not r.get("tests_passed"))),
        "rate_limit_rate": (_rate(recent, lambda r: r.get("rate_limited")),
                            _rate(base, lambda r: r.get("rate_limited"))),
        "cost_per_task": (sum(float(r.get("usd") or 0) for r in recent) / len(recent),
                          sum(float(r.get("usd") or 0) for r in base) / max(1, len(base))),
        "avg_duration_s": (_avg_duration(recent), _avg_duration(base)),
    }
    alerts = []
    for name, (now, baseline) in metrics.items():
        if baseline > 0:
            if now > baseline * SPIKE:
                alerts.append(f"{name}: {now:.3f} vs baseline {baseline:.3f} "
                              f"({now/baseline:.1f}x)")
        elif name in RATE_METRICS and now >= ZERO_BASELINE_RATE:
            # No ratio exists to report here, so say what actually happened
            # rather than printing "infx" or dividing by zero.
            alerts.append(f"{name}: {now:.3f} against a clean baseline of 0.000 "
                          f"— new failure mode, not a worsening one")
    for a in alerts:
        db.insert("approvals", {"project": "ORCHESTRATOR", "kind": "self",
            "title": "Anomaly detected in orchestrator vitals",
            "why": a, "value": "Catch regressions before they cost time/money.",
            "risk": "Investigate; may indicate a bad self-change, a flaky model, or an outage.",
            "command": ""})
    return {"ok": not alerts, "alerts": alerts, "metrics": metrics}


if __name__ == "__main__":
    print(check())
