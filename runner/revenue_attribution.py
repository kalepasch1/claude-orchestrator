#!/usr/bin/env python3
"""
revenue_attribution.py - learn which WORK actually pays off. Snapshots each app's revenue/usage over
time, and for changes merged in a window, records the revenue delta that followed. Aggregated by task
KIND, this tells the governor/planner which kinds of work move the business, so the swarm biases toward
them (not just cheap merges).

  snapshot()   - append current app_revenue -> app_revenue_history (run daily).
  attribute()  - for recently MERGED tasks, link the app's before/after revenue delta -> merge_revenue.
  kind_roi()   - avg revenue_delta per task kind (fed into planning/prioritization).

Correlation, not causation — it's a directional signal, surfaced as guidance, not a hard gate.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW = int(os.environ.get("ATTR_WINDOW_DAYS", "7"))


def snapshot():
    n = 0
    for r in db.select("app_revenue", {"select": "*"}) or []:
        db.insert("app_revenue_history", {"app": r["app"], "mrr_usd": r.get("mrr_usd") or 0,
                                          "active_users": r.get("active_users") or 0})
        n += 1
    print(f"revenue_attribution: snapshotted {n} apps")
    return n


def _rev_at(app, days_ago):
    cut = (datetime.datetime.utcnow() - datetime.timedelta(days=days_ago)).isoformat()
    rows = db.select("app_revenue_history", {"select": "mrr_usd,active_users,captured_at",
                     "app": f"eq.{app}", "captured_at": f"lte.{cut}",
                     "order": "captured_at.desc", "limit": "1"}) or []
    return rows[0] if rows else None


def attribute():
    """Link merges from ~WINDOW days ago to the revenue change since."""
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=WINDOW)).isoformat()
    merged = db.select("outcomes", {"select": "project,slug,kind,created_at",
                                    "integrated": "eq.true", "created_at": f"gte.{since}",
                                    "limit": "500"}) or []
    already = {(m.get("project"), m.get("slug")) for m in
               (db.select("merge_revenue", {"select": "project,slug"}) or [])}
    linked = 0
    for m in merged:
        key = (m.get("project"), m.get("slug"))
        if key in already:
            continue
        before = _rev_at(m["project"], WINDOW)
        now = (db.select("app_revenue", {"select": "*", "app": f"eq.{m['project']}"}) or [None])[0]
        if not before or not now:
            continue
        delta = float(now.get("mrr_usd") or 0) - float(before.get("mrr_usd") or 0)
        db.insert("merge_revenue", {"project": m["project"], "slug": m["slug"], "kind": m.get("kind"),
                  "mrr_before": before.get("mrr_usd"), "mrr_after": now.get("mrr_usd"),
                  "users_before": before.get("active_users"), "users_after": now.get("active_users"),
                  "revenue_delta": round(delta, 2), "window_days": WINDOW})
        linked += 1
    print(f"revenue_attribution: linked {linked} merges to revenue movement")
    return linked


def kind_roi():
    rows = db.select("merge_revenue", {"select": "kind,revenue_delta"}) or []
    agg = {}
    for r in rows:
        a = agg.setdefault(r.get("kind") or "?", [0.0, 0]); a[0] += float(r.get("revenue_delta") or 0); a[1] += 1
    return {k: round(v[0] / v[1], 2) for k, v in agg.items() if v[1]}


def run():
    snapshot(); attribute()
    roi = kind_roi()
    if roi:
        print("revenue_attribution: $/merge by kind ->", roi)
    return roi


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
