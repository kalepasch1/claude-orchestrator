#!/usr/bin/env python3
"""kpi_regression_watchdog.py - Detect KPI regressions and auto-file remediation."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
_WINDOW_HOURS = int(os.environ.get("KPI_WINDOW_HOURS", "24"))
_BASELINE_DAYS = int(os.environ.get("KPI_BASELINE_DAYS", "7"))
_THRESHOLD_PCT = float(os.environ.get("KPI_REGRESSION_THRESHOLD", "0.15"))
KPI_DEFS = {"first_pass_rate": {"direction": "higher_better", "min_samples": 5}, "merge_rate": {"direction": "higher_better", "min_samples": 5}, "usd_per_merge": {"direction": "lower_better", "min_samples": 3}, "avg_wall_min": {"direction": "lower_better", "min_samples": 3}}
def _fetch_outcomes(hours):
    return db.sql("SELECT * FROM outcomes WHERE created_at > now() - interval '%s hours'" % int(hours)) or []
def _compute_kpi(rows, kpi_name):
    from scoreboard_metrics import _outcome_metrics
    return _outcome_metrics(rows).get(kpi_name)
def _baseline(kpi_name):
    return _compute_kpi(_fetch_outcomes(_BASELINE_DAYS * 24), kpi_name)
def _is_regression(current, baseline, defn):
    if current is None or baseline is None: return False
    if defn["direction"] == "higher_better": return current < baseline * (1 - _THRESHOLD_PCT)
    return current > baseline * (1 + _THRESHOLD_PCT)
def _attribute_cause(kpi_name, current, baseline):
    causes = []
    rc = db.sql("SELECT key FROM fleet_config WHERE updated_at > now() - interval '24 hours'") or []
    if rc: causes.append(f"config_changes: {len(rc)} keys changed")
    rm = db.sql("SELECT DISTINCT model FROM outcomes WHERE created_at > now() - interval '6 hours'") or []
    if len(rm) > 1: causes.append("model_mix: multiple models active")
    return causes or ["unknown"]
def check():
    regressions = []
    for kpi, defn in KPI_DEFS.items():
        recent = _fetch_outcomes(_WINDOW_HOURS)
        if len(recent) < defn["min_samples"]: continue
        cur = _compute_kpi(recent, kpi)
        base = _baseline(kpi)
        if _is_regression(cur, base, defn):
            regressions.append({"kpi": kpi, "current": cur, "baseline": base, "causes": _attribute_cause(kpi, cur, base)})
    for r in regressions:
        existing = db.sql("SELECT id FROM tasks WHERE slug='kpi-fix-%s' AND state IN ('QUEUED','RUNNING')" % r["kpi"]) or []
        if not existing:
            db.insert("tasks", {"slug": f"kpi-fix-{r['kpi']}", "kind": "bugfix", "state": "QUEUED", "prompt": f"KPI REGRESSION: {r['kpi']} {r['baseline']}->{r['current']}. Causes: {', '.join(r['causes'])}"})
    print(f"kpi_watchdog: {len(regressions)} regression(s)")
    return regressions
if __name__ == "__main__": check()
