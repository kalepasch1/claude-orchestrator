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


def _app_key(app):
    """The app's identity. `growth_apps` is keyed on `app` (text) — there is no `id`.

    Reading app["id"] is what crash-looped this job: every enabled row raised KeyError on
    the first loop iteration, so the nightly autopilot had never completed a single run.
    Legacy key names are still accepted so a caller passing an older shape degrades to a
    skip rather than an exception.
    """
    if not isinstance(app, dict):
        return ""
    return str(app.get("app") or app.get("id") or app.get("slug") or "")


def _app_label(app):
    """Human label for logs and digests. The column is `display_name`, not `name`."""
    if not isinstance(app, dict):
        return "unknown"
    return str(app.get("display_name") or app.get("app") or app.get("name") or "unknown")


def _active_run_count(app_key):
    """Count active growth_distribution_run rows for an app.

    Filters on `app`: growth_distribution_run has no `app_id` column. The old filter
    returned HTTP 400, which this function's own except swallowed into -1, so cold-start
    was permanently dead even apart from the crash — a silent bug hiding behind a loud one.
    """
    if not app_key:
        return -1
    try:
        rows = db.select("growth_distribution_run", {
            "select": "id",
            "app": f"eq.{app_key}",
            "status": "eq.active",
        }) or []
        return len(rows)
    except Exception as e:
        print(f"portfolio_autopilot: active-run count failed for {app_key}: {e}")
        return -1  # unknown -> skip cold-start (fail-soft)


def _cold_start(app):
    """Launch proven plays for an app with zero active distribution runs.

    Real signature is cold_start_app(p_app text, p_n integer, p_mode text); the previous
    call passed p_app_id/p_count and could never bind.
    """
    app_key = _app_key(app)
    if not app_key:
        return "cold_start_skipped: no app key"
    try:
        db.rpc("cold_start_app", {"p_app": app_key, "p_n": 3, "p_mode": "approval"})
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
        # Real signature is auto_tune_distribution(p_cac_ceiling numeric); p_ceiling never bound.
        result = db.rpc("auto_tune_distribution", {"p_cac_ceiling": ceiling})
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
    """Signups per hour of human effort across an app's active runs.

    Returns None when the ratio is genuinely unknown, and 0.0 only when there really were
    zero signups against real human effort. That distinction matters: the digest escalates
    on 0, so conflating "no data" with "no signups" made every app permanently high-severity.

    growth_distribution_run has neither `signups` nor `human_hours` — the old query asked
    for both and got HTTP 400, swallowed into a hard 0. The real shape:
      growth_distribution_run(id, play_id, app, status)     -- which runs are active
      growth_distribution_metric(run_id, signups)           -- the signups
      growth_distribution_play(id, human_minutes)           -- the human effort
    Three keyed reads rather than one embedded select, so no FK-embedding names are assumed.
    """
    app_key = _app_key(app)
    if not app_key:
        return None
    try:
        runs = db.select("growth_distribution_run", {
            "select": "id,play_id",
            "app": f"eq.{app_key}",
            "status": "eq.active",
        }) or []
        if not runs:
            return None

        run_ids = [str(r["id"]) for r in runs if r.get("id")]
        play_ids = sorted({str(r["play_id"]) for r in runs if r.get("play_id")})
        if not run_ids:
            return None

        metrics = db.select("growth_distribution_metric", {
            "select": "signups",
            "run_id": f"in.({','.join(run_ids)})",
        }) or []
        total_signups = sum(float(m.get("signups") or 0) for m in metrics)

        total_minutes = 0.0
        if play_ids:
            plays = db.select("growth_distribution_play", {
                "select": "human_minutes",
                "id": f"in.({','.join(play_ids)})",
            }) or []
            total_minutes = sum(float(p.get("human_minutes") or 0) for p in plays)

        if total_minutes <= 0:
            return None                      # unknown effort -> unknown ratio, not zero
        return round(total_signups / (total_minutes / 60.0), 2)
    except Exception as e:
        print(f"portfolio_autopilot: sphr failed for {app_key}: {e}")
        return None


def _write_digest(app, sphr, auto_tune_report, cold_start_result):
    """Write one digest line per app into growth_intake_suggestion.

    Columns are (app, kind, severity, detail, ref, status) — there is no app_id/app_name,
    so every previous insert was rejected and swallowed by the except below.

    sphr is None when unknown; only a real 0.0 escalates.
    """
    app_key = _app_key(app)
    label = _app_label(app)
    escalate = (sphr is not None and sphr == 0)
    severity = "high" if escalate else "low"

    shown = "unknown" if sphr is None else sphr
    detail_parts = [f"signups_per_human_hour={shown}"]
    if auto_tune_report:
        detail_parts.append(f"auto_tune={auto_tune_report}")
    if cold_start_result:
        detail_parts.append(f"cold_start={cold_start_result}")
    if escalate:
        detail_parts.append("FLAG: 0 signups against real human effort — needs attention")
    elif sphr is None:
        detail_parts.append("no active runs with recorded human effort — ratio unavailable")

    detail = "; ".join(detail_parts)
    try:
        db.insert("growth_intake_suggestion", {
            "app": app_key,
            "kind": "portfolio_autopilot_digest",
            "severity": severity,
            "detail": f"[{label}] {detail}",
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        })
    except Exception as e:
        print(f"portfolio_autopilot digest write failed for {label}: {e}")


def run():
    """Main entry point — called nightly by periodic.py."""
    if not ENABLED:
        print("portfolio_autopilot: disabled (ORCH_PORTFOLIO_AUTOPILOT_ENABLED)")
        return {"skipped": True}

    apps = _enabled_apps()
    if not apps:
        print("portfolio_autopilot: no enabled apps")
        return {"apps": 0}

    # 1. Cold-start apps with zero active runs.
    # Keyed by _app_key(app) — app["id"] raised KeyError on the first iteration for every
    # enabled row, so nothing below this point had ever executed in production.
    cold_started = 0
    cold_results = {}
    for app in apps:
        app_key = _app_key(app)
        if not app_key:
            print(f"portfolio_autopilot: skipping row with no app key: {sorted(app)[:6]}")
            continue
        if _active_run_count(app_key) == 0:
            cold_results[app_key] = _cold_start(app)
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
        cs = cold_results.get(_app_key(app))
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
        app_key = _app_key(app)
        if app_key and _active_run_count(app_key) == 0:
            zero_run_apps.append(_app_label(app))
    ceiling = _get_setting("distribution_cac_ceiling", 50)
    return {
        "enabled": True,
        "total_apps": len(apps),
        "zero_run_apps": zero_run_apps,
        "cac_ceiling": ceiling,
    }


if __name__ == "__main__":
    run()
