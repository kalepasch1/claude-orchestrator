#!/usr/bin/env python3
"""Evidence gate for promoting the secondary lane beyond shadow/canary operation."""
from __future__ import annotations
import datetime, json, math
import db

MIN_SAMPLES = 20
TARGET_RATIO = 500.0

def _rate_bounds(rows):
    if not rows:
        return {"n": 0, "value": 0.0, "hours": 0.0, "lower_per_hour": 0.0, "upper_per_hour": 0.0}
    values = [max(0.0, float(r.get("value") or 0)) for r in rows]
    stamps = []
    for row in rows:
        try: stamps.append(datetime.datetime.fromisoformat(str(row.get("observed_at")).replace("Z", "+00:00")))
        except Exception: pass
    exposure = max(1.0, ((max(stamps)-min(stamps)).total_seconds()/3600) if len(stamps)>1 else len(rows))
    total = sum(values); root = math.sqrt(max(total, 0.0))
    return {"n": len(rows), "value": total, "hours": exposure,
            "lower_per_hour": max(0.0, total-1.96*root)/exposure,
            "upper_per_hour": (total+1.96*root+1.0)/exposure}

def evaluate(rows, minimum_samples=MIN_SAMPLES, target_ratio=TARGET_RATIO):
    secondary = _rate_bounds([r for r in rows if r.get("variant") == "secondary"])
    cowork = _rate_bounds([r for r in rows if r.get("variant") == "cowork"])
    ratio = secondary["lower_per_hour"] / max(cowork["upper_per_hour"], 1e-12)
    enough = secondary["n"] >= minimum_samples and cowork["n"] >= minimum_samples
    return {"promoted": bool(enough and ratio >= target_ratio), "target_ratio": target_ratio,
            "lower_bound_ratio": ratio, "enough_samples": enough,
            "secondary": secondary, "cowork": cowork,
            "mode": "promoted" if enough and ratio >= target_ratio else "shadow_canary"}

def decision(days=30):
    cutoff=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=days)).isoformat()
    try:
        rows=db.select("product_metric_events", {"select":"variant,value,observed_at",
            "experiment":"eq.orchestration_flow_value", "metric":"eq.deployed_non_regressed_value",
            "observed_at":f"gte.{cutoff}", "limit":"10000"}) or []
    except Exception: rows=[]
    result=evaluate(rows)
    try: db.insert("controls", {"key":"secondary_flow_promotion", "value":json.dumps(result),
                                "updated_at":"now()"}, upsert=True)
    except Exception: pass
    try:
        import activation_proof
        activation_proof.record("flow_promotion", "outcome", True, **result)
    except Exception: pass
    return result

if __name__ == "__main__": print(json.dumps(decision(), indent=2))
