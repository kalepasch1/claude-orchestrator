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
import os, sys, time, hmac, hashlib, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

AUDIENCE = os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com")
LINK_TTL_S = int(os.environ.get("APPROVAL_LINK_TTL_S", str(7 * 24 * 3600)))   # links valid 7 days


def _sign(aid, action, opt=""):
    """Signed one-click decision link, verified by the approvals-api edge function.
    HMAC key = the service key (shared by runner + edge function only)."""
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    exp = str(int(time.time()) + LINK_TTL_S)
    sig = hmac.new(key.encode(), f"{aid}|{action}|{opt}|{exp}".encode(), hashlib.sha256).hexdigest()
    q = f"id={aid}&action={action}&exp={exp}&sig={sig}" + (f"&opt={opt}" if opt != "" else "")
    return f"{base}/functions/v1/approvals-api?{q}"


def _links_block(a):
    """Plain-text action links: flexible options (from alternatives) + approve/deny/defer."""
    lines = []
    alts = a.get("alternatives") or []
    if isinstance(alts, str):
        try:
            alts = json.loads(alts)
        except Exception:
            alts = []
    for i, alt in enumerate(alts[:4]):
        label = alt if isinstance(alt, str) else (alt.get("label") or alt.get("title") or f"option {i+1}")
        lines.append(f"  OPTION {i+1} — {str(label)[:90]}:\n    {_sign(a['id'], 'option', str(i))}")
    lines.append(f"  APPROVE as proposed:\n    {_sign(a['id'], 'approve')}")
    lines.append(f"  DENY:\n    {_sign(a['id'], 'deny')}")
    lines.append(f"  DEFER / request fuller brief:\n    {_sign(a['id'], 'defer')}")
    return "\n".join(lines)


def run(limit=50):
    # new decisions/actions not yet pushed
    already = {r.get("approval_id") for r in (db.select("notifications", {"select": "approval_id"}) or [])}
    cards = db.select("approvals", {"select": "id,kind,project,title,why,value,risk,alternatives,prebrief,legal_risk_level,radar_tag,detail",
                                    "status": "eq.pending",
                                    "kind": "in.(legal,material,secret,operator)",
                                    "order": "created_at.desc", "limit": str(limit)}) or []
    import approval_policy
    pushed = 0
    for a in cards:
        if a["id"] in already:
            continue
        # OWNER POLICY: only narrow legal-structuring questions email immediately;
        # approval_policy.sweep() auto-approves the rest (they land in the daily digest).
        if not approval_policy.is_legal_gated(a):
            continue
        is_decision = a["kind"] in ("legal", "material")
        kind = "decision" if is_decision else "action"
        # skip routine legal that legal_triage already auto-cleared/marked routine
        if a["kind"] == "legal" and (a.get("legal_risk_level") == "routine"):
            continue
        title = ("Decision: " if is_decision else "Action: ") + (a.get("title") or "")[:140]
        parts = [f"[{a.get('project') or '-'}] {a.get('title') or ''}"]
        for k, hdr in (("why", "WHY"), ("value", "VALUE"), ("risk", "RISK"), ("prebrief", "BRIEF")):
            if a.get(k):
                parts.append(f"{hdr}: {str(a[k])[:700]}")
        parts.append("DECIDE (one click):\n" + _links_block(a))
        parts.append("Or manage in the cockpit / Smarter — same queue, first decision wins.")
        body = "\n\n".join(parts)
        row = {"channel": "email", "audience": AUDIENCE, "kind": kind,
               "title": title[:180], "body": body[:4000], "approval_id": a["id"], "sent": False}
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
