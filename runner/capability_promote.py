#!/usr/bin/env python3
"""
capability_promote.py - cross-app learning that spawns PRODUCTS. When a published capability has
proven itself in the real world (high eval_pass_rate across enough instances/apps), propose turning
it into a standalone product — with DATA ISOLATION preserved (we share the capability/pattern, never
customer data; instances already carry consent/residency via provenance).

Gate (all must hold):
  * latest version eval_pass_rate >= PROMOTE_PASS (default 0.85)
  * used in >= PROMOTE_MIN_APPS distinct apps (proven general, not a one-off)
  * not already proposed/scaffolded

Files a `capability_products` proposal (+ an approval card). Does NOT auto-build a company; a human
green-lights productization. Schedule daily/weekly.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PROMOTE_PASS = float(os.environ.get("PROMOTE_PASS", "0.85"))
PROMOTE_MIN_APPS = int(os.environ.get("PROMOTE_MIN_APPS", "2"))


def _latest_pass_rate(cap_id):
    v = db.select("capability_versions", {"select": "eval_pass_rate", "capability_id": f"eq.{cap_id}",
                                          "order": "created_at.desc", "limit": "1"}) or []
    return (v[0].get("eval_pass_rate") if v else None)


def _distinct_apps(cap_id):
    inst = db.select("capability_instances", {"select": "project", "capability_id": f"eq.{cap_id}"}) or []
    return len({i.get("project") for i in inst if i.get("project")})


def candidates():
    caps = db.select("capabilities", {"select": "id,slug,name,domain,summary,status"}) or []
    already = {r["capability_slug"] for r in (db.select("capability_products", {"select": "capability_slug"}) or [])}
    out = []
    for c in caps:
        if c.get("status") == "retired" or c["slug"] in already:
            continue
        rate = _latest_pass_rate(c["id"])
        apps = _distinct_apps(c["id"])
        if rate is not None and float(rate) >= PROMOTE_PASS and apps >= PROMOTE_MIN_APPS:
            out.append({"slug": c["slug"], "name": c.get("name"), "domain": c.get("domain"),
                        "pass_rate": float(rate), "apps": apps, "summary": c.get("summary")})
    return out


def run(apply=True):
    made = 0
    for c in candidates():
        if apply:
            db.insert("capability_products", {
                "capability_slug": c["slug"], "status": "proposed", "eval_pass_rate": c["pass_rate"],
                "rationale": f"{c['pass_rate']*100:.0f}% real-world pass across {c['apps']} apps — proven general."})
            db.insert("approvals", {"project": "PORTFOLIO", "kind": "material",
                "title": f"Productize capability '{c['name'] or c['slug']}'",
                "why": f"{c['pass_rate']*100:.0f}% pass across {c['apps']} apps. Domain: {c.get('domain')}.",
                "value": "Spin the proven capability into a standalone product (data isolation preserved).",
                "risk": "Human go/no-go on productization; nothing auto-built.", "command": ""})
        made += 1
        print(f"capability_promote: proposed '{c['slug']}' ({c['pass_rate']*100:.0f}%, {c['apps']} apps)")
    if not made:
        print("capability_promote: no capabilities meet the promotion bar yet")
    return made


if __name__ == "__main__":
    run(apply=(len(sys.argv) < 2))
