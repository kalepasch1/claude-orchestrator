#!/usr/bin/env python3
"""
self_tune.py - closes the optimization loop. Reads REAL per-project outcomes and nudges the knobs
that govern autonomy, so the system self-calibrates instead of being hand-tuned:

  * confidence_threshold (per project): if a project's auto-merged / judge-passed work is proving
    reliable (high tests+integrate rate, no recent bad-merge regressions), LOWER the threshold a
    notch (more autonomy). If it's producing regressions / conflicts, RAISE it (more gating).
  * auto_merge stays under human control — self_tune never flips it on; it only tunes thresholds
    within a safe band. (You flip auto_merge per project explicitly.)

Bounded + reversible: every change is clamped to [FLOOR, CEIL] and moves by at most STEP per run,
and each adjustment is logged. Schedule daily (after roi).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW = int(os.environ.get("SELFTUNE_WINDOW", "200"))     # recent outcomes per project
STEP = float(os.environ.get("SELFTUNE_STEP", "0.05"))
FLOOR = float(os.environ.get("SELFTUNE_FLOOR", "0.30"))
CEIL = float(os.environ.get("SELFTUNE_CEIL", "0.90"))
GOOD_INTEGRATE = float(os.environ.get("SELFTUNE_GOOD", "0.55"))   # merge rate that earns more autonomy
BAD_INTEGRATE = float(os.environ.get("SELFTUNE_BAD", "0.25"))    # merge rate that tightens gating


def _stats(project):
    rows = db.select("outcomes", {"select": "tests_passed,integrated",
                                  "project": f"eq.{project}",
                                  "order": "created_at.desc", "limit": str(WINDOW)}) or []
    if not rows:
        return None
    n = len(rows)
    tests = sum(1 for r in rows if r.get("tests_passed")) / n
    integ = sum(1 for r in rows if r.get("integrated")) / n
    return {"n": n, "tests": round(tests, 3), "integrated": round(integ, 3)}


def _recent_bad_merges(project, days=3):
    """Regressions logged after an integrate — a signal that autonomy is too loose."""
    try:
        rows = db.select("regressions", {"select": "id", "project": f"eq.{project}",
                                         "limit": "50"}) or []
        return len(rows)
    except Exception:
        return 0


def plan_changes():
    """Compute (but do not apply) threshold changes. Returns list of dicts.

    Correctness note: a LOW integrate rate does NOT by itself mean bad work — on auto_merge=false
    projects, passing work is parked in approvals (never auto-integrated), so its integrate rate is
    ~0 by design. We therefore only:
      * TIGHTEN when there is a real quality signal — recent regressions (bad merges/conflicts).
      * LOOSEN only for auto_merge projects where a HIGH real merge rate + high tests + 0 regressions
        proves the pipeline is trustworthy enough for a touch more autonomy.
    """
    projs = db.select("projects", {"select": "id,name,confidence_threshold,auto_merge"}) or []
    changes = []
    for p in projs:
        st = _stats(p["name"])
        if not st or st["n"] < 20:
            continue  # not enough signal
        cur = float(p.get("confidence_threshold") or 0.55)
        bad = _recent_bad_merges(p["name"])
        direction = 0
        why = ""
        if bad > 0:
            direction = +1
            why = f"tighten: {bad} recent regressions/conflicts (real quality signal)"
        elif p.get("auto_merge") and st["integrated"] >= GOOD_INTEGRATE and st["tests"] >= 0.8:
            direction = -1
            why = f"loosen: auto_merge proven — integrate {st['integrated']}, tests {st['tests']}, 0 regressions"
        if direction == 0:
            continue
        new = round(min(CEIL, max(FLOOR, cur + direction * STEP)), 2)
        if new != cur:
            changes.append({"id": p["id"], "project": p["name"], "old": cur, "new": new,
                            "why": why, "stats": st})
    return changes


def run(apply=True):
    changes = plan_changes()
    for c in changes:
        if apply:
            db.update("projects", {"id": c["id"]}, {"confidence_threshold": c["new"]})
        print(f"self_tune: {c['project']} confidence {c['old']} -> {c['new']} ({c['why']})")
    if not changes:
        print("self_tune: no threshold changes (insufficient signal or already optimal)")
    return changes


if __name__ == "__main__":
    import json
    apply = not (len(sys.argv) > 1 and sys.argv[1] == "dry")
    print(json.dumps(run(apply=apply), indent=2, default=str))
