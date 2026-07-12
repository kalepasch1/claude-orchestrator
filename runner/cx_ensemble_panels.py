#!/usr/bin/env python3
"""
cx_ensemble_panels.py - Cross-examination ensemble panels.

For the highest-materiality recent determinations (bounded, cost-safe on
subscription models), convene 2-3 INDEPENDENTLY-assembled panels via
committees.review() on the same subject and compare their verdicts.

Records agreement/disagreement as an inbox item (kind='ensemble') plus a
determination_outcomes row (source='ensemble').  Treats disagreement as a
contention signal that should stay with a human.

Read-only except the digest; reuses committees.review; does NOT edit committees.py.
"""
import os, sys, datetime, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import committees

MAX_PANELS = int(os.environ.get("ENSEMBLE_MAX_PANELS", "3"))
MIN_PANELS = 2
MAX_DETERMINATIONS = int(os.environ.get("ENSEMBLE_MAX_DETERMINATIONS", "5"))
MATERIALITY_THRESHOLD = float(os.environ.get("ENSEMBLE_MATERIALITY_THRESHOLD", "7.0"))


def _recent_high_materiality_determinations():
    """Fetch recent determinations above the materiality threshold, bounded for cost safety."""
    try:
        rows = db.select("determinations", {
            "select": "*",
            "order": "created_at.desc",
            "limit": str(MAX_DETERMINATIONS * 3),
        }) or []
    except Exception:
        return []
    # Filter to high-materiality: score >= threshold, not already ensembled
    already = set()
    try:
        existing = db.select("determination_outcomes", {
            "select": "determination_id",
            "source": "eq.ensemble",
        }) or []
        already = {r.get("determination_id") for r in existing}
    except Exception:
        pass
    result = []
    for r in rows:
        if r.get("id") in already:
            continue
        score = float(r.get("score") or r.get("materiality") or 0)
        if score >= MATERIALITY_THRESHOLD:
            result.append(r)
        if len(result) >= MAX_DETERMINATIONS:
            break
    return result

def _convene_ensemble(det):
    """Convene 2-3 independent panels for a single determination and compare verdicts."""
    title = det.get("title") or det.get("subject") or f"determination-{det.get('id', '?')}"
    body = det.get("body") or det.get("detail") or json.dumps(det, default=str)[:2000]
    subject_type = det.get("subject_type") or "determination"
    subject_id = det.get("subject_id") or det.get("id") or ""

    verdicts = []
    for i in range(MAX_PANELS):
        try:
            result = committees.review(subject_type, subject_id, title, body)
            if result and result.get("aggregate") is not None:
                verdicts.append(result)
        except Exception:
            pass  # fail-soft: partial ensemble is acceptable
        if len(verdicts) >= MIN_PANELS:
            # Cost gate: stop once we have enough independent opinions
            if len(verdicts) >= MAX_PANELS:
                break

    if len(verdicts) < MIN_PANELS:
        return None  # not enough panels convened

    # Compare verdicts
    recommendations = [v.get("recommendation", "") for v in verdicts]
    unique_recs = set(recommendations)
    agrees = len(unique_recs) == 1
    scores = [v.get("aggregate", 0) for v in verdicts]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    return {
        "determination_id": det.get("id"),
        "subject_id": subject_id,
        "title": title,
        "panel_count": len(verdicts),
        "agrees": agrees,
        "recommendations": recommendations,
        "avg_score": avg_score,
        "verdicts": verdicts,
    }


def _record_ensemble(result):
    """Record the ensemble result as inbox + determination_outcomes row."""
    agrees = result["agrees"]
    det_id = result.get("determination_id")
    subject_id = result.get("subject_id") or ""
    title = result.get("title", "")
    recs = result.get("recommendations", [])

    if agrees:
        body = f"Ensemble of {result['panel_count']} panels AGREES on '{recs[0]}' (avg score {result['avg_score']})"
    else:
        body = (f"Ensemble of {result['panel_count']} panels DISAGREES — "
                f"recommendations: {', '.join(recs)} (avg score {result['avg_score']}). "
                f"Contention signal: requires human review.")

    # Inbox item
    try:
        db.insert("inbox", {
            "kind": "ensemble",
            "title": f"Ensemble: {title[:120]}",
            "body": body[:3000],
            "meta": json.dumps({
                "agrees": agrees,
                "panel_count": result["panel_count"],
                "recommendations": recs,
                "avg_score": result["avg_score"],
            }),
        })
    except Exception:
        pass

    # determination_outcomes row
    if det_id:
        try:
            db.insert("determination_outcomes", {
                "determination_id": det_id,
                "subject_id": subject_id,
                "source": "ensemble",
                "outcome": "agreement" if agrees else "contention",
                "detail": body[:1000],
            })
        except Exception:
            pass


def run():
    """Entry point: ensemble-review the highest-materiality recent determinations."""
    dets = _recent_high_materiality_determinations()
    if not dets:
        return {"ensembled": 0, "note": "no high-materiality determinations pending ensemble review"}

    results = []
    for det in dets:
        result = _convene_ensemble(det)
        if result:
            _record_ensemble(result)
            results.append({
                "title": result["title"],
                "agrees": result["agrees"],
                "panel_count": result["panel_count"],
                "avg_score": result["avg_score"],
            })

    agreements = sum(1 for r in results if r["agrees"])
    contentions = sum(1 for r in results if not r["agrees"])
    return {
        "ensembled": len(results),
        "agreements": agreements,
        "contentions": contentions,
        "details": results,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
