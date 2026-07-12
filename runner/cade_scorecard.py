#!/usr/bin/env python3
"""
cade_scorecard.py - Pure aggregator for CADE fleet telemetry.

Takes per-app CADE KPI dicts (win-rate lift, calibration gap, alignment recall/surprise,
override failure-rate) and produces:
  (a) a normalized fleet scorecard
  (b) a weakest_app + recommended_next_capability hint

Pure functions only (inputs passed in; no live HTTP). Does NOT wire into the live
scheduler (that is a follow-up, human-approved).
"""


def normalize_kpi(raw, *, floor=0.0, ceiling=1.0):
    """Clamp and normalize a raw KPI value to [0, 1]. Higher is better."""
    if raw is None:
        return 0.0
    v = float(raw)
    if ceiling == floor:
        return 1.0 if v >= ceiling else 0.0
    return max(0.0, min(1.0, (v - floor) / (ceiling - floor)))


def score_app(kpis):
    """Score a single app's CADE KPIs into a normalized 0-1 composite.

    Expected keys (all optional, missing -> 0):
      win_rate_lift:       float, higher is better (range 0-1)
      calibration_gap:     float, lower is better  (range 0-1, inverted)
      alignment_recall:    float, higher is better (range 0-1)
      alignment_surprise:  float, lower is better  (range 0-1, inverted)
      override_failure:    float, lower is better  (range 0-1, inverted)
    """
    if not kpis:
        return 0.0
    weights = {
        "win_rate_lift":      0.25,
        "calibration_gap":    0.25,
        "alignment_recall":   0.25,
        "alignment_surprise": 0.10,
        "override_failure":   0.15,
    }
    total = 0.0
    for key, w in weights.items():
        raw = kpis.get(key)
        if raw is None:
            continue
        if key in ("calibration_gap", "alignment_surprise", "override_failure"):
            total += w * normalize_kpi(1.0 - float(raw))
        else:
            total += w * normalize_kpi(float(raw))
    return round(total, 4)


def fleet_scorecard(apps):
    """Build a normalized fleet scorecard from a dict of {app_name: kpis_dict}.
    Returns a list of dicts sorted by score (ascending = weakest first)."""
    if not apps:
        return []
    rows = []
    for name, kpis in apps.items():
        rows.append({"app": name, "score": score_app(kpis), "kpis": kpis or {}})
    rows.sort(key=lambda r: r["score"])
    return rows


_CAPABILITY_MAP = {
    "win_rate_lift":      "ab_experimentation",
    "calibration_gap":    "forecast_calibration",
    "alignment_recall":   "alignment_monitoring",
    "alignment_surprise": "anomaly_detection",
    "override_failure":   "override_governance",
}


def weakest_app(apps):
    """Identify the weakest app and recommend the next capability to improve.
    Tie-break: alphabetical by app name (deterministic)."""
    sc = fleet_scorecard(apps)
    if not sc:
        return None

    min_score = sc[0]["score"]
    candidates = [r for r in sc if r["score"] == min_score]
    candidates.sort(key=lambda r: r["app"])
    worst = candidates[0]

    kpis = worst.get("kpis") or {}
    worst_gap = None
    worst_gap_val = float("inf")
    for key in ("win_rate_lift", "calibration_gap", "alignment_recall",
                "alignment_surprise", "override_failure"):
        raw = kpis.get(key)
        if raw is None:
            worst_gap = key
            worst_gap_val = -1
            continue
        if key in ("calibration_gap", "alignment_surprise", "override_failure"):
            effective = 1.0 - float(raw)
        else:
            effective = float(raw)
        if effective < worst_gap_val:
            worst_gap_val = effective
            worst_gap = key

    recommended = _CAPABILITY_MAP.get(worst_gap, "general_improvement")

    return {
        "app": worst["app"],
        "score": worst["score"],
        "gap": worst_gap,
        "recommended_next_capability": recommended,
    }
