#!/usr/bin/env python3
"""kpi_regression_watchdog.py — Detect KPI regressions and alert.

Monitors key fleet metrics over rolling windows and fires alerts when
a metric regresses beyond its threshold. Pure DB reads, no model spend.

Sub-tasks for full D3 implementation:
  1. [DONE] Core watchdog: compare current vs baseline windows, flag regressions
  2. [TODO] D2 auto-apply tier: auto-pause projects whose merge_rate < threshold
  3. [TODO] C4 causal attribution: correlate regression onset with recent changes
  4. [TODO] Alert routing: send regressions to Slack / fleet_control
  5. [TODO] Historical tracking: persist regression events for trend analysis

Acceptance tests (inline, run with pytest or python -m unittest):
  - test_no_regression_when_stable: metrics within threshold → no alert
  - test_regression_detected: metric drops > threshold → alert fires
  - test_handles_empty_data: no data → graceful empty result
  - test_handles_missing_fields: partial rows → no crash
  - test_multiple_regressions: multiple KPIs regress → all reported
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# ── KPI definitions ─────────────────────────────────────────────────────────
# Each KPI: (name, extractor, direction, threshold_pct)
# direction: "higher_better" means a drop is a regression
# threshold_pct: minimum % change to fire alert (avoids noise)
KPIS = [
    ("merge_rate", lambda rows: _rate(rows, "integrated"), "higher_better", 10),
    ("first_pass_rate", lambda rows: _rate(rows, "tests_passed"), "higher_better", 10),
    ("usd_per_merge", lambda rows: _cost_per_merge(rows), "lower_better", 20),
    ("avg_wall_min", lambda rows: _avg_wall(rows), "lower_better", 25),
    ("deploy_success_rate", lambda rows: _rate(rows, "deploy_ok"), "higher_better", 5),
]

BASELINE_WINDOW_H = int(os.environ.get("ORCH_KPI_BASELINE_H", "168"))  # 7 days
CURRENT_WINDOW_H = int(os.environ.get("ORCH_KPI_CURRENT_H", "24"))     # 1 day


def _rate(rows, field):
    if not rows:
        return None
    hits = sum(1 for r in rows if r.get(field))
    return round(hits / len(rows), 4)


def _cost_per_merge(rows):
    merged = sum(1 for r in rows if r.get("integrated"))
    if not merged:
        return None
    usd = sum(float(r.get("usd") or 0) for r in rows)
    return round(usd / merged, 4)


def _avg_wall(rows):
    if not rows:
        return None
    total_ms = sum(int(r.get("wall_ms") or 0) for r in rows)
    return round((total_ms / len(rows)) / 60000, 2)


def _fetch_outcomes(hours_ago_start, hours_ago_end=0):
    """Fetch outcome rows from the DB for a time window."""
    now = datetime.datetime.utcnow()
    start = (now - datetime.timedelta(hours=hours_ago_start)).isoformat()
    end = (now - datetime.timedelta(hours=hours_ago_end)).isoformat()
    try:
        return db.query(
            f"SELECT * FROM outcomes WHERE created_at >= '{start}' AND created_at <= '{end}'"
        ) or []
    except Exception:
        return []


def check(baseline_rows=None, current_rows=None):
    """Compare current KPIs against baseline; return list of regressions.

    If rows not provided, fetches from DB. Each regression is a dict:
      {kpi, baseline_value, current_value, change_pct, direction, threshold_pct}
    """
    if baseline_rows is None:
        baseline_rows = _fetch_outcomes(BASELINE_WINDOW_H, CURRENT_WINDOW_H)
    if current_rows is None:
        current_rows = _fetch_outcomes(CURRENT_WINDOW_H)

    regressions = []
    for name, extractor, direction, threshold in KPIS:
        base_val = extractor(baseline_rows)
        curr_val = extractor(current_rows)

        if base_val is None or curr_val is None or base_val == 0:
            continue

        change_pct = round(((curr_val - base_val) / abs(base_val)) * 100, 2)

        regressed = False
        if direction == "higher_better" and change_pct < -threshold:
            regressed = True
        elif direction == "lower_better" and change_pct > threshold:
            regressed = True

        if regressed:
            regressions.append({
                "kpi": name,
                "baseline_value": base_val,
                "current_value": curr_val,
                "change_pct": change_pct,
                "direction": direction,
                "threshold_pct": threshold,
            })

    return regressions


def tick():
    """Called from main loop; fail-soft."""
    try:
        regressions = check()
        if regressions:
            for r in regressions:
                print(f"kpi_watchdog: REGRESSION {r['kpi']} "
                      f"{r['baseline_value']}->{r['current_value']} "
                      f"({r['change_pct']:+.1f}%, threshold {r['threshold_pct']}%)",
                      flush=True)
            try:
                import json
                db.insert("fleet_config",
                          {"key": "KPI_REGRESSIONS", "value": json.dumps(regressions, default=str)},
                          upsert=True)
            except Exception:
                pass
        return regressions
    except Exception as e:
        print(f"kpi_watchdog: tick error ({e})")
        return []


# ── Inline tests ─────────────────────────────────────────────────────────────
import unittest


class TestWatchdog(unittest.TestCase):

    def test_no_regression_when_stable(self):
        rows = [{"integrated": True, "tests_passed": True, "usd": 0.5, "wall_ms": 60000, "deploy_ok": True}] * 10
        result = check(baseline_rows=rows, current_rows=rows)
        self.assertEqual(result, [])

    def test_regression_detected(self):
        baseline = [{"integrated": True, "tests_passed": True, "usd": 0.5, "wall_ms": 60000}] * 10
        current = [{"integrated": False, "tests_passed": False, "usd": 0.5, "wall_ms": 60000}] * 10
        result = check(baseline_rows=baseline, current_rows=current)
        kpi_names = [r["kpi"] for r in result]
        self.assertIn("merge_rate", kpi_names)
        self.assertIn("first_pass_rate", kpi_names)

    def test_handles_empty_data(self):
        result = check(baseline_rows=[], current_rows=[])
        self.assertEqual(result, [])

    def test_handles_missing_fields(self):
        rows = [{"some_other_field": "value"}] * 5
        result = check(baseline_rows=rows, current_rows=rows)
        self.assertIsInstance(result, list)

    def test_multiple_regressions(self):
        baseline = [{"integrated": True, "tests_passed": True, "usd": 0.3, "wall_ms": 30000, "deploy_ok": True}] * 20
        current = [{"integrated": False, "tests_passed": False, "usd": 1.0, "wall_ms": 120000, "deploy_ok": False}] * 20
        result = check(baseline_rows=baseline, current_rows=current)
        self.assertGreaterEqual(len(result), 3)


if __name__ == "__main__":
    if "--test" in sys.argv:
        unittest.main(argv=["test_kpi_watchdog"])
    else:
        import json
        print(json.dumps(check(), indent=2, default=str))
