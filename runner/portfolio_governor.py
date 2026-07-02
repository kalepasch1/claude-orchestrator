#!/usr/bin/env python3
"""
portfolio_governor.py - allocate the whole fleet's compute across apps by EXPECTED VALUE, so the
swarm chases ROI instead of just draining a FIFO queue. Generalizes roi.py (which only looked at
cost-per-merge) into a single score per project:

    EV = value_weight * success_prob / (cost_per_merge + eps)

  value_weight : goals/demand signal (defaults 1; higher for prioritized apps)
  success_prob : recent integrate rate (how often work actually merges)
  cost_per_merge : recent $ per merged change (from outcomes; subscription work ~0 -> cheap)

The EV is normalized across the portfolio and mapped to projects.concurrency_weight (1-3), which the
economic scheduler (db.claim_task) already uses to order claims. Result: high-EV apps get more of the
fleet's parallel slots automatically. Bounded + reversible; logs every change. Schedule ~hourly.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW = int(os.environ.get("GOV_WINDOW", "300"))
EPS = 0.25


def _project_stats(name):
    rows = db.select("outcomes", {"select": "integrated,usd",
                                  "project": f"eq.{name}", "order": "created_at.desc",
                                  "limit": str(WINDOW)}) or []
    if not rows:
        return None
    n = len(rows)
    merges = sum(1 for r in rows if r.get("integrated"))
    spend = sum(float(r.get("usd") or 0) for r in rows)
    success = merges / n
    cpm = (spend / merges) if merges else (spend if spend else EPS)
    return {"n": n, "success": round(success, 3), "cost_per_merge": round(cpm, 4)}


def _value_weight(name):
    """Business-impact signal. Prefers REAL revenue/usage (app_revenue) so the fleet weights work by
    actual business value, not just merge economics. Falls back to goals weight, else 1.0."""
    # revenue-linked: log-scaled MRR + a nudge for active users, plus any manual override
    try:
        r = db.select("app_revenue", {"select": "*", "app": f"eq.{name}", "limit": "1"}) or []
        if r:
            row = r[0]
            if row.get("weight_override") is not None:
                return float(row["weight_override"])
            import math
            mrr = float(row.get("mrr_usd") or 0)
            users = float(row.get("active_users") or 0)
            if mrr > 0 or users > 0:
                return round(1.0 + math.log10(1 + mrr) + 0.3 * math.log10(1 + users), 3)
    except Exception:
        pass
    try:
        g = db.select("goals", {"select": "weight", "project": f"eq.{name}", "limit": "1"}) or []
        if g and g[0].get("weight") is not None:
            return float(g[0]["weight"])
    except Exception:
        pass
    return 1.0


def _behind_merge_slo(name):
    """True if the app has a merges/day target and is pacing below it today (throughput SLO)."""
    import datetime
    slo = db.select("cost_slos", {"select": "target_merges_per_day", "app": f"eq.{name}"}) or []
    target = slo[0].get("target_merges_per_day") if slo else None
    if not target:
        return False
    today = datetime.date.today().isoformat()
    rows = db.select("outcomes", {"select": "id", "project": f"eq.{name}",
                                  "integrated": "eq.true", "created_at": f"gte.{today}"}) or []
    frac = max(0.25, (datetime.datetime.utcnow().hour + 1) / 24.0)
    return len(rows) < float(target) * frac  # behind the pro-rated pace


def plan():
    projs = db.select("projects", {"select": "id,name,concurrency_weight,auto_merge"}) or []
    scored = []
    for p in projs:
        st = _project_stats(p["name"])
        if not st or st["n"] < 10:
            continue
        ev = _value_weight(p["name"]) * (st["success"] + 0.05) / (st["cost_per_merge"] + EPS)
        scored.append({"id": p["id"], "name": p["name"], "ev": ev, "stats": st,
                       "cur_weight": p.get("concurrency_weight") or 1})
    if not scored:
        return []
    evs = sorted(s["ev"] for s in scored)
    # map EV to weight 1-3 by tercile
    lo, hi = evs[len(evs)//3], evs[2*len(evs)//3]
    for s in scored:
        w = 3 if s["ev"] >= hi else (2 if s["ev"] >= lo else 1)
        # merge-rate SLO: an app behind its throughput commitment gets a capacity bump
        if _behind_merge_slo(s["name"]):
            w = min(3, w + 1)
            s["slo_boost"] = True
        s["new_weight"] = w
    return scored


def run(apply=True):
    scored = plan()
    changed = 0
    for s in sorted(scored, key=lambda x: x["ev"], reverse=True):
        if s["new_weight"] != s["cur_weight"]:
            if apply:
                db.update("projects", {"id": s["id"]}, {"concurrency_weight": s["new_weight"]})
            changed += 1
        print(f"governor: {s['name']:22s} EV={s['ev']:.3f} success={s['stats']['success']} "
              f"cpm=${s['stats']['cost_per_merge']} weight {s['cur_weight']}->{s['new_weight']}")
    if not scored:
        print("governor: not enough outcome signal yet")
    return changed


if __name__ == "__main__":
    import json
    print(json.dumps(plan(), indent=2, default=str))
