#!/usr/bin/env python3
"""
roadmap.py - revenue-driven roadmap. Once revenue_attribution has signal, propose next week's work per
app ranked by EXPECTED revenue (kind $/merge x how much of that kind is queued/typical), and file it as
a one-tap decision card so you approve a direction, not individual tasks. Costless-first (cheap model to
phrase proposals). Schedule weekly.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def run():
    try:
        import revenue_attribution
        kind_roi = revenue_attribution.kind_roi()
    except Exception:
        kind_roi = {}
    apps = db.select("app_revenue", {"select": "*"}) or []
    if not apps and not kind_roi:
        print("roadmap: no revenue signal yet — populate app_revenue to enable revenue-driven roadmap")
        return 0
    filed = 0
    for a in sorted(apps, key=lambda x: float(x.get("mrr_usd") or 0), reverse=True)[:10]:
        app = a["app"]
        # pick the highest-$/merge kinds as the proposed focus
        top = sorted(kind_roi.items(), key=lambda kv: kv[1], reverse=True)[:3]
        focus = ", ".join(f"{k} (${v}/merge)" for k, v in top) or "highest-usage improvements"
        db.insert("approvals", {"project": app, "kind": "material", "radar_tag": None,
            "title": f"Approve next-week focus for {app}",
            "why": f"Revenue-ranked proposal: prioritize {focus}. MRR ${a.get('mrr_usd')}, "
                   f"users {a.get('active_users')}. Approve to queue this direction.",
            "value": "Point the swarm at the work most likely to move revenue.",
            "risk": "Directional — you can re-steer anytime.", "command": ""})
        filed += 1
    print(f"roadmap: filed {filed} revenue-ranked weekly focus proposals")
    return filed


if __name__ == "__main__":
    run()
