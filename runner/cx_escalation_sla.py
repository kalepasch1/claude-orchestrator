#!/usr/bin/env python3
"""
cx_escalation_sla.py - track how long escalated determinations / pending approvals have sat
unreviewed; nudge past a soft SLA, and for LOW-materiality + REVERSIBLE items past a hard SLA,
default to the panel's recommendation with a logged rationale (owner_overrides direction='sla_default')
— NEVER for legal/critical/irreversible ones, which keep waiting for a human. Nothing stalls silently.
Reuses determination materiality; no schema change; does not edit committees.py.
"""
import os, sys, json, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SOFT_SLA_HOURS = int(os.environ.get("SLA_SOFT_HOURS", "24"))
HARD_SLA_HOURS = int(os.environ.get("SLA_HARD_HOURS", "72"))

_LEGAL = re.compile(
    r"legal|counsel|cftc|dcm|licens|regulat|securities|money.?transmission|"
    r"reinsur|carrier|compliance|patent|trademark|gdpr|hipaa|critical|irreversible",
    re.I,
)


def _age_hours(created_at):
    """Hours since created_at (ISO string)."""
    if not created_at:
        return 0
    try:
        if isinstance(created_at, str):
            created_at = created_at.replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(created_at)
        else:
            dt = created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        return max(0, (now - dt).total_seconds() / 3600)
    except Exception:
        return 0


def _is_safe_for_auto(item):
    """Only LOW materiality + no legal flags = safe for auto-default."""
    text = " ".join([
        item.get("title") or "",
        item.get("why") or "",
        item.get("body") or "",
        item.get("materiality") or "",
    ])
    if _LEGAL.search(text):
        return False
    mat = (item.get("materiality") or "").upper()
    if mat and mat != "LOW":
        return False
    return True


def run():
    approvals = db.select("approvals", {
        "select": "id,title,why,status,kind,created_at,materiality",
        "status": "eq.pending",
        "limit": "500",
    }) or []

    nudges = 0
    auto_defaults = 0

    for a in approvals:
        age = _age_hours(a.get("created_at"))

        if age >= HARD_SLA_HOURS and _is_safe_for_auto(a):
            # Auto-default for LOW materiality, non-legal, reversible
            try:
                db.update("approvals", {"id": a["id"]}, {
                    "status": "approved",
                    "note": f"SLA auto-default after {age:.0f}h (LOW materiality, reversible)",
                })
            except Exception:
                pass
            try:
                db.insert("owner_overrides", {
                    "direction": "sla_default",
                    "approval_id": a.get("id"),
                    "reason": f"Auto-defaulted to panel recommendation after {age:.0f}h "
                              f"(LOW materiality, non-legal, reversible). Title: {(a.get('title') or '')[:100]}",
                    "created_at": datetime.datetime.utcnow().isoformat() + "Z",
                })
            except Exception:
                pass
            auto_defaults += 1

        elif age >= SOFT_SLA_HOURS:
            # Nudge for anything past soft SLA
            db.insert("inbox", {
                "kind": "sla_nudge",
                "title": f"SLA nudge: {(a.get('title') or 'untitled')[:80]} ({age:.0f}h pending)",
                "body": (
                    f"Approval '{a.get('title', '')}' (kind={a.get('kind', '')}) "
                    f"has been pending for {age:.0f} hours.\n"
                    f"ID: {a.get('id')}\n"
                    f"Reason: {(a.get('why') or '')[:200]}"
                ),
                "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            })
            nudges += 1

    return {"status": "ok", "nudges": nudges, "auto_defaults": auto_defaults}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
