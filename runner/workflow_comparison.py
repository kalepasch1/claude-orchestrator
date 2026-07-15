#!/usr/bin/env python3
"""Comparable Cowork vs orchestrator-native delivery telemetry.

Outcome rows are classified by the executor that actually emitted them, while
task state is classified by the claiming account.  This avoids treating a
Claude model invoked by the native runner as Cowork work.  Exact release links
are applied when available; integrations remain a leading indicator, never a
deployment substitute.
"""
import collections
import datetime
import json
import os

import db


WINDOW_H = float(os.environ.get("WORKFLOW_COMPARISON_HOURS", "2"))


def workflow_for_outcome(row):
    model = str(row.get("model") or "").lower()
    return "cowork" if model.startswith("cowork") else "orchestrator_native"


def _rate(value, total):
    return round(value / total, 3) if total else 0.0


def summarize_outcomes(rows, hours):
    buckets = collections.defaultdict(lambda: {
        "attempts": 0, "unique_tasks": set(), "tests_passed": 0,
        "integrated": 0, "deployed": 0, "wall_ms": 0.0, "usd": 0.0,
    })
    for row in rows or []:
        bucket = buckets[workflow_for_outcome(row)]
        bucket["attempts"] += 1
        bucket["unique_tasks"].add(row.get("task_id") or
                                   (row.get("project"), row.get("slug")))
        bucket["tests_passed"] += int(bool(row.get("tests_passed")))
        bucket["integrated"] += int(bool(row.get("integrated")))
        bucket["deployed"] += int(bool(row.get("deployed")))
        bucket["wall_ms"] += float(row.get("wall_ms") or 0)
        bucket["usd"] += float(row.get("usd") or 0)

    result = {}
    for name in ("cowork", "orchestrator_native"):
        raw = buckets[name]
        n = raw["attempts"]
        result[name] = {
            "attempts": n,
            "unique_tasks": len(raw["unique_tasks"]),
            "tests_passed": raw["tests_passed"],
            "pass_rate": _rate(raw["tests_passed"], n),
            "verified_per_hour": round(raw["tests_passed"] / max(hours, 0.01), 3),
            "integrated": raw["integrated"],
            "integration_rate": _rate(raw["integrated"], n),
            "integrated_per_hour": round(raw["integrated"] / max(hours, 0.01), 3),
            "deployed": raw["deployed"],
            "deployment_rate": _rate(raw["deployed"], n),
            "deployed_per_hour": round(raw["deployed"] / max(hours, 0.01), 3),
            "avg_wall_seconds": round(raw["wall_ms"] / max(n, 1) / 1000, 1),
            "usd": round(raw["usd"], 4),
        }
    return result


def _outcomes(since):
    common = {"created_at": f"gte.{since}", "order": "created_at.desc", "limit": "5000"}
    try:
        rows = db.select("outcomes", dict(common, select=(
            "id,task_id,model,project,kind,slug,integrated,tests_passed,usd,"
            "wall_ms,attempts,created_at"))) or []
    except Exception:
        rows = db.select("outcomes", dict(common, select=(
            "model,project,kind,slug,integrated,tests_passed,usd,wall_ms,"
            "attempts,created_at"))) or []
    try:
        import release_attribution
        rows = release_attribution.apply(rows, authoritative=True)
    except Exception:
        pass
    return rows


def _task_state(since):
    rows = db.select("tasks", {
        "select": "id,state,account,updated_at", "updated_at": f"gte.{since}",
        "order": "updated_at.desc", "limit": "5000",
    }) or []
    out = {"cowork": collections.Counter(), "orchestrator_native": collections.Counter()}
    for row in rows:
        lane = "cowork" if str(row.get("account") or "").startswith("cowork-") else "orchestrator_native"
        out[lane][str(row.get("state") or "UNKNOWN")] += 1
    return {k: dict(v) for k, v in out.items()}


def run(hours=WINDOW_H):
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(hours=hours)
    since = start.isoformat()
    outcomes = summarize_outcomes(_outcomes(since), hours)
    payload = {
        "window_start": since, "window_end": end.isoformat(), "hours": hours,
        **outcomes, "task_state_transitions": _task_state(since),
    }
    native = outcomes["orchestrator_native"]
    cowork = outcomes["cowork"]
    payload["comparison"] = {
        "native_to_cowork_verified_throughput": (
            round(native["verified_per_hour"] / cowork["verified_per_hour"], 3)
            if cowork["verified_per_hour"] else None),
        "native_to_cowork_integrated_throughput": (
            round(native["integrated_per_hour"] / cowork["integrated_per_hour"], 3)
            if cowork["integrated_per_hour"] else None),
        "winner_by_deployed_value": (
            "orchestrator_native" if native["deployed"] > cowork["deployed"] else
            "cowork" if cowork["deployed"] > native["deployed"] else "insufficient_or_tied"),
    }
    payload["coverage"] = {
        "comparable_quality": bool(native["attempts"] and cowork["attempts"]),
        "warning": (None if native["attempts"] and cowork["attempts"] else
                    "Both workflows need outcome evidence in the same window for a fair ratio."),
    }
    print(json.dumps(payload, indent=2, default=str))
    return payload


if __name__ == "__main__":
    run()
