#!/usr/bin/env python3
"""
constitution.py - CONSTITUTION-AS-CODE. Moves the guardrails from heuristic strings to explicit, machine-
checked PREDICATES that gate every determination and leave an auditable record. CADE proposes; the
Constitution bounds; a human acts. Each predicate returns pass/fail; a failed 'block' rule forces the
determination to a human no matter how confident the panel is.

Predicates (referenced by constitution_rules.predicate):
  no_money_movement   - the action must not autonomously move money / file / send on the owner's behalf
  legal_veto_blocks   - a legal/compliance expert opposing is absolute (cannot be auto-executed)
  privacy_required    - if the issue touches user data, privacy competence must be seated (warn)
  reversibility_gate  - irreversible / critical determinations must go to a human

evaluate(agg) -> {"passed":bool, "must_gate":bool, "violations":[{rule,severity,detail}], ...}
Pure + dependency-light; the only I/O is reading the (cached) rule list and writing check rows.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_MONEY = ("wire", "transfer", "pay ", "payout", "withdraw", "send funds", "buy ", "sell ", "trade",
          "invoice", "charge the", "move money", "file with", "submit to the")


def _rules():
    try:
        return db.select("constitution_rules", {"select": "*", "active": "eq.true"}) or []
    except Exception:
        return []


def _panel_has_legal_oppose(agg):
    for p in (agg.get("panel") or []):
        n = (p.get("committee") or "").lower()
        if any(k in n for k in ("legal", "complian", "regulat", "privacy", "counsel")) and p.get("verdict") == "oppose":
            return True
    return False


def _touches_user_data(agg):
    t = ((agg.get("title") or "") + " " + (agg.get("body") or "")).lower()
    return any(k in t for k in ("user data", "pii", "personal data", "email", "profile", "tracking",
                                "consent", "gdpr", "ccpa", "privacy"))


def _privacy_seated(agg):
    return any("privacy" in (p.get("committee") or "").lower() or "legal" in (p.get("committee") or "").lower()
               for p in (agg.get("panel") or []))


def _check(predicate, agg):
    """Return (passed, detail) for one predicate against the determination."""
    if predicate == "no_money_movement":
        t = ((agg.get("title") or "") + " " + (agg.get("body") or "")).lower()
        hit = next((m for m in _MONEY if m in t), None)
        return (hit is None), (f"references '{hit.strip()}' — must not auto-execute money/filing/sending" if hit else "ok")
    if predicate == "legal_veto_blocks":
        return (not _panel_has_legal_oppose(agg)), ("legal/compliance expert opposes — veto is absolute" if _panel_has_legal_oppose(agg) else "ok")
    if predicate == "privacy_required":
        if _touches_user_data(agg) and not _privacy_seated(agg):
            return False, "touches user data but no privacy/legal competence was seated"
        return True, "ok"
    if predicate == "reversibility_gate":
        return (not agg.get("critical")), ("critical/irreversible — requires a human" if agg.get("critical") else "ok")
    return True, "unknown predicate (skipped)"


def evaluate(agg, determination_id=None):
    violations, must_gate = [], False
    for r in _rules():
        passed, detail = _check(r.get("predicate"), agg)
        if not passed:
            sev = r.get("severity", "block")
            violations.append({"rule": r.get("name"), "severity": sev, "detail": detail})
            if sev == "block":
                must_gate = True
        if determination_id:
            try:
                db.insert("constitution_checks", {"determination_id": determination_id,
                          "rule": r.get("name"), "passed": passed, "detail": detail})
            except Exception:
                pass
    return {"passed": not violations, "must_gate": must_gate, "violations": violations}


if __name__ == "__main__":
    import json
    demo = {"title": "Auto-wire refunds to churned users", "body": "transfer funds automatically",
            "critical": False, "panel": []}
    print(json.dumps(evaluate(demo), indent=2))
