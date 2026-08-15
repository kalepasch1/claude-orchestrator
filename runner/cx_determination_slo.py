#!/usr/bin/env python3
"""
cx_determination_slo.py - LATENCY SLO for determinations: how long a subject waits before the
committee stack actually decides it.

Two sibling modules already watch adjacent failure modes and neither covers this one:
  - cx_contention_slo_alerts.py  -> quality SLO (domains whose consensus stays low)
  - cx_escalation_sla.py         -> post-escalation dwell time (a human is already the blocker)

Neither notices the case where determinations are simply slow to be issued in the first place:
subjects pile up, decisions land days after the work they were meant to gate, and nothing alerts
because each individual determination eventually happened. This module measures time-to-determine
from subject arrival to determination, computes p50/p95 and SLO compliance against a target, and
opens ONE inbox alert when compliance drops under the floor.

Compliance = share of determinations decided within ORCH_DETERMINATION_SLO_HOURS (default 24).
Alert fires when compliance < ORCH_DETERMINATION_SLO_FLOOR (default 0.8) over at least
MIN_SAMPLE determinations in the lookback window.

Read-only except the alert digest. No schema change. Does not edit committees.py.

Usage:
    python3 runner/cx_determination_slo.py [--days 7] [--json] [--no-alert]
"""
import datetime
import json
import os
import sys
from argparse import ArgumentParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Target: a determination should land within this many hours of the subject arriving.
SLO_HOURS = float(os.environ.get("ORCH_DETERMINATION_SLO_HOURS", "24") or 24)
# Alert when the share of determinations meeting the target falls below this.
SLO_FLOOR = float(os.environ.get("ORCH_DETERMINATION_SLO_FLOOR", "0.8") or 0.8)
# Never alert off a handful of samples — small windows are noise, not a trend.
MIN_SAMPLE = int(os.environ.get("ORCH_DETERMINATION_SLO_MIN_SAMPLE", "5") or 5)
LOOKBACK_DAYS = int(os.environ.get("ORCH_DETERMINATION_SLO_LOOKBACK_DAYS", "7") or 7)

# Where a subject's arrival timestamp lives, by subject_type. Determinations reference several
# different subject tables; each is read only for its created_at.
SUBJECT_TABLES = {
    "improvement_proposal": "improvement_proposals",
    "proposal": "improvement_proposals",
    "approval": "approvals",
    "shadow_approval": "approvals",
    "task": "tasks",
}


def _parse_ts(value):
    """ISO timestamp -> aware datetime, or None. Never raises on malformed input."""
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)
    try:
        dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def _hours_between(start, end):
    """Positive hour delta, or None when either endpoint is unusable or the pair is inverted."""
    a, b = _parse_ts(start), _parse_ts(end)
    if not a or not b:
        return None
    delta = (b - a).total_seconds() / 3600.0
    return None if delta < 0 else round(delta, 3)


