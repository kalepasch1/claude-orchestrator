#!/usr/bin/env python3
"""
causal_attribution.py - CAUSAL, not correlational, credit. The scoreboard rewards experts whose decisions
CAUSED good outcomes, not ones that merely co-occurred with them. Where a determination shipped as an A/B
or behind a holdout (committee_experiments), compute the treatment-vs-control lift and attribute THAT
(signed) as the causal outcome; feed it back as the determination's ground-truth label so calibration and
the reputation flywheel learn from causal effect.

  run(): for each concluded experiment tied to a determination, compute lift, write determination_outcomes
         (causal_lift + labeled_outcome from the sign of the lift), and label the underlying reviews.
Schedule daily (folded into committees.calibrate()). Falls back gracefully when no experiments exist.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _match_determination(app, slug):
    """Find the determination whose title references this experiment's app/hypothesis."""
    dets = db.select("determinations", {"select": "id,subject_id,title", "order": "created_at.desc",
                                        "limit": "200"}) or []
    key = (slug or "").replace("ab-", "").replace("-", " ")
    for d in dets:
        t = (d.get("title") or "").lower()
        if app and app.lower() in t:
            return d
        if key and any(w in t for w in key.split() if len(w) > 3):
            return d
    return None


def _concurrent_experiments(exp, all_exps):
    """Find experiments that overlapped in time with exp, excluding exp itself."""
    start = exp.get("started_at") or ""
    end = exp.get("concluded_at") or exp.get("updated_at") or ""
    concurrent = []
    for other in all_exps:
        if other.get("id") == exp.get("id"):
            continue
        o_start = other.get("started_at") or ""
        o_end = other.get("concluded_at") or other.get("updated_at") or ""
        # Overlap check: experiments overlap if one starts before the other ends
        if o_start and end and o_start <= end and o_end and o_end >= start:
            concurrent.append(other)
    return concurrent


def _adjust_lift_for_concurrency(lift, exp, concurrent):
    """Discount lift when concurrent experiments may confound attribution.

    If N concurrent experiments were running, attribute only 1/(N+1) of the
    observed lift to this experiment — a conservative equal-share split that
    avoids double-counting the same KPI movement across experiments.
    """
    if not concurrent:
        return lift
    n = len(concurrent) + 1  # this experiment + concurrent ones
    return lift / n


def run():
    exps = db.select("committee_experiments", {"select": "*", "status": "eq.concluded"}) or []
    linked = {o.get("subject_id") for o in (db.select("determination_outcomes",
              {"select": "subject_id", "source": "like.causal%"}) or [])}
    n = 0
    for x in exps:
        lift = x.get("lift")
        if lift is None:
            continue
        det = _match_determination(x.get("app"), x.get("slug"))
        if not det or det.get("subject_id") in linked:
            continue
        lift = float(lift)
        # Adjust for concurrent experiments to avoid misattribution
        concurrent = _concurrent_experiments(x, exps)
        lift = _adjust_lift_for_concurrency(lift, x, concurrent)
        outcome = 1.0 if lift >= 1 else -1.0 if lift <= -1 else 0.0   # material causal lift threshold
        db.insert("determination_outcomes", {"determination_id": det.get("id"), "subject_id": det.get("subject_id"),
                  "metric": "ab_lift_pct", "delta": lift, "causal_lift": lift, "labeled_outcome": outcome,
                  "is_holdout": (x.get("kind") == "holdout"), "source": f"causal:{x.get('slug')}"})
        sid = det.get("subject_id")
        if sid and outcome != 0:
            for row in (db.select("committee_reviews", {"select": "id", "subject_id": f"eq.{sid}"}) or []):
                db.update("committee_reviews", {"id": row["id"]}, {"outcome": outcome})
            for row in (db.select("committee_seat_reviews", {"select": "id", "subject_id": f"eq.{sid}"}) or []):
                db.update("committee_seat_reviews", {"id": row["id"]}, {"outcome": outcome})
        n += 1
    print(f"causal_attribution: attributed causal lift to {n} determinations")
    return n


if __name__ == "__main__":
    run()
