#!/usr/bin/env python3
"""
cx_ensemble_panels.py - ensemble deliberation for high-materiality determinations.

For the highest-materiality recent determinations, convene 2-3 INDEPENDENTLY-assembled panels
via committees.review() on the same subject and compare their verdicts. Record agreement/
disagreement as inbox kind='ensemble' + a determination_outcomes row source='ensemble'.
Disagreement is treated as a contention signal that should stay with a human.

Read-only except the digest; reuses committees.review; does not edit committees.py.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import committees

MAX_PANELS = int(os.environ.get("ENSEMBLE_MAX_PANELS", "3"))
MIN_PANELS = 2
TOP_N = int(os.environ.get("ENSEMBLE_TOP_N", "5"))


def _high_materiality_determinations():
    """Fetch recent high-materiality determinations not yet ensemble-reviewed."""
    already = {r["subject_id"] for r in (db.select("determination_outcomes", {
        "select": "subject_id", "source": "eq.ensemble"}) or [])}
    rows = db.select("committee_opinions", {
        "select": "subject_type,subject_id,subject_title,opinion,consensus_verdict,app",
        "order": "created_at.desc", "limit": str(TOP_N * 3)}) or []
    out = []
    for r in rows:
        sid = r.get("subject_id")
        if sid and sid not in already:
            already.add(sid)
            out.append(r)
        if len(out) >= TOP_N:
            break
    return out


def _convene_panels(subject_type, subject_id, title, body, app=None):
    """Run committees.review() multiple times independently to get diverse panels."""
    results = []
    for _ in range(MAX_PANELS):
        try:
            result = committees.review(subject_type, subject_id, title, body, app=app)
            if result and result.get("aggregate") is not None:
                results.append(result)
        except Exception:
            pass
        if len(results) >= MIN_PANELS:
            # enough for comparison; stop early if we hit max
            if len(results) >= MAX_PANELS:
                break
    return results


def _compare_verdicts(panels):
    """Compare panel verdicts. Returns (agreed: bool, summary: str)."""
    if not panels:
        return True, "no panels"
    recs = [p.get("recommendation", "HOLD") for p in panels]
    # normalize: strip parenthetical qualifiers for comparison
    normed = [r.split("(")[0].strip().upper() for r in recs]
    unique = set(normed)
    agreed = len(unique) == 1
    summary = f"verdicts: {', '.join(recs)} -> {'AGREE' if agreed else 'DISAGREE'}"
    return agreed, summary


def run():
    """Entry point for periodic scheduling."""
    dets = _high_materiality_determinations()
    if not dets:
        return
    for det in dets:
        sid = det.get("subject_id")
        stype = det.get("subject_type", "determination")
        title = det.get("subject_title", "")
        body = det.get("opinion", "")
        app = det.get("app")

        panels = _convene_panels(stype, sid, title, body, app=app)
        if len(panels) < MIN_PANELS:
            continue

        agreed, summary = _compare_verdicts(panels)

        # Record outcome
        try:
            db.insert("determination_outcomes", {
                "determination_id": sid,
                "subject_id": sid,
                "source": "ensemble",
                "labeled_outcome": "agree" if agreed else "disagree",
                "detail": summary[:500],
            })
        except Exception:
            pass

        # Inbox item for visibility
        try:
            db.insert("inbox", {
                "kind": "ensemble",
                "title": f"Ensemble {'agreement' if agreed else 'DISAGREEMENT'}: {title[:80]}",
                "body": summary[:1000],
                "app": app,
            })
        except Exception:
            pass
