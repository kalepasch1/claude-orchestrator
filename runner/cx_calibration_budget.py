#!/usr/bin/env python3
"""
cx_calibration_budget.py - advisory autonomy-budget adjustment from committee Brier scores.

committees.tune_budget() owns the live owner_model.autonomy_budget value. This runner reads the
committee_scoreboard Brier scores and writes only:
  * owner_model.autonomy_budget_brier_adj  (integer adjustment)
  * an approvals/self advisory note for the inbox

Lower Brier is better. A calls-weighted committee Brier score earns or loses a small daily budget
recommendation without overwriting the live budget.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ADVISORY_KEY = "autonomy_budget_brier_adj"
LIVE_BUDGET_KEY = "autonomy_budget"
MIN_BUDGET = 5
MAX_BUDGET = 50


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _num(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _usable_rows(rows):
    usable = []
    for r in rows or []:
        brier = _num(r.get("brier"))
        calls = _int(r.get("calls"))
        if brier is None or calls <= 0:
            continue
        usable.append({
            "committee": r.get("committee") or "",
            "brier": _clamp(brier, 0.0, 1.0),
            "calls": calls,
        })
    return usable


def _weighted_brier(rows):
    usable = _usable_rows(rows)
    calls = sum(r["calls"] for r in usable)
    if calls <= 0:
        return None, 0, usable
    return sum(r["brier"] * r["calls"] for r in usable) / calls, calls, usable


def _adjustment_for_brier(brier):
    """Translate proper scoring into a conservative daily budget recommendation."""
    if brier is None:
        return 0
    if brier <= 0.12:
        return 5
    if brier <= 0.18:
        return 3
    if brier <= 0.25:
        return 1
    if brier <= 0.30:
        return 0
    if brier <= 0.40:
        return -2
    return -4


def _current_budget():
    default = int(os.environ.get("COMMITTEE_DAILY_AUTOBUILDS", "20"))
    try:
        rows = db.select("owner_model", {"select": "value", "key": f"eq.{LIVE_BUDGET_KEY}"}) or []
        if rows:
            return _int(rows[0].get("value"), default)
    except Exception:
        pass
    return default


def _reason(adj):
    if adj > 0:
        return "committee probability forecasts are well-calibrated enough to earn more autonomy"
    if adj < 0:
        return "committee probability forecasts are under-calibrated; reduce autonomy until scoring improves"
    return "committee probability forecasts are near the hold band; keep autonomy steady"


def _write_advisory(adj, weighted, calls, current, recommended):
    db.insert("owner_model", {"key": ADVISORY_KEY, "value": adj, "updated_at": "now()"}, upsert=True)
    brier_txt = "unavailable" if weighted is None else f"{weighted:.3f}"
    sign = f"+{adj}" if adj > 0 else str(adj)
    db.insert("approvals", {
        "project": "beethoven",
        "kind": "self",
        "title": f"ADVISORY: Brier autonomy-budget adjustment {sign}",
        "why": (f"Calls-weighted committee Brier score is {brier_txt} across {calls} realized calls; "
                f"{_reason(adj)}."),
        "value": (f"Recommend daily autonomy budget {current} -> {recommended}. This is advisory only; "
                  "committees.tune_budget remains the sole writer of autonomy_budget."),
        "risk": "Low - records a recommendation and inbox note without changing the live autonomy_budget.",
        "command": "",
    })


def run():
    """Compute and record an advisory autonomy-budget adjustment from committee Brier scores."""
    rows = db.select("committee_scoreboard", {
        "select": "committee,brier,calls",
        "entity_type": "eq.committee",
    }) or []
    weighted, calls, usable = _weighted_brier(rows)
    adj = _adjustment_for_brier(weighted)
    current = _current_budget()
    recommended = _clamp(current + adj, MIN_BUDGET, MAX_BUDGET)
    _write_advisory(adj, weighted, calls, current, recommended)
    print(f"cx_calibration_budget: brier={weighted if weighted is not None else 'n/a'} "
          f"calls={calls} adjustment={adj} advisory_budget={recommended}")
    return {
        "adjustment": adj,
        "weighted_brier": None if weighted is None else round(weighted, 3),
        "calls": calls,
        "committees": len(usable),
        "current_budget": current,
        "recommended_budget": recommended,
    }


if __name__ == "__main__":
    run()
