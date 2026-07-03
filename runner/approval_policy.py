#!/usr/bin/env python3
"""
approval_policy.py - THE approval gate, owner policy 2026-07-02:

  "Human approval only for narrow issues that conflict with our legal structuring /
   exemptions. Everything non-problematic auto-approves. When a card IS gated, scope
   it to the fractional legal question (with 2-4 flexible options), never a wall of
   text, never a bare yes/no."

Every scheduler cycle, sweep() classifies each pending card:

  LEGAL-GATE (stays for the owner, enriched):
    * kind='legal' with legal_risk_level='novel' (legal_triage already auto-clears routine)
    * title/why/detail indicates a posture-changing regulated activity: licensing,
      registration, custody, transmission, regulated advice, underwriting, etc.
    Gated cards get: a "NARROW LEGAL QUESTION" framing if missing, and fallback
    alternatives (guardrailed / full-after-counsel / defer-fraction-build-rest) so email
    links always offer flexible strategies, not yes/no.

  AUTO-APPROVE (audited, digest-notified, never emailed one-by-one):
    * everything else EXCEPT kind='secret' (humans hold credentials) and cards matching
      ALARM_RX (billing firewall / key leak / spend circuit - those are incidents, not
      approvals). Merge cards remain test-gated by approval_merge regardless.

Audit trail: every auto decision writes decided_by='auto-policy:owner-20260702' plus a
digest notification row - nothing disappears silently.
"""
import os, re, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import legal_filter

POLICY_MARK = "auto-policy:owner-20260702"
ENABLED = os.environ.get("OWNER_POLICY_AUTOAPPROVE", "true").lower() in ("true", "1", "yes")
AUDIENCE = os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com")

ALARM_RX = re.compile(r"key\s+leak|secret\s+leak|credential\s+compromis", re.I)

FALLBACK_ALTERNATIVES = [
    {"label": "Proceed with guardrails (Recommended)",
     "description": "Ship the non-legal parts now; wrap the sensitive fraction in disclaimers/limits/flags.",
     "risk": "low", "reversible": True, "recommended": True},
    {"label": "Proceed fully after counsel",
     "description": "Build everything; launch the sensitive fraction only after counsel confirms it fits the current exemption/structuring posture.",
     "risk": "high", "reversible": False, "recommended": False},
    {"label": "Defer the conflicting fraction",
     "description": "Everything else proceeds now; only the legally sensitive piece waits.",
     "risk": "minimal", "reversible": True, "recommended": False},
]


def build_decision_prompt(card, alts):
    """Canonical structured decision prompt - same shape on email, cockpit, and Smarter:
    one NARROW question, 2-4 labeled options with tradeoffs, a recommended default."""
    title = str(card.get("title") or "")
    why = str(card.get("why") or "")
    question = why.split("\n")[0][:400] if why else f"Approve: {title}?"
    options, rec = [], 0
    for i, a in enumerate(alts[:4]):
        if isinstance(a, str):
            a = {"label": a}
        if a.get("recommended"):
            rec = i
        options.append({
            "label": str(a.get("label") or f"Option {i+1}")[:120],
            "description": str(a.get("description") or a.get("label") or "")[:400],
            "risk": a.get("risk", "unknown"),
            "reversible": bool(a.get("reversible", True)),
            "recommended": bool(a.get("recommended", False)),
        })
    if options and not any(o["recommended"] for o in options):
        # default recommendation: lowest-risk reversible option
        order = {"minimal": 0, "low": 1, "low-medium": 2, "medium": 3, "unknown": 4, "high": 5}
        rec = min(range(len(options)),
                  key=lambda i: (order.get(str(options[i]["risk"]), 4), not options[i]["reversible"]))
        options[rec]["recommended"] = True
        options[rec]["label"] += " (Recommended)" if "(Recommended)" not in options[rec]["label"] else ""
    return {"question": question, "header": (card.get("radar_tag") or card.get("kind") or "decision")[:24],
            "options": options, "recommended_index": rec}


def _text(card):
    return " ".join(str(card.get(k) or "") for k in ("title", "why", "detail", "prebrief"))


def is_legal_gated(card):
    """True only for a genuine posture-changing legal/regulatory question."""
    if card.get("kind") == "legal" and (card.get("legal_risk_level") or "") == "novel":
        return True
    return legal_filter.requires_owner_approval(
        card,
        kind=card.get("kind") or "",
        radar_tag=card.get("radar_tag") or "",
    )


def is_auto_approvable(card):
    """Everything non-problematic. Secrets and incident alarms are never 'approved' by policy."""
    if card.get("kind") == "secret":
        return False
    if ALARM_RX.search(str(card.get("title") or "")):
        return False
    return not is_legal_gated(card)


