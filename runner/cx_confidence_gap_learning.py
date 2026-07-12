#!/usr/bin/env python3
"""
cx_confidence_gap_learning.py - learn fastest from surprises.

Find determinations where predicted confidence and the realized labeled_outcome most disagree
(high-confidence GO that went bad, or low-confidence HOLD that would have paid off), and route
those exact subjects to re-deliberation (queue an inbox item kind='surprise_review' + optionally
an improvement_proposal to re-run).

Read-only except the queue/digest; reuses determination_outcomes; does not edit committees.py.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TOP_N = int(os.environ.get("CONFIDENCE_GAP_TOP_N", "10"))


def _fetch_surprises():
    """Find determinations where confidence and outcome disagree most."""
    outcomes = db.select("determination_outcomes", {
        "select": "determination_id,subject_id,labeled_outcome,detail,source",
        "source": "neq.ensemble",
        "order": "created_at.desc",
        "limit": "200",
    }) or []
    if not outcomes:
        return []

    # Get corresponding committee opinions for confidence scores
    subject_ids = list({o["subject_id"] for o in outcomes if o.get("subject_id")})
    if not subject_ids:
        return []

    opinions = db.select("committee_opinions", {
        "select": "subject_id,consensus_verdict,conviction,score,subject_title,app",
        "order": "created_at.desc",
        "limit": "500",
    }) or []
    opinion_map = {}
    for op in opinions:
        sid = op.get("subject_id")
        if sid and sid not in opinion_map:
            opinion_map[sid] = op

    # Already reviewed surprises
    already = set()
    existing = db.select("inbox", {
        "select": "title",
        "kind": "eq.surprise_review",
        "limit": "500",
    }) or []
    for e in existing:
        already.add(e.get("title", ""))

    surprises = []
    for o in outcomes:
        sid = o.get("subject_id")
        op = opinion_map.get(sid)
        if not op:
            continue

        verdict = (op.get("consensus_verdict") or "").lower()
        conviction = float(op.get("conviction") or 5)
        outcome = (o.get("labeled_outcome") or "").lower()

        # High-confidence GO that went bad
        go_bad = (verdict == "support" and conviction >= 7
                  and outcome in ("negative", "failed", "bad", "disagree", "loss"))
        # Low-confidence HOLD that would have paid off
        hold_good = (verdict in ("oppose", "hold", "needs-info") and conviction <= 4
                     and outcome in ("positive", "success", "good", "agree", "gain"))

        if go_bad or hold_good:
            gap = abs(conviction - (2 if go_bad else 8))  # distance from "correct" confidence
            title = f"Surprise: {op.get('subject_title', sid)}"
            if title in already:
                continue
            surprises.append({
                "subject_id": sid,
                "title": op.get("subject_title", ""),
                "app": op.get("app"),
                "verdict": verdict,
                "conviction": conviction,
                "outcome": outcome,
                "gap": gap,
                "kind": "go_bad" if go_bad else "hold_good",
            })

    surprises.sort(key=lambda s: s["gap"], reverse=True)
    return surprises[:TOP_N]


def run():
    """Entry point for periodic scheduling."""
    surprises = _fetch_surprises()
    if not surprises:
        return

    for s in surprises:
        title = f"Surprise: {s['title'][:80]}"
        body = (f"Prediction: {s['verdict']} (conviction {s['conviction']}), "
                f"Outcome: {s['outcome']}. Type: {s['kind']}. "
                f"This subject should be re-deliberated to learn from the gap.")

        try:
            db.insert("inbox", {
                "kind": "surprise_review",
                "title": title,
                "body": body[:1000],
                "app": s.get("app"),
            })
        except Exception:
            pass
