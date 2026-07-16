#!/usr/bin/env python3
"""
cade_scorecard.py - Pure aggregator for per-app CADE telemetry into fleet scorecard.

Takes per-app CADE KPI dicts (win-rate lift, calibration gap, alignment recall/surprise,
override failure-rate) — shapes from apparently's GET /api/firm-api/positions/kpi and
/alignment-kpi — and produces:
  (a) a normalized fleet scorecard (0-1 scores per dimension per app)
  (b) a weakest_app + recommended_next_capability hint for the scheduler

The run() function fetches telemetry from the controls table, aggregates via the pure
functions below, stores the fleet scorecard snapshot, and returns the scheduler hint.
"""
import os, sys, json, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# How many recent telemetry snapshots to keep per app
MAX_HISTORY = int(os.environ.get("ORCH_SCORECARD_HISTORY", "50"))


# ─── Pure Functions ───

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


# ─── DB-Backed Telemetry Fetch ───

def _load_app_telemetry():
    """Fetch per-app CADE telemetry from the controls table.

    Expects a controls row with key='cade_app_telemetry' whose value is a JSON dict
    of {app_name: {win_rate_lift, calibration_gap, alignment_recall,
    alignment_surprise, override_failure}}.

    These KPIs originate from apparently's GET /api/firm-api/positions/kpi
    and /alignment-kpi endpoints, ingested by the telemetry sync job.
    """
    try:
        rows = db.select("controls", {
            "select": "value",
            "key": "eq.cade_app_telemetry",
        })
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_scorecard_snapshot(scorecard, hint):
    """Persist the latest fleet scorecard snapshot into controls for dashboard use."""
    snapshot = {
        "timestamp": time.time(),
        "iso": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scorecard": scorecard,
        "weakest": hint,
        "app_count": len(scorecard),
    }

    # Load existing history and append
    history = []
    try:
        rows = db.select("controls", {
            "select": "value",
            "key": "eq.cade_fleet_scorecard",
        })
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            prev = json.loads(v) if isinstance(v, str) else v
            history = prev.get("history", [])
    except Exception:
        pass

    history.append(snapshot)
    history = history[-MAX_HISTORY:]

    try:
        db.upsert("controls", {
            "key": "cade_fleet_scorecard",
            "value": json.dumps({
                "current": snapshot,
                "history": history,
            }, default=str),
        })
    except Exception:
        pass


# ─── Runner Entry Point ───

def run():
    """Periodic aggregator: fetch per-app CADE telemetry, build fleet scorecard,
    persist snapshot, and return the scheduler hint.

    Returns dict with status, app_count, scorecard rows, and weakest_app hint.
    """
    apps = _load_app_telemetry()
    if not apps:
        print("[cade_scorecard] no app telemetry found")
        return {"status": "no_data", "app_count": 0, "scorecard": [], "weakest": None}

    sc = fleet_scorecard(apps)
    hint = weakest_app(apps)

    _save_scorecard_snapshot(sc, hint)

    # Log summary
    print(f"[cade_scorecard] {len(sc)} apps scored")
    for row in sc:
        print(f"  {row['app']}: {row['score']:.4f}")
    if hint:
        print(f"  weakest: {hint['app']} (score={hint['score']:.4f}, "
              f"gap={hint['gap']}, next={hint['recommended_next_capability']})")

    return {
        "status": "ok",
        "app_count": len(sc),
        "scorecard": sc,
        "weakest": hint,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