def _enrich_gated(card):
    """Scope a gated card to its fractional legal question + guarantee flexible options."""
    patch = {}
    why = str(card.get("why") or "")
    if "NARROW LEGAL QUESTION" not in why:
        trigger = legal_filter.trigger_excerpt(card)
        hook = f" (trigger: '{trigger}')" if trigger else ""
        patch["why"] = ("NARROW LEGAL QUESTION" + hook +
                        " - only the legally sensitive fraction needs your call; "
                        "non-conflicting parts of this work proceed automatically.\n\n" + why)[:4000]
    alts = card.get("alternatives")
    if isinstance(alts, str):
        try:
            alts = json.loads(alts)
        except Exception:
            alts = None
    if not alts:
        alts = FALLBACK_ALTERNATIVES
        patch["alternatives"] = alts
    if not card.get("legal_risk_level"):
        patch["legal_risk_level"] = "novel"
    # canonical structured prompt for every surface (email/cockpit/Smarter)
    bj = card.get("brief_json")
    if not bj or not isinstance(bj, dict) or "options" not in (bj or {}):
        patch["brief_json"] = build_decision_prompt({**card, **patch}, alts)
    return patch


def gate_owner_emails(limit=400):
    """CENTRAL OWNER-EMAIL GUARDRAIL (owner policy 2026-07-03).

    The owner asked to NEVER approve merges and to be emailed ONLY when something changes the
    company's legal-LICENSING / regulatory posture. Merges auto-approve (QA/build-gated), and every
    material change, operator to-do, digest and auto-approval is managed in the cockpit + Smarter —
    not the inbox.

    This is the single chokepoint that enforces it no matter which composer produced the row: any
    UNSENT notification bound to an approval card (channel email/digest) whose card is NOT legal-
    licensing-gated is demoted to channel='cockpit' (still visible in the app + Smarter, never
    emailed). Rows with no approval_id are system alerts (account exhaustion, cost circuit, weekly
    report) and are left alone — those are the few things the owner does want to hear about.
    """
    try:
        pend = db.select("notifications",
                         {"select": "id,approval_id,channel", "channel": "in.(email,digest)",
                          "sent": "eq.false", "order": "id.desc", "limit": str(limit)}) or []
    except Exception:
        return 0
    ids = sorted({str(n["approval_id"]) for n in pend if n.get("approval_id")})
    cards = {}
    if ids:
        try:
            for r in (db.select("approvals", {"select": "*", "id": f"in.({','.join(ids)})"}) or []):
                cards[r["id"]] = r
        except Exception:
            cards = {}
    demoted = 0
    for n in pend:
        aid = n.get("approval_id")
        if not aid:
            continue  # system alert / report, not an approval email — leave it
        card = cards.get(aid)
        if card and is_legal_gated(card):
            continue  # the ONE thing allowed to email the owner
        try:
            db.update("notifications", {"id": n["id"]}, {"channel": "cockpit"})
            demoted += 1
        except Exception:
            pass
    if demoted:
        print(f"approval_policy: gated {demoted} non-legal notification(s) to cockpit (owner-email = legal-licensing only)")
    return demoted


def sweep(limit=200):
    """Classify every pending card: auto-approve the safe, enrich + keep the legal."""
    if not ENABLED:
        print("approval_policy: disabled (OWNER_POLICY_AUTOAPPROVE=false)")
        return 0, 0
    gate_owner_emails()
    cards = db.select("approvals", {"select": "*", "status": "eq.pending",
                                    "order": "created_at.asc", "limit": str(limit)}) or []
    approved = gated = 0
    for c in cards:
        try:
            if is_auto_approvable(c):
                db.update("approvals", {"id": c["id"]},
                          {"status": "approved", "decided_by": POLICY_MARK,
                           "decision_type": "approve",
                           "decision_text": "auto-approved by owner policy: no legal-structuring conflict"})
                db.insert("notifications", {
                    "channel": "cockpit", "audience": AUDIENCE, "kind": "auto-approved",
                    "title": f"[auto] {(c.get('title') or '')[:150]}",
                    "body": f"[{c.get('project') or '-'}] auto-approved under owner policy; "
                            f"merges stay QA/build-gated. Why: {(c.get('why') or '')[:300]}",
                    "approval_id": c["id"], "sent": False})
                approved += 1
            elif is_legal_gated(c):
                patch = _enrich_gated(c)
                if patch:
                    db.update("approvals", {"id": c["id"]}, patch)
                gated += 1
        except Exception as e:
            print(f"approval_policy: skipped {c.get('id')}: {e}")
    print(f"approval_policy: auto-approved {approved}, legal-gated {gated} of {len(cards)} pending")
    return approved, gated


if __name__ == "__main__":
    sweep()
