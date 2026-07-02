#!/usr/bin/env python3
"""
approval_push.py - fan every decision you need to make out to wherever you want to manage it: email
(kalepasch@gmail.com) and Smarter (which reads the shared Supabase). For each NEW pending legal /
business-model / action card, it writes a row to `notifications` (the source of truth every surface
reads) and, if a direct channel is configured (notify.sh / RESEND_API_KEY), sends it immediately.

Dedup: one notification per approval id. The daily/hourly digest task drains unsent email rows and
mails them; Smarter reads v_pending_decisions live. So you can act from the cockpit, from email, or
from Smarter — same queue, single approval final. Schedule every few minutes.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

AUDIENCE = os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com")


def run(limit=50):
    # new decisions/actions not yet pushed
    already = {r.get("approval_id") for r in (db.select("notifications", {"select": "approval_id"}) or [])}
    cards = db.select("approvals", {"select": "id,kind,project,title,why,legal_risk_level",
                                    "status": "eq.pending",
                                    "kind": "in.(legal,material,secret,operator)",
                                    "order": "created_at.desc", "limit": str(limit)}) or []
    pushed = 0
    for a in cards:
        if a["id"] in already:
            continue
        is_decision = a["kind"] in ("legal", "material")
        kind = "decision" if is_decision else "action"
        # skip routine legal that legal_triage already auto-cleared/marked routine
        if a["kind"] == "legal" and (a.get("legal_risk_level") == "routine"):
            continue
        title = ("Decision: " if is_decision else "Action: ") + (a.get("title") or "")[:140]
        body = f"[{a.get('project') or '-'}] {(a.get('why') or '')[:240]}\nManage: cockpit, email reply, or Smarter."
        row = {"channel": "email", "audience": AUDIENCE, "kind": kind,
               "title": title[:180], "body": body[:600], "approval_id": a["id"], "sent": False}
        db.insert("notifications", row)
        # also mirror to Smarter channel (same content; Smarter reads v_pending_decisions live anyway)
        db.insert("notifications", {**row, "channel": "smarter"})
        # best-effort immediate ping
        try:
            import notify
            notify.send(f"{title}")
        except Exception:
            pass
        pushed += 1
    print(f"approval_push: pushed {pushed} new decisions/actions to {AUDIENCE} + Smarter")
    return pushed


if __name__ == "__main__":
    run()
