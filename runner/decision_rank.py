#!/usr/bin/env python3
"""
decision_rank.py - rank pending decisions/actions by how much they matter, so the digest leads with the
one or two that count and collapses the rest. Score blends: legal exposure (novel > elevated > routine),
business-model radar (regulatory/pricing/data), and the app's revenue (bigger app = higher stakes).

rank(limit) -> [{id, app, kind, title, score, why_rank}]  (desc). Pure read; used by approval_push +
the digest task. No model calls.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

LEGAL_W = {"novel": 40, "elevated": 20, "routine": 5, None: 15}
RADAR_W = {"regulatory": 30, "pricing": 18, "data_use": 20, None: 0}
KIND_W = {"legal": 25, "material": 12, "secret": 8, "operator": 6}


def rank(limit=200):
    mrr = {r["app"]: float(r.get("mrr_usd") or 0) for r in (db.select("app_revenue", {"select": "*"}) or [])}
    import math
    rows = db.select("approvals", {"select": "id,kind,project,title,legal_risk_level,radar_tag",
                                   "status": "eq.pending",
                                   "kind": "in.(legal,material,secret,operator)",
                                   "limit": str(limit)}) or []
    out = []
    for a in rows:
        score = (KIND_W.get(a.get("kind"), 5)
                 + (LEGAL_W.get(a.get("legal_risk_level"), 15) if a.get("kind") == "legal" else 0)
                 + RADAR_W.get(a.get("radar_tag"), 0)
                 + 6 * math.log10(1 + mrr.get(a.get("project"), 0)))
        why = []
        if a.get("kind") == "legal":
            why.append(f"legal:{a.get('legal_risk_level') or 'unclassified'}")
        if a.get("radar_tag"):
            why.append(f"business:{a['radar_tag']}")
        if mrr.get(a.get("project"), 0) > 0:
            why.append(f"MRR ${mrr[a['project']]:.0f}")
        out.append({"id": a["id"], "app": a.get("project"), "kind": a.get("kind"),
                    "title": a.get("title"), "score": round(score, 1), "why_rank": ", ".join(why) or a.get("kind")})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


if __name__ == "__main__":
    import json
    print(json.dumps(rank(10), indent=2, default=str))
