#!/usr/bin/env python3
"""cx_reviewer_queue.py - rank pending human-review items by expected value-of-review.
EV = materiality * contention * reversibility_weight * override_rate
Writes ranked digest into inbox (kind=review_queue). Read-only except inbox digest."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

LIMIT = int(os.environ.get("CX_REVIEWER_QUEUE_LIMIT", "50"))

def _override_rate():
    try:
        overrides = db.select("owner_overrides", {"select": "id", "limit": "1000"}) or []
        decided = db.select("approvals", {"select": "id", "status": "in.(approved,denied)", "limit": "1000"}) or []
        return len(overrides) / max(len(decided), 1)
    except Exception:
        return 0.1

def _contention(item):
    cp = item.get("consensus_pct")
    if cp is not None:
        try: return round(1.0 - float(cp), 3)
        except (ValueError, TypeError): pass
    return 0.5

def _materiality_score(item):
    m = item.get("materiality")
    if m is not None:
        try: return float(m)
        except (ValueError, TypeError): pass
    return 0.5

def _reversibility_weight(item):
    rev = item.get("reversible")
    if rev is False or str(rev).lower() == "false": return 1.5
    return 1.0

def _score_item(item, or_rate):
    return round(_materiality_score(item) * _contention(item) * _reversibility_weight(item) * max(or_rate, 0.05), 4)

def run():
    approvals = db.select("approvals", {"select": "*", "status": "eq.pending", "limit": str(LIMIT)}) or []
    proposals = db.select("improvement_proposals", {"select": "*", "status": "eq.for_review", "limit": str(LIMIT)}) or []
    if not approvals and not proposals:
        print("cx_reviewer_queue: nothing pending"); return 0
    or_rate = _override_rate()
    scored = []
    for a in approvals:
        scored.append({"type": "approval", "id": a.get("id"), "title": a.get("title", ""), "ev_review": _score_item(a, or_rate)})
    for p in proposals:
        scored.append({"type": "proposal", "id": p.get("id"), "title": p.get("title", ""), "ev_review": _score_item(p, or_rate)})
    scored.sort(key=lambda x: x["ev_review"], reverse=True)
    lines = [f"Ranked review queue ({len(scored)} items, override_rate={round(or_rate, 3)}):"]
    for i, s in enumerate(scored[:20], 1):
        lines.append(f"{i}. [{s[chr(39)+'type'+chr(39) if 0 else 'type'}] {s['title'][:80]}  (EV={s['ev_review']})")
    try:
        db.insert("inbox", {"kind": "review_queue", "title": f"Review queue: {len(scored)} items",
            "body": chr(10).join(lines)[:3000], "status": "unread"})
    except Exception: pass
    print(f"cx_reviewer_queue: ranked {len(scored)} items")
    return len(scored)

if __name__ == "__main__":
    run()
