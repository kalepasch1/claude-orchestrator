#!/usr/bin/env python3
"""
portfolio_autopilot.py — nightly cron: cold-start idle apps, auto-tune distribution,
score runs, compute relationship strength, and write a per-app digest line.

Feature flag: ORCH_PORTFOLIO_AUTOPILOT_ENABLED (default true).
Registered in periodic.py and runner.py _SCHEDULE as a nightly job.

Nothing is sent or spent — all gated work stays gated.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("ORCH_PORTFOLIO_AUTOPILOT_ENABLED", "true").lower() in ("1", "true", "yes", "on")


def _enabled_apps():
    """Return growth_apps rows where enabled=true."""
    try:
        return db.select("growth_apps", {"select": "*", "enabled": "eq.true"}) or []
    except Exception as e:
        print(f"portfolio_autopilot: growth_apps fetch failed: {e}")
        return []


def _active_run_count(app_id):
    """Count active growth_distribution_run rows for an app."""
    try:
        rows = db.select("growth_distribution_run", {
            "select": "id",
            "app_id": f"eq.{app_id}",
            "status": "eq.active",
        }) or []
        return len(rows)
    except Exception:
        return -1  # unknown -> skip cold-start (fail-soft)


def _cold_start(app):
    """Launch proven plays for an app with zero active distribution runs."""
    try:
        db.rpc("cold_start_app", {"p_app_id": app["id"], "p_count": 3, "p_mode": "approval"})
        return "cold_started"
    except Exception as e:
        return f"cold_start_err: {e}"


def _get_setting(key, default=None):
    """Read a value from growth_settings by key."""
    try:
        rows = db.select("growth_settings", {"select": "value", "key": f"eq.{key}", "limit": "1"}) or []
        if rows:
            return rows[0].get("value", default)
    except Exception:
        pass
    return default


def _auto_tune(ceiling):
    """Call auto_tune_distribution with the CAC ceiling."""
    try:
        result = db.rpc("auto_tune_distribution", {"p_ceiling": ceiling})
        return result
    except Exception as e:
        return f"auto_tune_err: {e}"


def _score_runs():
    """Score all distribution runs."""
    try:
        return db.rpc("score_distribution_runs", {})
    except Exception as e:
        return f"score_err: {e}"


def _compute_relationships():
    """Compute relationship strength across the portfolio."""
    try:
        return db.rpc("compute_relationship_strength", {})
    except Exception as e:
        return f"relationship_err: {e}"


def _signups_per_human_hour(app):
    """Fetch signups_per_human_hour for an app (returns 0 on failure)."""
    try:
        rows = db.select("growth_distribution_run", {
            "select": "signups,human_hours",
            "app_id": f"eq.{app['id']}",
            "status": "eq.active",
        }) or []
        total_signups = sum(r.get("signups") or 0 for r in rows)
        total_hours = sum(r.get("human_hours") or 0 for r in rows)
        if total_hours > 0:
            return round(total_signups / total_hours, 2)
        return 0
    except Exception:
        return 0


def _write_digest(app, sphr, auto_tune_report, cold_start_result):
    """Write one digest line per app into growth_intake_suggestion."""
    severity = "high" if sphr == 0 else "low"
    detail_parts = [f"signups_per_human_hour={sphr}"]
    if auto_tune_report:
        detail_parts.append(f"auto_tune={auto_tune_report}")
    if cold_start_result:
        detail_parts.append(f"cold_start={cold_start_result}")
    if sphr == 0:
        detail_parts.append("FLAG: 0 signups — needs attention")

    detail = "; ".join(detail_parts)
    try:
        db.insert("growth_intake_suggestion", {
            "app_id": app["id"],
            "app_name": app.get("name", "unknown"),
            "kind": "portfolio_autopilot_digest",
            "severity": severity,
            "detail": detail,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        })
    except Exception as e:
        print(f"portfolio_autopilot digest write failed for {app.get('name')}: {e}")


def run():
    """Main entry point — called nightly by periodic.py."""
    if not ENABLED:
        print("portfolio_autopilot: disabled (ORCH_PORTFOLIO_AUTOPILOT_ENABLED)")
        return {"skipped": True}

    apps = _enabled_apps()
    if not apps:
        print("portfolio_autopilot: no enabled apps")
        return {"apps": 0}

    # 1. Cold-start apps with zero active runs
    cold_started = 0
    cold_results = {}
    for app in apps:
        count = _active_run_count(app["id"])
        if count == 0:
            result = _cold_start(app)
            cold_results[app.get("name", app["id"])] = result
            cold_started += 1

    # 2. Auto-tune distribution from growth_settings ceiling
    ceiling = _get_setting("distribution_cac_ceiling", 50)
    try:
        ceiling = float(ceiling)
    except (TypeError, ValueError):
        ceiling = 50.0
    auto_tune_report = _auto_tune(ceiling)

    # 3. Score runs and compute relationships
    score_result = _score_runs()
    relationship_result = _compute_relationships()

    # 4. Write digest per app
    for app in apps:
        sphr = _signups_per_human_hour(app)
        cs = cold_results.get(app.get("name", app["id"]))
        _write_digest(app, sphr, auto_tune_report, cs)

    summary = {
        "apps": len(apps),
        "cold_started": cold_started,
        "auto_tune": auto_tune_report,
        "score": score_result,
        "relationships": relationship_result,
    }
    print(f"portfolio_autopilot: {summary}")
    return summary


def stats():
    """Return lightweight stats for the dashboard / monitoring."""
    if not ENABLED:
        return {"enabled": False}
    apps = _enabled_apps()
    zero_run_apps = []
    for app in apps:
        if _active_run_count(app["id"]) == 0:
            zero_run_apps.append(app.get("name", app["id"]))
    ceiling = _get_setting("distribution_cac_ceiling", 50)
    return {
        "enabled": True,
        "total_apps": len(apps),
        "zero_run_apps": zero_run_apps,
        "cac_ceiling": ceiling,
    }


if __name__ == "__main__":
    run()
