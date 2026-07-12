#!/usr/bin/env python3
"""
kpi_eval_harness.py - KPI regression watchdog for self-improvements.

Compares 24h before/after for the declared target KPI of each auto-applied
self-improvement and logs a postmortem row if:
  - the target KPI didn't move (delta < 1% improvement), OR
  - any tracked KPI regressed more than 10%.

Usage: python3 kpi_eval_harness.py
Schedule daily or after each self-improvement apply window.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW_H = int(os.environ.get("KPI_EVAL_WINDOW_H", "24"))
REGRESSION_THRESHOLD = float(os.environ.get("KPI_REGRESSION_PCT", "10"))
MIN_IMPROVEMENT_PCT = float(os.environ.get("KPI_MIN_IMPROVEMENT_PCT", "1"))


def _iso_ago(hours):
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat()


def _scoreboard_snapshot(start_iso, end_iso):
    """Fetch scoreboard rows in a time range, return averaged KPI dict."""
    try:
        rows = db.select("scoreboard", {
            "select": "*",
            "generated_at": f"gte.{start_iso}",
            "order": "generated_at.desc",
            "limit": "100",
        }) or []
        # Filter to only rows within the window
        rows = [r for r in rows if str(r.get("generated_at", "")) <= end_iso]
    except Exception:
        rows = []
    if not rows:
        return {}
    # Average numeric KPI fields across snapshots
    kpi_keys = ["merge_rate", "first_pass_rate", "usd_per_merge", "tokens_per_merge",
                "avg_wall_min", "review_failures_per_merge"]
    result = {}
    for key in kpi_keys:
        vals = [float(r["overall"][key]) for r in rows
                if isinstance(r.get("overall"), dict) and r["overall"].get(key) is not None]
        if vals:
            result[key] = sum(vals) / len(vals)
    return result


def _pct_change(before, after):
    """Percentage change from before to after. Positive = improvement for rates, negative for costs."""
    if not before:
        return 0.0
    return ((after - before) / abs(before)) * 100.0


# KPIs where higher = better
_HIGHER_BETTER = {"merge_rate", "first_pass_rate"}
# KPIs where lower = better
_LOWER_BETTER = {"usd_per_merge", "tokens_per_merge", "avg_wall_min", "review_failures_per_merge"}


def _improved(kpi_name, pct_change):
    """Return True if the pct_change represents improvement for this KPI."""
    if kpi_name in _HIGHER_BETTER:
        return pct_change > 0
    if kpi_name in _LOWER_BETTER:
        return pct_change < 0
    return abs(pct_change) > 0


def _regressed(kpi_name, pct_change):
    """Return True if the pct_change represents regression for this KPI."""
    if kpi_name in _HIGHER_BETTER:
        return pct_change < -REGRESSION_THRESHOLD
    if kpi_name in _LOWER_BETTER:
        return pct_change > REGRESSION_THRESHOLD
    return False


def _recent_auto_applies():
    """Find auto-applied self-improvements from the last 48h that have a target_kpi."""
    try:
        rows = db.select("approvals", {
            "select": "id,title,decided_by,decision_text,brief_json,updated_at",
            "status": "eq.approved",
            "decided_by": "like.owner-model%",
            "order": "updated_at.desc",
            "limit": "100",
        }) or []
    except Exception:
        rows = []
    cutoff = _iso_ago(48)
    return [r for r in rows if str(r.get("updated_at", "")) >= cutoff]


def evaluate():
    """Compare 24h before vs 24h after each recent auto-apply. Log postmortems."""
    now = datetime.datetime.utcnow()
    applies = _recent_auto_applies()
    postmortems = 0

    for app in applies:
        apply_ts = str(app.get("updated_at") or now.isoformat())
        # 24h window before apply
        before_end = apply_ts
        before_start = (datetime.datetime.fromisoformat(apply_ts.replace("Z", "+00:00").replace("+00:00", ""))
                        - datetime.timedelta(hours=WINDOW_H)).isoformat()
        # 24h window after apply
        after_start = apply_ts
        after_end = (datetime.datetime.fromisoformat(apply_ts.replace("Z", "+00:00").replace("+00:00", ""))
                     + datetime.timedelta(hours=WINDOW_H)).isoformat()

        before_kpis = _scoreboard_snapshot(before_start, before_end)
        after_kpis = _scoreboard_snapshot(after_start, after_end)

        if not before_kpis or not after_kpis:
            continue

        # Extract target_kpi from brief_json if declared
        bj = app.get("brief_json") or {}
        target_kpi = bj.get("target_kpi") if isinstance(bj, dict) else None

        # Check target KPI didn't move
        target_stalled = False
        if target_kpi and target_kpi in before_kpis and target_kpi in after_kpis:
            delta = _pct_change(before_kpis[target_kpi], after_kpis[target_kpi])
            if not _improved(target_kpi, delta) or abs(delta) < MIN_IMPROVEMENT_PCT:
                target_stalled = True

        # Check for any KPI regression > threshold
        regressions = {}
        for kpi in before_kpis:
            if kpi in after_kpis:
                delta = _pct_change(before_kpis[kpi], after_kpis[kpi])
                if _regressed(kpi, delta):
                    regressions[kpi] = round(delta, 2)

        if target_stalled or regressions:
            postmortem = {
                "approval_id": app.get("id"),
                "title": (app.get("title") or "")[:200],
                "target_kpi": target_kpi,
                "target_stalled": target_stalled,
                "regressions": regressions,
                "before_kpis": {k: round(v, 4) for k, v in before_kpis.items()},
                "after_kpis": {k: round(v, 4) for k, v in after_kpis.items()},
                "window_h": WINDOW_H,
                "evaluated_at": now.isoformat(),
            }
            try:
                import json
                db.insert("postmortems", {
                    "kind": "kpi_regression",
                    "source": f"kpi_eval_harness:{app.get('id', '')[:36]}",
                    "payload": json.dumps(postmortem, default=str),
                    "created_at": now.isoformat(),
                })
            except Exception as e:
                print(f"kpi_eval_harness: failed to log postmortem: {e}")
            postmortems += 1

    print(f"kpi_eval_harness: evaluated {len(applies)} auto-applies, "
          f"logged {postmortems} postmortems")
    return postmortems


def run():
    return evaluate()


if __name__ == "__main__":
    run()
