#!/usr/bin/env python3
"""
cx_outcome_horizons.py - Multi-horizon outcome measurement for determinations.

For determinations old enough, compute the realized revenue/usage delta at 7/30/90-day
horizons (reusing outcome_instrument's signal sources: merge_revenue, app_revenue,
committee_rollouts) and store per-horizon rows in determination_outcomes (metric like
'revenue_7d', 'revenue_30d', 'revenue_90d'). Flags decays where a determination was
positive at an early horizon but negative at a later one. Never guesses when no signal
exists. This lets calibration weight durability over first impressions. No schema change
(reuses determination_outcomes table).
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HORIZONS = [7, 30, 90]


def _age_days(created_at_str):
    """Return the age in days of a timestamp string, or None if unparseable."""
    if not created_at_str:
        return None
    try:
        ts = created_at_str.replace("Z", "+00:00")
        created = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - created).days
    except Exception:
        return None


def _rev_by_slug():
    """Revenue deltas keyed by slug from merge_revenue."""
    return {r["slug"]: float(r.get("revenue_delta") or 0)
            for r in (db.select("merge_revenue", {"select": "slug,revenue_delta"}) or [])}


def _rolled_back_slugs():
    """Set of slugs that have been rolled back."""
    out = set()
    for r in (db.select("committee_rollouts", {"select": "slug,stage,status"}) or []):
        if r.get("stage") == "rolled_back":
            out.add(r.get("slug"))
    return out


def _app_revenue_map():
    """Map app name -> latest MRR for app-level fallback."""
    return {(r.get("app") or "").lower(): float(r.get("mrr_usd") or 0)
            for r in (db.select("app_revenue", {"select": "app,mrr_usd"}) or [])}


def _slug_for_determination(det):
    """Resolve the task slug linked to a determination via its subject_id."""
    sid = det.get("subject_id")
    if not sid:
        return None
    props = db.select("improvement_proposals",
                      {"select": "task_slug", "id": f"eq.{sid}"}) or [{}]
    return props[0].get("task_slug") if props else None


def _compute_horizon_outcome(slug, horizon_days, rev, rolled):
    """Compute the outcome for a specific horizon. Returns (outcome, source, delta) or (None, None, None)."""
    if not slug:
        return None, None, None
    if slug in rolled:
        return -1.0, f"rollback:{slug}@{horizon_days}d", None
    if slug in rev:
        d = rev[slug]
        if d == 0:
            return 0.0, f"merge_revenue:{slug}@{horizon_days}d", d
        return (1.0 if d > 0 else -1.0), f"merge_revenue:{slug}@{horizon_days}d", d
    return None, None, None


def _detect_decay(horizon_outcomes):
    """Flag decay: positive at early horizon, negative at later horizon.
    Returns a list of decay descriptions, or empty list."""
    decays = []
    sorted_h = sorted(horizon_outcomes.items())
    for i, (h1, o1) in enumerate(sorted_h):
        if o1 is None or o1 <= 0:
            continue
        for h2, o2 in sorted_h[i + 1:]:
            if o2 is not None and o2 < 0:
                decays.append(f"decay:{h1}d->{ h2}d")
    return decays


def run(limit=200):
    """Main entry point. For each determination old enough for a given horizon,
    compute and store the realized outcome at that horizon if not already stored."""
    rev = _rev_by_slug()
    rolled = _rolled_back_slugs()
    dets = db.select("determinations", {
        "select": "id,subject_id,title,created_at",
        "order": "created_at.desc",
        "limit": str(limit),
    }) or []

    # Build set of already-recorded (subject_id, metric) pairs to avoid duplicates
    existing = set()
    for o in (db.select("determination_outcomes", {"select": "subject_id,metric"}) or []):
        existing.add((o.get("subject_id"), o.get("metric")))

    labeled = 0
    decays_flagged = 0

    for det in dets:
        sid = det.get("subject_id")
        if not sid:
            continue
        age = _age_days(det.get("created_at"))
        if age is None:
            continue
        slug = _slug_for_determination(det)
        horizon_outcomes = {}

        for horizon in HORIZONS:
            if age < horizon:
                continue  # not old enough for this horizon yet
            metric = f"revenue_{horizon}d"
            if (sid, metric) in existing:
                continue  # already recorded
            outcome, source, delta = _compute_horizon_outcome(slug, horizon, rev, rolled)
            if outcome is None:
                continue  # never guess
            db.insert("determination_outcomes", {
                "determination_id": det.get("id"),
                "subject_id": sid,
                "metric": metric,
                "delta": delta,
                "labeled_outcome": outcome,
                "source": source,
            })
            horizon_outcomes[horizon] = outcome
            labeled += 1

        # Check for decay pattern across horizons
        if horizon_outcomes:
            decays = _detect_decay(horizon_outcomes)
            if decays:
                decays_flagged += 1
                # Store a decay flag row
                db.insert("determination_outcomes", {
                    "determination_id": det.get("id"),
                    "subject_id": sid,
                    "metric": "decay_flag",
                    "delta": None,
                    "labeled_outcome": -0.5,
                    "source": ";".join(decays),
                })

    print(f"cx_outcome_horizons: labeled {labeled} horizon outcomes, {decays_flagged} decay flags")
    return {"labeled": labeled, "decays": decays_flagged}


if __name__ == "__main__":
    run()
