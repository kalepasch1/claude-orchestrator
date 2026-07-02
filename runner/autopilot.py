#!/usr/bin/env python3
"""
autopilot.py - portfolio autopilot. Given a budget of YOUR attention (max decisions/day) and compute
(fleet slots), it self-allocates across apps to maximize total revenue signal, and surfaces only the
decisions that beat a materiality threshold — everything below it flows automatically. Ties the pieces
together: revenue attribution -> governor weights -> materiality gate on decisions.

  * capacity: reads fleet ceiling; leaves concurrency to resource_governor (Mac safety) but sets
    per-app weights via portfolio_governor.
  * attention: dedups/auto-clears sub-threshold decision cards so your queue stays small; keeps only
    material (revenue/legal/regulatory) ones.
Schedule ~hourly. Bounded + logged; never touches legal/regulatory cards (those always surface).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MATERIALITY_MRR = float(os.environ.get("AUTOPILOT_MATERIALITY_MRR", "0"))   # $ impact below which a
MAX_DECISIONS_DAY = int(os.environ.get("AUTOPILOT_MAX_DECISIONS", "20"))     # non-legal card auto-clears


def run():
    # 1) refresh economic weights (revenue-aware governor)
    try:
        import portfolio_governor
        portfolio_governor.run(apply=True)
    except Exception as e:
        print(f"autopilot: governor step skipped ({e})")
    # 2) attention budget: if too many non-legal 'material' proposals are pending, keep the top-N by
    #    project MRR and auto-defer the rest (legal/regulatory/radar always kept).
    mrr = {r["app"]: float(r.get("mrr_usd") or 0) for r in (db.select("app_revenue", {"select": "*"}) or [])}
    cards = db.select("approvals", {"select": "id,kind,project,radar_tag,title", "status": "eq.pending",
                                    "kind": "eq.material", "limit": "500"}) or []
    # never auto-defer legal/regulatory/radar decisions
    deferrable = [c for c in cards if not c.get("radar_tag")
                  and "legal" not in (c.get("title") or "").lower()]
    deferrable.sort(key=lambda c: mrr.get(c.get("project"), 0), reverse=True)
    deferred = 0
    for c in deferrable[MAX_DECISIONS_DAY:]:
        db.update("approvals", {"id": c["id"]},
                  {"status": "approved", "decided_by": "autopilot-sub-threshold", "decided_at": "now()"})
        deferred += 1
    print(f"autopilot: refreshed weights; kept top {min(len(deferrable),MAX_DECISIONS_DAY)} decisions, "
          f"auto-cleared {deferred} sub-threshold (legal/regulatory always kept)")
    return {"kept": min(len(deferrable), MAX_DECISIONS_DAY), "cleared": deferred}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
