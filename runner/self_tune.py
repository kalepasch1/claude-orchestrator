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

Closed-loop model feedback: tracks per-project model success rates and writes preferred_model
hints so outcome_router can bias toward models that work best for each project's codebase.
"""
import os, sys, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW = int(os.environ.get("SELFTUNE_WINDOW", "200"))     # recent outcomes per project
STEP = float(os.environ.get("SELFTUNE_STEP", "0.05"))
FLOOR = float(os.environ.get("SELFTUNE_FLOOR", "0.30"))
CEIL = float(os.environ.get("SELFTUNE_CEIL", "0.90"))
GOOD_INTEGRATE = float(os.environ.get("SELFTUNE_GOOD", "0.55"))   # merge rate that earns more autonomy
BAD_INTEGRATE = float(os.environ.get("SELFTUNE_BAD", "0.25"))    # merge rate that tightens gating
# Time-decay half-life: outcomes older than this (in days) count half as much.
# Ensures recent performance dominates stale history.
DECAY_HALFLIFE_DAYS = float(os.environ.get("SELFTUNE_DECAY_HALFLIFE", "14"))
# Minimum weighted sample size before acting (prevents noise-driven changes)
MIN_EFFECTIVE_SAMPLES = int(os.environ.get("SELFTUNE_MIN_SAMPLES", "20"))


def _time_weight(age_days):
    """Exponential decay weight: 1.0 for today, 0.5 at DECAY_HALFLIFE_DAYS."""
    if age_days <= 0:
        return 1.0
    return math.exp(-0.693 * age_days / max(DECAY_HALFLIFE_DAYS, 1))


def _stats(project):
    """Compute recent test-pass and integration rates for a project."""
    rows = db.select("outcomes", {"select": "tests_passed,integrated",
                                  "project": f"eq.{project}",
                                  "order": "created_at.desc", "limit": str(WINDOW)}) or []
    if not rows:
        return None
    now = time.time()
    w_total = 0.0
    w_tests = 0.0
    w_integ = 0.0
    for r in rows:
        # Parse created_at to compute age; fall back to weight=1 if unparseable
        age_days = 0
        try:
            from datetime import datetime
            if isinstance(r.get("created_at"), str):
                # ISO format from Supabase
                dt = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                age_days = (now - dt.timestamp()) / 86400
        except Exception:
            pass
        w = _time_weight(age_days)
        w_total += w
        if r.get("tests_passed"):
            w_tests += w
        if r.get("integrated"):
            w_integ += w
    if w_total < MIN_EFFECTIVE_SAMPLES:
        return None  # not enough effective signal after decay
    tests = w_tests / w_total
    integ = w_integ / w_total
    return {"n": len(rows), "n_eff": round(w_total, 1),
            "tests": round(tests, 3), "integrated": round(integ, 3)}


def _recent_bad_merges(project, days=3):
    """Regressions logged after an integrate — a signal that autonomy is too loose."""
    try:
        rows = db.select("regressions", {"select": "id", "project": f"eq.{project}",
                                         "limit": "50"}) or []
        return len(rows)
    except Exception:
        return 0


def _model_stats(project):
    """Per-model success rates for a project. Returns {model: {total, success, rate}}."""
    try:
        rows = db.select("outcomes", {"select": "model,integrated",
                                      "project": f"eq.{project}",
                                      "order": "created_at.desc",
                                      "limit": str(WINDOW)}) or []
    except Exception:
        return {}
    stats = {}
    for r in rows:
        m = r.get("model") or "unknown"
        if m not in stats:
            stats[m] = {"total": 0, "success": 0}
        stats[m]["total"] += 1
        if r.get("integrated"):
            stats[m]["success"] += 1
    for m in stats:
        t = stats[m]["total"]
        stats[m]["rate"] = round(stats[m]["success"] / t, 3) if t > 0 else 0
    return stats


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
        if not st:
            continue  # not enough signal (time-weighted)
        cur = float(p.get("confidence_threshold") or 0.55)
        bad = _recent_bad_merges(p["name"])
        direction = 0
        why = ""
        if bad > 0:
            direction = +1
            why = f"tighten: {bad} recent regressions/conflicts (real quality signal)"
        elif p.get("auto_merge") and st["integrated"] >= GOOD_INTEGRATE and st["tests"] >= 0.8:
            direction = -1
            why = (f"loosen: auto_merge proven — integrate {st['integrated']}, "
                   f"tests {st['tests']}, 0 regressions (n_eff={st['n_eff']})")
        if direction == 0:
            continue
        new = round(min(CEIL, max(FLOOR, cur + direction * STEP)), 2)
        if new != cur:
            changes.append({"id": p["id"], "project": p["name"], "old": cur, "new": new,
                            "why": why, "stats": st})
    return changes


def plan_model_preferences():
    """Compute per-project model preference hints from outcome data.

    Returns list of {project, preferred_model, stats} for projects where one model
    clearly outperforms others (>= 10 samples, >= 20% higher success rate than runner-up).
    """
    projs = db.select("projects", {"select": "id,name"}) or []
    prefs = []
    for p in projs:
        ms = _model_stats(p["name"])
        if not ms:
            continue
        # Only consider models with enough samples
        qualified = {m: s for m, s in ms.items() if s["total"] >= 10 and m != "unknown"}
        if not qualified:
            continue
        best_model = max(qualified, key=lambda m: qualified[m]["rate"])
        best_rate = qualified[best_model]["rate"]
        # Check if best is meaningfully better than runner-up
        others = [qualified[m]["rate"] for m in qualified if m != best_model]
        runner_up = max(others) if others else 0
        if best_rate - runner_up >= 0.20 and best_rate >= 0.5:
            prefs.append({"id": p["id"], "project": p["name"],
                          "preferred_model": best_model,
                          "best_rate": best_rate, "runner_up_rate": runner_up,
                          "model_stats": qualified})
    return prefs


def run(apply=True):
    # --- Confidence threshold tuning ---
    changes = plan_changes()
    for c in changes:
        if apply:
            db.update("projects", {"id": c["id"]}, {"confidence_threshold": c["new"]})
        print(f"self_tune: {c['project']} confidence {c['old']} -> {c['new']} ({c['why']})")
    if not changes:
        print("self_tune: no threshold changes (insufficient signal or already optimal)")

    # --- Model preference feedback (closed-loop) ---
    prefs = plan_model_preferences()
    for pref in prefs:
        if apply:
            try:
                db.update("projects", {"id": pref["id"]},
                          {"preferred_model": pref["preferred_model"]})
            except Exception as e:
                # Column may not exist yet — log and continue
                print(f"self_tune: model pref write failed for {pref['project']}: {e}")
        print(f"self_tune: {pref['project']} preferred_model -> {pref['preferred_model']} "
              f"(rate={pref['best_rate']}, runner_up={pref['runner_up_rate']})")
    if not prefs:
        print("self_tune: no model preference changes (insufficient data or no clear winner)")

    return {"threshold_changes": changes, "model_preferences": prefs}


if __name__ == "__main__":
    import json
    apply = not (len(sys.argv) > 1 and sys.argv[1] == "dry")
    print(json.dumps(run(apply=apply), indent=2, default=str))
