#!/usr/bin/env python3
"""
digest.py - the daily executive digest. One message: portfolio health summary,
pending decisions/actions batched from the last 24h, shipped tasks, spend, and next moves.
Schedule for DIGEST_HOUR (default 07:00 UTC).
Sends via the v2 notify.sh (Slack + email) if present, else prints.
"""
import os, sys, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, health


def _portfolio_summary():
    """Return 3-line portfolio health summary."""
    s = health.summary()
    projects = s.get("projects", 0)
    avg_health = s.get("avg_health", 100)
    inbox_count = s.get("inbox_count", 0)
    needs = s.get("needs_attention", [])

    line1 = f"*Portfolio Health*: {avg_health}/100 across {projects} projects"
    line2 = f"Bottlenecks: {', '.join(n['project'] for n in needs[:2]) or 'none'}"
    line3 = f"Action items: {inbox_count} need your attention"
    return [line1, line2, line3]


def _build_pending_decisions():
    """Fetch unsent email notifications (batched decisions/actions from last 24h)."""
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).isoformat()
    pending = db.select("notifications", {
        "select": "id,title,body,approval_id,kind",
        "channel": "eq.email",
        "sent": "eq.false",
        "created_at": f"gte.{since}",
        "order": "created_at.desc"
    }) or []
    return pending


def _mark_sent(notification_ids):
    """Mark notifications as sent after they're included in digest."""
    for nid in notification_ids:
        db.update("notifications", {"id": nid}, {"sent": True})


def build():
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).isoformat()

    # Portfolio summary (3 lines)
    lines = _portfolio_summary()
    lines.append("")  # blank line

    # Pending decisions/actions batched from last 24h
    pending = _build_pending_decisions()
    if pending:
        lines.append("*Pending Decisions & Actions*")
        for p in pending[:10]:  # cap at 10 to avoid digest bloat
            card_title = p.get("title", "").replace("Decision: ", "").replace("Action: ", "")
            card_body = (p.get("body") or "")[:100]
            lines.append(f"  • {card_title}: {card_body}")
        if len(pending) > 10:
            lines.append(f"  ... and {len(pending) - 10} more decisions pending")
        lines.append("")

    # What shipped
    merged = db.select("tasks", {"select": "slug", "state": "eq.MERGED",
                                 "updated_at": f"gte.{since}"}) or []
    shipped = ", ".join(t["slug"] for t in merged) or "nothing merged"
    lines.append(f"*Shipped (24h)*: {shipped}")

    # Needs you
    inbox = health.inbox()
    needs = "; ".join(f"{i['label']}: {i['detail'][:60]}" for i in inbox[:5]) or "all clear"
    lines.append(f"*Needs you*: {needs}")

    # Spend
    spend = db.select("v_spend_mtd", {"select": "project,spent"}) or []
    spend_str = ", ".join(f"{r['project']} ${r['spent']}" for r in spend) or "$0"
    lines.append(f"*Spend MTD*: {spend_str}")

    # Proposed
    proposals = db.select("approvals", {"select": "title", "status": "eq.pending",
                                        "kind": "in.(self,proposal,efficiency)"}) or []
    proposed = "; ".join(p["title"] for p in proposals[:4]) or "none queued"
    lines.append(f"*Proposed next*: {proposed}")

    return "\n".join(lines), [p["id"] for p in pending]


def send():
    msg, notification_ids = build()
    here = os.path.dirname(os.path.abspath(__file__))
    notify = os.path.join(here, "..", "scripts", "notify.sh")
    if os.path.exists(notify):
        subprocess.run(["bash", notify, msg], check=False)
    else:
        print(msg)
    # Mark notifications as sent after digest is sent
    _mark_sent(notification_ids)


def should_run():
    """Check if we should run the digest based on DIGEST_HOUR (default 07)."""
    digest_hour = int(os.environ.get("DIGEST_HOUR", "07"))
    now = datetime.datetime.utcnow()
    return now.hour == digest_hour


if __name__ == "__main__":
    send()
