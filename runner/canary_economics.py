#!/usr/bin/env python3
"""
canary_economics.py - make canary promote/rollback decisions on PRODUCTION cost + quality, not just
pre-merge signals. After a change canaries, this checks the live app's operation economics
(app_operations: cost/quality per operation during the canary window) and the app's error signal:

  promote  if  quality >= QUALITY_MIN  AND  cost within the app's $/merge (cost_slo) budget  AND
               no error/regression spike during the canary window.
  rollback if  quality drops OR cost spikes beyond the SLO hard ceiling OR errors spike.

Returns a decision; the deploy pipeline (deploy_window / canary) calls this before flipping traffic.
Read-only on infra; it only recommends + files an approval on rollback. Schedule alongside deploys.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

QUALITY_MIN = float(os.environ.get("CANARY_QUALITY_MIN", "7.0"))
WINDOW_MIN = int(os.environ.get("CANARY_WINDOW_MIN", "30"))


def _canary_ops(app, minutes):
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)).isoformat()
    return db.select("app_operations", {"select": "quality_score,cost_usd,ok",
                                        "app": f"eq.{app}", "created_at": f"gte.{cutoff}"}) or []


def _slo(app):
    r = db.select("cost_slos", {"select": "*", "app": f"eq.{app}"}) or []
    return r[0] if r else {"target_usd_per_merge": 1.0, "hard_ceiling_usd_per_merge": None}


def decide(app):
    ops = _canary_ops(app, WINDOW_MIN)
    if not ops:
        return {"app": app, "decision": "hold", "why": "no canary telemetry yet"}
    q = [float(o["quality_score"]) for o in ops if o.get("quality_score") is not None]
    quality = sum(q) / len(q) if q else None
    cost = sum(float(o.get("cost_usd") or 0) for o in ops)
    errors = sum(1 for o in ops if o.get("ok") is False)
    slo = _slo(app)
    ceiling = slo.get("hard_ceiling_usd_per_merge")

    if quality is not None and quality < QUALITY_MIN:
        return {"app": app, "decision": "rollback", "why": f"canary quality {quality:.1f} < {QUALITY_MIN}"}
    if errors > max(1, len(ops) // 10):
        return {"app": app, "decision": "rollback", "why": f"error spike {errors}/{len(ops)} during canary"}
    if ceiling and cost > float(ceiling):
        return {"app": app, "decision": "rollback", "why": f"canary cost ${cost:.2f} > ceiling ${ceiling}"}
    return {"app": app, "decision": "promote",
            "why": f"quality {quality if quality is None else round(quality,1)}, cost ${cost:.2f}, errors {errors}"}


def run():
    out = []
    for p in db.select("projects", {"select": "name"}) or []:
        d = decide(p["name"])
        out.append(d)
        if d["decision"] == "rollback":
            db.insert("approvals", {"project": p["name"], "kind": "material",
                "title": f"Canary ROLLBACK recommended: {p['name']}",
                "why": d["why"], "value": "Protect production cost/quality.",
                "risk": "Promoting this canary would degrade the app.", "command": ""})
        print(f"canary_economics: {p['name']} -> {d['decision']} ({d['why']})")
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
