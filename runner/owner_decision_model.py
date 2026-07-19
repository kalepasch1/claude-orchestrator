#!/usr/bin/env python3
"""
owner_decision_model.py - learn the owner from decision history.

approval_policy.py already narrows the human gate to genuine legal-structuring
questions. This module goes one step further: it studies the owner's PRIOR
decisions (approved/denied cards with decision_text) per legal category and,
when the owner has answered the same category of question consistently
(>= MIN_PRECEDENTS decisions, >= CONSISTENCY of them choosing the same option
pattern), auto-applies that precedent to new gated cards. Otherwise it merely
annotates the pending card with a suggested option + rationale so the email /
cockpit surfaces show "the model thinks you'd pick X (based on N precedents)".

Audit trail mirrors approval_policy: decided_by='owner-model:precedent' plus a
digest notification row - nothing disappears silently.
"""
import os, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import approval_policy

MODEL_MARK = "owner-model:precedent"
AUDIENCE = os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com")
MIN_PRECEDENTS = 5          # need at least this many prior decisions in a category
CONSISTENCY = 0.80          # and this fraction choosing the same option pattern
PATTERN_LEN = 12            # first N chars of decision_text after 'CHOSEN: '

# Ordered: first matching category wins; 'other' is the fallback.
CATEGORY_RX = [
    ("attestation-reliance", re.compile(r"attestation|attest\b|reliance|third\s+part(y|ies)\s+rely", re.I)),
    ("solicitation", re.compile(r"solicit|general\s+solicitation|cold\s+outreach|recruit\s+page", re.I)),
    ("financial-advice", re.compile(
        r"financial\s+advice|invest(ment)?\s+advice|securit(y|ies)|broker|adviser|advisor|"
        r"insurance\s+(advice|product)|lending|fiduciary", re.I)),
    ("data-use-crossapp", re.compile(r"data.{0,12}(use|shar|transfer)|cross.?app|privacy|pii|consent", re.I)),
    ("pricing", re.compile(r"pric(e|ing)|billing|fee\b|fees\b|discount|refund", re.I)),
    ("marketing-claims", re.compile(r"marketing|advertis|promo|testimonial|claim(s)?\b|guarantee", re.I)),
]


def _text(card):
    return " ".join(str(card.get(k) or "") for k in ("title", "why", "decision_text"))


def classify(card):
    """Map a card/decision row to a category via regex on title+why+decision_text."""
    text = _text(card)
    for cat, rx in CATEGORY_RX:
        if rx.search(text):
            return cat
    return "other"


def _pattern(row):
    """Canonical 'what the owner chose' key: first PATTERN_LEN chars of decision_text
    after 'CHOSEN: ', else the decision_type, else a prefix of decision_text."""
    dt = str(row.get("decision_text") or "")
    if "CHOSEN: " in dt:
        return dt.split("CHOSEN: ", 1)[1][:PATTERN_LEN]
    if row.get("decision_type"):
        return str(row["decision_type"])
    return dt[:PATTERN_LEN]


def history(category):
    """All prior decided cards (approved/denied, with decision_text) in this category."""
    rows = db.select("approvals", {"select": "*",
                                   "status": "in.(approved,denied)",
                                   "decision_text": "not.is.null",
                                   "limit": "1000"}) or []
    return [r for r in rows if classify(r) == category]


def _words(s):
    return set(re.findall(r"[a-z0-9]+", str(s or "").lower()))


def draft(card):
    """Draft a decision for a gated card from owner precedent.
    Returns {"auto_apply": True, decision_type, decision_text, confidence} when the
    owner has been consistent enough, else {"auto_apply": False,
    suggested_option_index, rationale}."""
    cat = classify(card)
    hist = history(cat)
    patterns = Counter(p for p in (_pattern(r) for r in hist) if p)
    n = sum(patterns.values())
    if n >= MIN_PRECEDENTS:
        top, cnt = patterns.most_common(1)[0]
        ratio = cnt / n
        if ratio >= CONSISTENCY:
            rep = next((r for r in hist if _pattern(r) == top), {})
            return {"auto_apply": True,
                    "decision_type": rep.get("decision_type") or "approve",
                    "decision_text": (f"auto-applied from owner precedent "
                                      f"({cnt} consistent prior decisions): {top}"),
                    "confidence": round(ratio, 3)}
    # Not confident enough to decide - suggest the option whose label best
    # word-overlaps the most common prior decision_text.
    common_text = ""
    if patterns:
        top = patterns.most_common(1)[0][0]
        rep = next((r for r in hist if _pattern(r) == top), None)
        common_text = str((rep or {}).get("decision_text") or "")
    bj = card.get("brief_json")
    options = (bj or {}).get("options") if isinstance(bj, dict) else None
    idx = 0
    if options and common_text:
        cw = _words(common_text)
        idx = max(range(len(options)),
                  key=lambda i: len(cw & _words((options[i] or {}).get("label", ""))))
    return {"auto_apply": False, "suggested_option_index": idx,
            "rationale": (f"owner-decision-model: {len(hist)} precedents in "
                          f"category '{cat}'; not consistent enough to auto-apply")}


def apply(card):
    """Execute draft(card): auto-approve from precedent, or annotate the pending card."""
    d = draft(card)
    if d.get("auto_apply"):
        db.update("approvals", {"id": card["id"]},
                  {"status": "approved", "decided_by": MODEL_MARK,
                   "decision_type": d["decision_type"],
                   "decision_text": d["decision_text"]})
        db.insert("notifications", {
            "channel": "digest", "audience": AUDIENCE, "kind": "owner-model",
            "title": f"[owner-model] {(card.get('title') or '')[:150]}",
            "body": (f"[{card.get('project') or '-'}] {d['decision_text']} "
                     f"(confidence {d['confidence']})"),
            "approval_id": card.get("id"), "sent": False})
    else:
        bj = card.get("brief_json")
        bj = dict(bj) if isinstance(bj, dict) else {}
        bj["suggested_option_index"] = d["suggested_option_index"]
        bj["recommended_index"] = d["suggested_option_index"]
        bj["model_rationale"] = d["rationale"]
        db.update("approvals", {"id": card["id"]}, {"brief_json": bj})
    return d


def sweep(limit=200):
    """Run apply() over pending legal-gated cards. Returns (auto_applied, suggested)."""
    cards = db.select("approvals", {"select": "*", "status": "eq.pending",
                                    "order": "created_at.asc", "limit": str(limit)}) or []
    auto = suggested = 0
    for c in cards:
        try:
            if not approval_policy.is_legal_gated(c):
                continue
            if apply(c).get("auto_apply"):
                auto += 1
            else:
                suggested += 1
        except Exception as e:
            print(f"owner_decision_model: skipped {c.get('id')}: {e}")
    print(f"owner_decision_model: auto-applied {auto}, suggested {suggested} "
          f"of {len(cards)} pending")
    return auto, suggested


if __name__ == "__main__":
    sweep()
