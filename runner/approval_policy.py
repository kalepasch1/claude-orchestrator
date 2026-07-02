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
    * radar_tag='regulatory'
    * title/why/detail matches LEGAL_RX (exemptions, licensing, solicitation, attestation
      reliance, securities/insurance advice, entity/tax structuring, privilege, KYC/AML)
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

POLICY_MARK = "auto-policy:owner-20260702"
ENABLED = os.environ.get("OWNER_POLICY_AUTOAPPROVE", "true").lower() in ("true", "1", "yes")
AUDIENCE = os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com")

LEGAL_RX = re.compile(
    r"exempt|licens|solicit|attestation|reliance|securit(y|ies)\s+offering|"
    r"broker|adviser|advisor.{0,12}(regist|licens)|insurance\s+(advice|product|producer)|"
    r"regulated\s+activit|general\s+solicitation|entity\s+(formation|structur)|"
    r"tax\s+(election|structur)|privilege|kyc|aml|money\s+transmi|lending\s+exemption|"
    r"legal\s+structur", re.I)

ALARM_RX = re.compile(
    r"billing\s+firewall|api\s+key|spend\s+(cap|circuit)|cost\s+circuit|account.{0,20}exhaust|"
    r"secret|credential", re.I)

FALLBACK_ALTERNATIVES = [
    {"label": "Proceed with guardrails: ship the non-legal parts now; wrap the sensitive part in disclaimers/limits", "risk": "low", "reversible": True},
    {"label": "Proceed fully - after counsel confirms it fits the current exemption/structuring posture", "risk": "high", "reversible": False},
    {"label": "Defer only the conflicting fraction; everything else proceeds now", "risk": "minimal", "reversible": True},
]


def _text(card):
    return " ".join(str(card.get(k) or "") for k in ("title", "why", "detail", "prebrief"))


def is_legal_gated(card):
    """True if this card raises a genuine legal-structuring/exemption question."""
    if card.get("kind") == "legal" and (card.get("legal_risk_level") or "") == "novel":
        return True
    if (card.get("radar_tag") or "") == "regulatory":
        return True
    return bool(LEGAL_RX.search(_text(card)))


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
        m = LEGAL_RX.search(_text(card))
        hook = f" (trigger: '{m.group(0)}')" if m else ""
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
        patch["alternatives"] = FALLBACK_ALTERNATIVES
    if not card.get("legal_risk_level"):
        patch["legal_risk_level"] = "novel"
    return patch


def sweep(limit=200):
    """Classify every pending card: auto-approve the safe, enrich + keep the legal."""
    if not ENABLED:
        print("approval_policy: disabled (OWNER_POLICY_AUTOAPPROVE=false)")
        return 0, 0
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
                    "channel": "digest", "audience": AUDIENCE, "kind": "auto-approved",
                    "title": f"[auto] {(c.get('title') or '')[:150]}",
                    "body": f"[{c.get('project') or '-'}] auto-approved under owner policy; "
                            f"merges stay test-gated. Why: {(c.get('why') or '')[:300]}",
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
