#!/usr/bin/env python3
"""
experiment_analyzer.py — Autonomous experiment analysis and recommendation engine.

Analyzes completed experiment outcomes from the experiments/experiment_outcomes tables,
identifies statistically significant winners, and recommends follow-up experiments
based on observed patterns (e.g., if raising CONTEXT_MAX_FILES helped, try raising further).

Owner module: auto_experiment.py, experiment_router.py
Slice-2 of: improve-enhance-autonomous-experimentation-with
"""
import os, sys, math, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fail-soft: return empty/defaults on any error
def _safe_import(mod):
    try:
        return __import__(mod)
    except Exception:
        return None

db = _safe_import("db")

# Minimum sample size per variant before we declare significance
MIN_SAMPLES = int(os.environ.get("ORCH_EXPERIMENT_MIN_SAMPLES", "3"))
# Minimum improvement ratio to recommend adoption
MIN_IMPROVEMENT = float(os.environ.get("ORCH_EXPERIMENT_MIN_IMPROVEMENT", "0.05"))
# Cost tolerance: candidate cost must be <= this multiplier of control cost
COST_TOLERANCE = float(os.environ.get("ORCH_EXPERIMENT_COST_TOLERANCE", "1.15"))


def _mean(vals):
    """Mean of a list; 0.0 if empty."""
    return sum(vals) / len(vals) if vals else 0.0


def _stddev(vals):
    """Population standard deviation; 0.0 if fewer than 2 values."""
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


def analyze_experiment(experiment_id):
    """Analyze outcomes for a single experiment.

    Returns dict with:
        status: 'significant_win' | 'significant_loss' | 'inconclusive' | 'insufficient_data'
        recommendation: 'adopt' | 'reject' | 'continue' | 'no_data'
        control_mean, candidate_mean, control_cost_mean, candidate_cost_mean
        detail: human-readable summary
    """
    if not db:
        return {"status": "insufficient_data", "recommendation": "no_data",
                "detail": "db module unavailable"}
    try:
        outcomes = db.select("experiment_outcomes", {
            "select": "*", "experiment_id": f"eq.{experiment_id}"
        }) or []
    except Exception:
        outcomes = []

    control = [o for o in outcomes if o.get("variant") == "control"]
    candidate = [o for o in outcomes if o.get("variant") == "candidate"]

    if len(control) < MIN_SAMPLES or len(candidate) < MIN_SAMPLES:
        return {
            "status": "insufficient_data",
            "recommendation": "continue",
            "control_n": len(control),
            "candidate_n": len(candidate),
            "detail": f"Need >= {MIN_SAMPLES} samples per variant; have control={len(control)}, candidate={len(candidate)}"
        }

    ctrl_scores = [float(o.get("tests_passed", 0)) for o in control]
    cand_scores = [float(o.get("tests_passed", 0)) for o in candidate]
    ctrl_costs = [float(o.get("cost_usd", 0)) for o in control]
    cand_costs = [float(o.get("cost_usd", 0)) for o in candidate]

    cm, canm = _mean(ctrl_scores), _mean(cand_scores)
    cc, canc = _mean(ctrl_costs), _mean(cand_costs)

    improvement = (canm - cm) / max(cm, 0.001)
    cost_ok = canc <= cc * COST_TOLERANCE if cc > 0 else True

    if improvement >= MIN_IMPROVEMENT and cost_ok:
        status, rec = "significant_win", "adopt"
    elif improvement <= -MIN_IMPROVEMENT:
        status, rec = "significant_loss", "reject"
    else:
        status, rec = "inconclusive", "continue"

    return {
        "status": status,
        "recommendation": rec,
        "control_mean": round(cm, 4),
        "candidate_mean": round(canm, 4),
        "control_cost_mean": round(cc, 4),
        "candidate_cost_mean": round(canc, 4),
        "improvement_pct": round(improvement * 100, 2),
        "cost_ok": cost_ok,
        "detail": f"ctrl={cm:.3f} cand={canm:.3f} improve={improvement*100:.1f}% cost_ok={cost_ok}"
    }


def recommend_next_experiments():
    """Scan completed experiments and suggest follow-up experiments.

    Logic: if a knob change was adopted, suggest exploring further in the same
    direction (e.g., CONTEXT_MAX_FILES 12->18 worked, try 18->24). If rejected,
    suggest the opposite direction or a different knob.

    Returns list of recommendation dicts.
    """
    if not db:
        return []
    try:
        experiments = db.select("experiments", {
            "select": "*", "status": "eq.active", "limit": "50"
        }) or []
    except Exception:
        return []

    recommendations = []
    for exp in experiments:
        analysis = analyze_experiment(exp.get("id"))
        if analysis["recommendation"] == "adopt":
            recommendations.append({
                "experiment_id": exp.get("id"),
                "category": exp.get("category", "unknown"),
                "action": "adopt_and_extend",
                "detail": f"Experiment shows {analysis['improvement_pct']}% improvement; adopt and try further."
            })
        elif analysis["recommendation"] == "reject":
            recommendations.append({
                "experiment_id": exp.get("id"),
                "category": exp.get("category", "unknown"),
                "action": "reject_and_pivot",
                "detail": f"Experiment shows regression; try opposite direction or different knob."
            })
    return recommendations


def stats():
    """Return summary stats for all experiments."""
    if not db:
        return {"total": 0, "active": 0, "analyzed": 0}
    try:
        all_exp = db.select("experiments", {"select": "id,status", "limit": "500"}) or []
        return {
            "total": len(all_exp),
            "active": sum(1 for e in all_exp if e.get("status") == "active"),
            "completed": sum(1 for e in all_exp if e.get("status") == "completed"),
        }
    except Exception:
        return {"total": 0, "active": 0, "analyzed": 0}
