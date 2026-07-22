#!/usr/bin/env python3
"""
telemetry_ingest.py - periodic (1h) per-app signal collection for ev_scheduler.

Pulls signals already available in the environment:
  - deploy_health states (from deploy_verify / deploy_watch)
  - Supabase ai_call_log volumes/costs where readable
  - Vercel deployment error rates (vercel CLI ls per linked project)
  - App-emitted usage counters (convention: apps push a metrics row to 'app_metrics' table)

Normalizes into ctx['app_signals'] = {project: {usage_trend, error_rate, cost_burn}}
consumed by ev_scheduler.score().

Convention for apps to push metrics:
  INSERT INTO app_metrics (project, metric, value, ts)
  VALUES ('myapp', 'active_users', 142, now());
  Supported metrics: active_users, signups, errors, api_calls, revenue_delta.
"""
import os, sys, json, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

INTERVAL_S = int(os.environ.get("TELEMETRY_INTERVAL_S", "3600"))
VERCEL_TIMEOUT = int(os.environ.get("TELEMETRY_VERCEL_TIMEOUT", "15"))
SIGNAL_WINDOW_H = int(os.environ.get("TELEMETRY_WINDOW_H", "24"))


def _fetch_deploy_health():
    """Pull deploy_health states from resource_events. Fail-soft: returns {} on error."""
    try:
        rows = db.select("resource_events", {
            "select": "project,payload",
            "kind": "eq.deploy_health",
            "order": "created_at.desc",
            "limit": "100",
        }) or []
        health = {}
        for r in rows:
            proj = r.get("project", "")
            if proj and proj not in health:
                payload = r.get("payload") or {}
                if isinstance(payload, str):
                    try: payload = json.loads(payload)
                    except Exception: payload = {}
                health[proj] = payload.get("status", "unknown")
        return health
    except Exception:
        return {}


def _fetch_app_metrics():
    """Pull app-emitted metrics from the app_metrics table. Fail-soft."""
    try:
        rows = db.select("app_metrics", {
            "select": "project,metric,value",
            "order": "ts.desc",
            "limit": "500",
        }) or []
        by_proj = {}
        for r in rows:
            proj = r.get("project", "")
            metric = r.get("metric", "")
            val = float(r.get("value", 0) or 0)
            if proj not in by_proj:
                by_proj[proj] = {}
            by_proj[proj][metric] = val
        return by_proj
    except Exception:
        return {}


def _fetch_ai_call_costs():
    """Pull per-project cost summaries from ai_call_log. Fail-soft."""
    try:
        rows = db.select("ai_call_log", {
            "select": "project,cost_usd",
            "order": "created_at.desc",
            "limit": "500",
        }) or []
        costs = {}
        for r in rows:
            proj = r.get("project", "")
            cost = float(r.get("cost_usd", 0) or 0)
            if proj:
                costs[proj] = costs.get(proj, 0.0) + cost
        return costs
    except Exception:
        return {}


def _fetch_vercel_errors():
    """Pull Vercel deployment error rates via CLI. Fail-soft."""
    try:
        result = subprocess.run(
            ["vercel", "ls", "--json"],
            capture_output=True, text=True, timeout=VERCEL_TIMEOUT
        )
        if result.returncode != 0:
            return {}
        deployments = json.loads(result.stdout) if result.stdout else []
        if not isinstance(deployments, list):
            return {}
        errors = {}
        for d in deployments:
            name = d.get("name", "")
            state = d.get("state", "")
            if name:
                if name not in errors:
                    errors[name] = {"total": 0, "error": 0}
                errors[name]["total"] += 1
                if state in ("ERROR", "CANCELED"):
                    errors[name]["error"] += 1
        rates = {}
        for name, counts in errors.items():
            if counts["total"] > 0:
                rates[name] = counts["error"] / counts["total"]
        return rates
    except Exception:
        return {}


def collect():
    """
    Collect all app signals and normalize into the ctx['app_signals'] format:
    {project: {usage_trend: float, error_rate: float, cost_burn: float}}
    
    All fail-soft: missing signal = neutral (0.0).
    """
    health = _fetch_deploy_health()
    metrics = _fetch_app_metrics()
    costs = _fetch_ai_call_costs()
    vercel_errors = _fetch_vercel_errors()

    all_projects = set(list(health.keys()) + list(metrics.keys()) +
                       list(costs.keys()) + list(vercel_errors.keys()))

    signals = {}
    for proj in all_projects:
        proj_metrics = metrics.get(proj, {})
        # usage_trend: positive = growing, negative = shrinking, 0 = neutral
        usage_trend = 0.0
        if "active_users" in proj_metrics:
            usage_trend = min(max(proj_metrics["active_users"] / 100.0, -1.0), 1.0)
        elif "signups" in proj_metrics:
            usage_trend = min(max(proj_metrics["signups"] / 50.0, -1.0), 1.0)
        elif "api_calls" in proj_metrics:
            usage_trend = min(max(proj_metrics["api_calls"] / 1000.0, -1.0), 1.0)

        # error_rate: 0..1, combine deploy health + vercel errors + app-reported errors
        error_rate = 0.0
        h = health.get(proj, "unknown")
        if h in ("error", "failing", "down"):
            error_rate = max(error_rate, 0.8)
        elif h in ("degraded", "warning"):
            error_rate = max(error_rate, 0.4)
        vercel_er = vercel_errors.get(proj, 0.0)
        error_rate = max(error_rate, vercel_er)
        if "errors" in proj_metrics:
            app_er = min(proj_metrics["errors"] / 100.0, 1.0)
            error_rate = max(error_rate, app_er)

        # cost_burn: raw USD cost in the window
        cost_burn = costs.get(proj, 0.0)

        signals[proj] = {
            "usage_trend": round(usage_trend, 4),
            "error_rate": round(error_rate, 4),
            "cost_burn": round(cost_burn, 4),
        }
    return signals


def run():
    """Entry point for periodic invocation. Stores signals in resource_events."""
    try:
        signals = collect()
        if signals:
            db.insert("resource_events", {
                "kind": "telemetry_signals",
                "payload": json.dumps(signals),
                "project": "orchestrator",
            })
        return signals
    except Exception:
        return {}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
