#!/usr/bin/env python3
"""
roi.py - tie spend to outcomes. Computes cost-per-merged-task and a simple ROI ranking per
project from `outcomes`, so low-ROI work can be deprioritized automatically.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def report():
    rows = db.select("outcomes", {"select": "project,usd,integrated,tests_passed", "limit": "5000"}) or []
    agg = {}
    for r in rows:
        p = r.get("project") or "?"
        a = agg.setdefault(p, {"spend": 0.0, "merged": 0, "tasks": 0, "passed": 0})
        a["spend"] += float(r.get("usd") or 0); a["tasks"] += 1
        a["merged"] += 1 if r.get("integrated") else 0
        a["passed"] += 1 if r.get("tests_passed") else 0
    out = []
    for p, a in agg.items():
        cpm = a["spend"] / a["merged"] if a["merged"] else None
        out.append({"project": p, "spend": round(a["spend"], 2), "merged": a["merged"],
                    "tasks": a["tasks"], "pass_rate": round(a["passed"] / a["tasks"], 2) if a["tasks"] else 0,
                    "cost_per_merge": round(cpm, 2) if cpm else None})
    out.sort(key=lambda x: (x["cost_per_merge"] is None, x["cost_per_merge"] or 0))
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(report(), indent=2))
