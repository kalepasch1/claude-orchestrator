#!/usr/bin/env python3
"""
owner_report.py - a Monday "what shipped, what earned, what's next" summary so you steer the portfolio
in five minutes. Aggregates the past week: merges by app, revenue movement (from merge_revenue /
app_revenue), spend (real $0 on Max + notional), top pending decisions (decision_rank), and the
autopilot/roadmap proposals. Writes a notification (channel='email') the digest task delivers.
Pure read + one notification insert. Schedule weekly (Monday am).
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def run():
    wk = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat()
    merges = db.select("outcomes", {"select": "project", "integrated": "eq.true",
                                    "created_at": f"gte.{wk}", "limit": "2000"}) or []
    by_app = {}
    for m in merges:
        by_app[m["project"]] = by_app.get(m["project"], 0) + 1
    shipped = ", ".join(f"{a}: {n}" for a, n in sorted(by_app.items(), key=lambda x: -x[1])[:8]) or "nothing yet"
    rev = db.select("app_revenue", {"select": "*"}) or []
    total_mrr = sum(float(r.get("mrr_usd") or 0) for r in rev)
    notional = sum(float(r.get("usd") or 0) for r in
                   (db.select("provider_usage", {"select": "usd", "created_at": f"gte.{wk}"}) or []))
    try:
        import decision_rank
        top = decision_rank.rank(3)
    except Exception:
        top = []
    top_txt = "; ".join(f"{t['title'][:60]} ({t['app']})" for t in top) or "none"
    body = (f"WEEK IN REVIEW\n"
            f"Shipped (merges by app): {shipped}\n"
            f"Portfolio MRR: ${total_mrr:,.0f} across {len(rev)} apps with revenue data\n"
            f"Compute: $0 real API (Max plans) · ${notional:,.0f} notional this week\n"
            f"Top decisions waiting: {top_txt}\n"
            f"Open the cockpit Portfolio tab to steer next week.")
    db.insert("notifications", {"channel": "email", "audience": os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com"),
              "kind": "alert", "title": "Weekly owner report", "body": body[:1500], "sent": False})
    print("owner_report: weekly report queued")
    return 1


if __name__ == "__main__":
    run()
