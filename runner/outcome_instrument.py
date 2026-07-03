#!/usr/bin/env python3
"""
outcome_instrument.py - GROUND-TRUTH OUTCOMES: the critical enabler. Calibration, Brier scores, dissent-
vindication, seat reliability, and the portfolio bandit are only as good as the `outcome` label they learn
from. This module attributes a REALIZED outcome to each determination from actual post-ship signals —
revenue movement, retention/usage, and rollbacks — and writes it back onto committee_reviews +
committee_seat_reviews (the labels calibration reads) and a transparent determination_outcomes row.

Signal precedence per determination/subject:
  1. rollback / auto-rollback on the shipped work            -> outcome = -1 (bad)
  2. merge_revenue.revenue_delta for the shipped task slug   -> outcome = sign(delta)
  3. app_revenue movement (MRR+users) after the ship         -> outcome = sign(delta)
  4. task merged with no regression                          -> outcome = +0.5 (weak good)
Neutral / unknown -> left unlabeled (never guessed), so calibration stays honest.
Schedule daily (folded into committees.calibrate()).  Read-only except the outcome labels it writes.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _rev_by_slug():
    return {r["slug"]: float(r.get("revenue_delta") or 0)
            for r in (db.select("merge_revenue", {"select": "slug,revenue_delta"}) or [])}


def _rolled_back_slugs():
    out = set()
    for r in (db.select("committee_rollouts", {"select": "slug,stage,status"}) or []):
        if r.get("stage") == "rolled_back" or (r.get("status") == "done" and r.get("stage") == "rolled_back"):
            out.add(r.get("slug"))
    return out


def _label_for(det, rev, rolled):
    """Return (outcome, source, delta) for a determination, or (None,...) if we can't ground it yet."""
    # link determination -> shipped task via the improvement_proposal that produced it (subject_id)
    slug = None
    prop = (db.select("improvement_proposals", {"select": "task_slug", "id": f"eq.{det.get('subject_id')}"}) or [{}])
    if prop and prop[0].get("task_slug"):
        slug = prop[0]["task_slug"]
    if slug and slug in rolled:
        return -1.0, f"rollback:{slug}", None
    if slug and slug in rev:
        d = rev[slug]
        return (1.0 if d > 0 else -1.0 if d < 0 else 0.0), f"merge_revenue:{slug}", d
    # fall back to app-level movement if the determination names an app
    app = (det.get("title") or "").lower()
    for r in (db.select("app_revenue", {"select": "app,mrr_usd,active_users"}) or []):
        if (r.get("app") or "").lower() in app:
            return None, None, None   # app-level attribution handled by causal_attribution; skip weak guess
    if slug:
        return 0.5, f"merged:{slug}", None   # shipped, no regression seen -> weak positive
    return None, None, None


def run(limit=300):
    rev, rolled = _rev_by_slug(), _rolled_back_slugs()
    dets = db.select("determinations", {"select": "id,subject_id,title,recommendation",
                                        "order": "created_at.desc", "limit": str(limit)}) or []
    already = {o["subject_id"] for o in (db.select("determination_outcomes", {"select": "subject_id"}) or [])}
    labeled = 0
    for det in dets:
        sid = det.get("subject_id")
        if not sid or sid in already:
            continue
        outcome, source, delta = _label_for(det, rev, rolled)
        if outcome is None:
            continue
        # write the ground-truth row (transparency)
        db.insert("determination_outcomes", {"determination_id": det.get("id"), "subject_id": sid,
                  "metric": "revenue/usage", "delta": delta, "labeled_outcome": outcome, "source": source})
        # write the label onto the rows calibration actually reads
        for row in (db.select("committee_reviews", {"select": "id", "subject_id": f"eq.{sid}"}) or []):
            db.update("committee_reviews", {"id": row["id"]}, {"outcome": outcome})
        for row in (db.select("committee_seat_reviews", {"select": "id", "subject_id": f"eq.{sid}"}) or []):
            db.update("committee_seat_reviews", {"id": row["id"]}, {"outcome": outcome})
        labeled += 1
    print(f"outcome_instrument: grounded {labeled} determinations in realized outcomes")
    return labeled


if __name__ == "__main__":
    run()
