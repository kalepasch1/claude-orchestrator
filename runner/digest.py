#!/usr/bin/env python3
"""
digest.py - the daily executive digest. One message: what shipped, what's blocked,
what needs you, spend, and the swarm's proposed next moves. Schedule for ~7am.
Sends via the v2 notify.sh (Slack + email) if present, else prints.
"""
import os, sys, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, health


def build():
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).isoformat()
    merged = db.select("tasks", {"select": "slug", "state": "eq.MERGED",
                                 "updated_at": f"gte.{since}"}) or []
    s = health.summary()
    inbox = health.inbox()
    spend = db.select("v_spend_mtd", {"select": "project,spent"}) or []
    proposals = db.select("approvals", {"select": "title", "status": "eq.pending",
                                        "kind": "in.(self,proposal,efficiency)"}) or []
    shipped = ", ".join(t["slug"] for t in merged) or "nothing merged"
    needs = "; ".join(f"{i['label']}: {i['detail'][:60]}" for i in inbox[:5]) or "all clear"
    spend_str = ", ".join(f"{r['project']} ${r['spent']}" for r in spend) or "$0"
    proposed = "; ".join(p["title"] for p in proposals[:4]) or "none queued"
    lines = ["*Claude Orchestrator — daily digest*",
             f"Avg health {s['avg_health']}/100 across {s['projects']} projects · {s['inbox_count']} items need you",
             f"Shipped (24h): {shipped}",
             f"Needs you: {needs}",
             f"Spend MTD: {spend_str}",
             f"Proposed next: {proposed}"]
    return "\n".join(lines)


def send():
    msg = build()
    here = os.path.dirname(os.path.abspath(__file__))
    notify = os.path.join(here, "..", "scripts", "notify.sh")
    if os.path.exists(notify):
        subprocess.run(["bash", notify, msg], check=False)
    else:
        print(msg)


if __name__ == "__main__":
    send()
