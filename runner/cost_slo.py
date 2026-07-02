#!/usr/bin/env python3
"""
cost_slo.py - closed-loop cost SLOs. You set a target $/merge per app; this loop measures actual
$/merge and drives the knobs to hold it, escalating to you only on a hard breach:

  actual > target  -> tighten economics: prefer cheaper model tier (lower per-project OPUS use via a
                      cost_bias flag) and, on hard-ceiling breach, file an approval / optionally pause.
  actual <= target -> healthy: leave as-is (self_tune may loosen autonomy elsewhere).

Reads outcomes for actual $/merge; writes a per-project `cost_bias` (0=normal,1=cheap,2=cheapest)
that model_router/model_policy can honor to bias toward cheaper tiers. Bounded + logged. ~hourly.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW = int(os.environ.get("SLO_WINDOW", "300"))
DEFAULT_TARGET = float(os.environ.get("SLO_DEFAULT_TARGET", "1.0"))


def _actual_cpm(name):
    rows = db.select("outcomes", {"select": "integrated,usd", "project": f"eq.{name}",
                                  "order": "created_at.desc", "limit": str(WINDOW)}) or []
    if not rows:
        return None
    merges = sum(1 for r in rows if r.get("integrated"))
    spend = sum(float(r.get("usd") or 0) for r in rows)
    if merges == 0:
        return {"cpm": None, "spend": round(spend, 2), "merges": 0}
    return {"cpm": round(spend / merges, 4), "spend": round(spend, 2), "merges": merges}


def _slo(name):
    rows = db.select("cost_slos", {"select": "*", "app": f"eq.{name}"}) or []
    if rows:
        return rows[0]
    return {"app": name, "target_usd_per_merge": DEFAULT_TARGET, "hard_ceiling_usd_per_merge": None}


def run(apply=True):
    projs = db.select("projects", {"select": "id,name,cost_bias"}) or []
    actions = []
    for p in projs:
        a = _actual_cpm(p["name"])
        if not a:
            continue
        slo = _slo(p["name"])
        target = float(slo.get("target_usd_per_merge") or DEFAULT_TARGET)
        ceiling = slo.get("hard_ceiling_usd_per_merge")
        cur_bias = int(p.get("cost_bias") or 0)
        # subscription work is ~$0 -> cpm None/0 means healthy
        cpm = a["cpm"]
        if cpm is None:
            # spending but not merging -> economic waste; bias cheaper
            new_bias = min(2, cur_bias + 1) if a["spend"] > target else cur_bias
            reason = f"spend ${a['spend']} with 0 merges"
        elif cpm > target:
            new_bias = min(2, cur_bias + 1)
            reason = f"$/merge ${cpm} > target ${target}"
        else:
            new_bias = max(0, cur_bias - 1)  # comfortably under -> relax the cheap bias
            reason = f"$/merge ${cpm} <= target ${target}"
        if new_bias != cur_bias and apply:
            db.update("projects", {"id": p["id"]}, {"cost_bias": new_bias})
        if new_bias != cur_bias:
            actions.append({"app": p["name"], "bias": f"{cur_bias}->{new_bias}", "why": reason})
            print(f"cost_slo: {p['name']} bias {cur_bias}->{new_bias} ({reason})")
        # hard ceiling breach -> escalate
        if ceiling and cpm is not None and cpm > float(ceiling):
            db.insert("approvals", {"project": p["name"], "kind": "material",
                "title": f"COST SLO breach: {p['name']} ${cpm}/merge > ceiling ${ceiling}",
                "why": reason, "value": "Contain runaway cost on this app.",
                "risk": "Consider pausing or forcing cheapest tier until fixed.", "command": ""})
    if not actions:
        print("cost_slo: all apps within SLO (or insufficient signal)")
    return actions


if __name__ == "__main__":
    import json
    print(json.dumps(run(apply=(len(sys.argv) < 2)), indent=2, default=str))
