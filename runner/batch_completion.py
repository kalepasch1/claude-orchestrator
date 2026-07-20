#!/usr/bin/env python3
"""Publish batch progress and detect decomposed work that is not executing.

The output is compact JSON so the admin dashboard, cron logs, and incident tools
all consume the same completion view. It intentionally performs no model work.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
from execution_assurance import dispatch_sla_breaches


def _count_by(rows, key):
    counts = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def snapshot(prefix="", batch="", limit=1000):
    task_params = {
        "select": "id,slug,state,kind,deps,note,created_at,updated_at,project_id",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    if prefix:
        task_params["slug"] = f"like.{prefix}*"
    batch_row = None
    if batch:
        rows = db.select("task_batches", {"select": "id,slug,title", "slug": f"eq.{batch}", "limit": "1"}) or []
        if not rows:
            raise ValueError(f"unknown batch: {batch}")
        batch_row = rows[0]
        task_params["batch_id"] = f"eq.{batch_row['id']}"
    tasks = db.select("tasks", task_params) or []
    task_ids = [str(task["id"]) for task in tasks if task.get("id")]
    runs = []
    if task_ids:
        runs = db.select("runs", {
            "select": "task_id,created_at",
            "task_id": f"in.({','.join(task_ids)})",
            "limit": str(limit),
        }) or []
    alerts = db.select("runner_alerts", {
        "select": "id,kind,resolved,created_at",
        "kind": "eq.runner_down",
        "resolved": "eq.false",
        "order": "created_at.desc",
        "limit": "100",
    }) or []
    breaches = dispatch_sla_breaches(tasks, runs)
    return {
        "prefix": prefix or "all",
        "batch": batch_row["slug"] if batch_row else None,
        "total": len(tasks),
        "states": _count_by(tasks, "state"),
        "kinds": _count_by(tasks, "kind"),
        "linked_runs": len(runs),
        "decomposed_without_run": [task["slug"] for task in breaches],
        "open_runner_down_alerts": len(alerts),
    }


def _already_alerted(prefix):
    try:
        rows = db.select("runner_alerts", {
            "select": "id",
            "kind": "eq.decomposed_without_run",
            "detail": f"ilike.*prefix={prefix or 'all'}*",
            "resolved": "eq.false",
            "limit": "1",
        }) or []
        return bool(rows)
    except Exception:
        return False


def emit_sla_alerts(summary):
    slugs = summary["decomposed_without_run"]
    prefix = summary["batch"] or summary["prefix"]
    if not slugs or _already_alerted(prefix):
        return 0
    try:
        db.insert("runner_alerts", {
            "kind": "decomposed_without_run",
            "detail": f"prefix={prefix} count={len(slugs)} slugs={','.join(slugs[:20])} exceeded decomposed-to-run SLA",
            "resolved": False,
        })
        return 1
    except Exception as exc:
        print(f"batch-completion: alert write failed: {exc}", file=sys.stderr)
        return 0


def reconcile_sla_alert(summary):
    """Resolve cleared SLA alerts; escalate one still-open alert after a second threshold."""
    prefix = summary["batch"] or summary["prefix"]
    rows = db.select("runner_alerts", {
        "select": "id,detail,created_at,resolved",
        "kind": "eq.decomposed_without_run",
        "detail": f"ilike.*prefix={prefix}*",
        "resolved": "eq.false",
        "order": "created_at.asc",
        "limit": "10",
    }) or []
    if not summary["decomposed_without_run"]:
        for row in rows:
            db.update("runner_alerts", {"id": row["id"]}, {"resolved": True})
        return {"resolved": len(rows), "escalated": 0}
    if not rows:
        return {"resolved": 0, "escalated": 0}
    threshold = int(os.environ.get("ORCH_DECOMPOSED_ESCALATION_MIN", "30"))
    created = rows[0].get("created_at")
    try:
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds() / 60
    except Exception:
        return {"resolved": 0, "escalated": 0}
    if age < threshold:
        return {"resolved": 0, "escalated": 0}
    existing = db.select("runner_alerts", {
        "select": "id", "kind": "eq.decomposed_without_run_escalated",
        "detail": f"ilike.*prefix={prefix}*", "resolved": "eq.false", "limit": "1",
    }) or []
    if existing:
        return {"resolved": 0, "escalated": 0}
    db.insert("runner_alerts", {
        "kind": "decomposed_without_run_escalated",
        "detail": f"prefix={prefix} remained above the decomposed-to-run SLA for {int(age)} minutes",
        "resolved": False,
    })
    return {"resolved": 0, "escalated": 1}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default=os.environ.get("ORCH_BATCH_PREFIX", ""))
    parser.add_argument("--batch", default=os.environ.get("ORCH_BATCH_SLUG", ""))
    parser.add_argument("--no-alert", action="store_true", help="report only; do not open SLA alerts")
    args = parser.parse_args()
    summary = snapshot(args.prefix, args.batch)
    if not args.no_alert:
        summary["alerts_emitted"] = emit_sla_alerts(summary)
        summary.update({f"alerts_{key}": value for key, value in reconcile_sla_alert(summary).items()})
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