def percentile(values, pct):
    """Nearest-rank percentile over a list of numbers. Returns None for an empty list."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return round(vals[0], 3)
    rank = max(1, min(len(vals), int(round(pct / 100.0 * len(vals) + 0.5))))
    return round(vals[rank - 1], 3)


def _cutoff(days):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=max(1, int(days)))).isoformat()


def recent_determinations(days=LOOKBACK_DAYS, limit=500):
    """Determinations created in the lookback window. Fail-soft: [] when the DB is unreachable."""
    try:
        return db.select("determinations", {
            "select": "id,subject_type,subject_id,title,created_at,materiality",
            "created_at": f"gte.{_cutoff(days)}",
            "order": "created_at.desc",
            "limit": str(limit),
        }) or []
    except Exception as e:
        print(f"cx_determination_slo: determinations read failed ({e}); fail-soft empty")
        return []


def _subject_arrivals(dets):
    """{subject_id: created_at} for every subject we can resolve, one query per subject table."""
    wanted = {}
    for d in dets:
        table = SUBJECT_TABLES.get((d.get("subject_type") or "").strip().lower())
        if table and d.get("subject_id"):
            wanted.setdefault(table, set()).add(d["subject_id"])
    arrivals = {}
    for table, ids in wanted.items():
        try:
            rows = db.select(table, {
                "select": "id,created_at",
                "id": f"in.({','.join(str(i) for i in ids)})",
                "limit": str(len(ids) + 1),
            }) or []
        except Exception as e:
            print(f"cx_determination_slo: {table} read failed ({e}); fail-soft skip")
            continue
        for r in rows:
            if r.get("id") and r.get("created_at"):
                arrivals[r["id"]] = r["created_at"]
    return arrivals


def measure(dets, arrivals, slo_hours=SLO_HOURS):
    """Per-determination latency records. Determinations with no resolvable arrival are dropped."""
    out = []
    for d in dets:
        latency = _hours_between(arrivals.get(d.get("subject_id")), d.get("created_at"))
        if latency is None:
            continue
        out.append({
            "determination_id": d.get("id"),
            "subject_type": d.get("subject_type"),
            "subject_id": d.get("subject_id"),
            "title": (d.get("title") or "")[:160],
            "latency_hours": latency,
            "met_slo": latency <= slo_hours,
        })
    return out


def summarize(records, slo_hours=SLO_HOURS):
    """Roll latency records into an SLO report, overall and broken down by subject_type."""
    latencies = [r["latency_hours"] for r in records]
    met = sum(1 for r in records if r["met_slo"])
    report = {
        "slo_hours": slo_hours,
        "sample": len(records),
        "met": met,
        "breached": len(records) - met,
        "compliance": round(met / len(records), 3) if records else None,
        "p50_hours": percentile(latencies, 50),
        "p95_hours": percentile(latencies, 95),
        "by_subject_type": {},
        "worst": sorted(records, key=lambda r: -r["latency_hours"])[:5],
    }
    for r in records:
        st = r.get("subject_type") or "unknown"
        b = report["by_subject_type"].setdefault(st, {"sample": 0, "met": 0, "latencies": []})
        b["sample"] += 1
        b["met"] += 1 if r["met_slo"] else 0
        b["latencies"].append(r["latency_hours"])
    for st, b in report["by_subject_type"].items():
        b["compliance"] = round(b["met"] / b["sample"], 3) if b["sample"] else None
        b["p95_hours"] = percentile(b.pop("latencies"), 95)
    return report


def should_alert(report, floor=SLO_FLOOR, min_sample=MIN_SAMPLE):
    """Alert only on a real trend: enough samples AND compliance under the floor."""
    if not report or (report.get("sample") or 0) < min_sample:
        return False
    compliance = report.get("compliance")
    return compliance is not None and compliance < floor


def _alert(report, floor=SLO_FLOOR):
    """Open one inbox row describing the breach. Fail-soft; returns True when written."""
    worst = "\n".join(
        f"- {w['title'] or w['determination_id']}: {w['latency_hours']}h" for w in report.get("worst", [])
    )
    slow_types = ", ".join(
        f"{st} {b['compliance']:.0%}" for st, b in sorted(
            report.get("by_subject_type", {}).items(), key=lambda kv: kv[1].get("compliance") or 0
        ) if b.get("compliance") is not None
    )
    try:
        db.insert("inbox", {
            "kind": "determination_slo",
            "title": (f"Determination latency SLO breached: {report['compliance']:.0%} within "
                      f"{report['slo_hours']:g}h (floor {floor:.0%})"),
            "body": (f"Over the last window {report['met']}/{report['sample']} determinations landed "
                     f"inside the {report['slo_hours']:g}h target.\n"
                     f"p50 {report['p50_hours']}h, p95 {report['p95_hours']}h.\n"
                     f"By subject type: {slow_types or 'n/a'}\n\nSlowest:\n{worst}"),
            "status": "unread",
        })
    except Exception as e:
        print(f"cx_determination_slo: alert insert failed ({e}); fail-soft continue")
        return False
    return True


def run(days=LOOKBACK_DAYS, slo_hours=SLO_HOURS, floor=SLO_FLOOR, alert=True):
    """Measure determination latency over the window and alert on an SLO breach. Returns the report."""
    dets = recent_determinations(days)
    if not dets:
        print("cx_determination_slo: no determinations in window; nothing to measure")
        return {"sample": 0, "compliance": None, "slo_hours": slo_hours, "alerted": False}
    records = measure(dets, _subject_arrivals(dets), slo_hours)
    report = summarize(records, slo_hours)
    report["window_days"] = days
    report["alerted"] = bool(alert and should_alert(report, floor) and _alert(report, floor))
    print(f"cx_determination_slo: {report['sample']} determinations, "
          f"compliance {report['compliance']} vs floor {floor}, "
          f"p50 {report['p50_hours']}h p95 {report['p95_hours']}h"
          f"{' [ALERTED]' if report['alerted'] else ''}")
    return report


def main(argv=None):
    p = ArgumentParser(description="Determination latency SLO: time from subject arrival to decision.")
    p.add_argument("--days", type=int, default=LOOKBACK_DAYS, help="lookback window in days")
    p.add_argument("--slo-hours", type=float, default=SLO_HOURS, help="target hours to determination")
    p.add_argument("--floor", type=float, default=SLO_FLOOR, help="compliance floor before alerting")
    p.add_argument("--no-alert", action="store_true", help="measure only; write no inbox row")
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = p.parse_args(argv)
    report = run(days=args.days, slo_hours=args.slo_hours, floor=args.floor, alert=not args.no_alert)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
