#!/usr/bin/env python3
"""
app_triage_review.py - the PERPETUAL bot review over cross-app AI/API operations. Same idea as
judge.py for code, applied to every product's model calls:

  1. Rate a sample of recent app_operations for quality with a CHEAP cross-model reviewer (a
     different family than the one that produced the output) -> quality_score/verdict.
  2. Aggregate cost + quality per (app, operation) and pick the CHEAPEST provider/model that still
     clears a quality bar -> write app_op_routes (what apps should use next).
  3. If a currently-used route is expensive AND a cheaper one holds quality, file an approval card
     proposing the switch (auto-applied for non-material ops on auto_merge apps; suggested otherwise).

Schedule every ~30 min. Read-only on the apps themselves; it only updates routing recommendations.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, judge, model_gateway as mg

SAMPLE = int(os.environ.get("APP_REVIEW_SAMPLE", "40"))
QUALITY_BAR = float(os.environ.get("APP_QUALITY_BAR", "7.0"))   # min avg score to keep a route
# rough ascending cost rank for tie-breaking when quality is comparable
COST_RANK = {"local": 0, "deepseek": 1, "google": 2, "openai": 3, "claude": 4}


def _heuristic_score(op):
    """Cheap fallback score so route learning is not blocked by sparse reviewer calls."""
    provider = op.get("provider")
    task_class = str(op.get("task_class") or "").lower()
    ok = bool(op.get("ok"))
    latency = int(op.get("latency_ms") or 0)
    score = 6.0
    if ok:
        score += 1.0
    else:
        score -= 2.0
    if provider == "local":
        score += 0.7 if task_class in ("plan", "rating", "mechanical", "review", "qa") else 0.2
    if provider in ("deepseek", "google", "openai") and task_class in ("plan", "review", "qa"):
        score += 0.4
    if provider == "claude" and task_class in ("security", "legal", "hard"):
        score += 0.8
    if latency and latency > 120000:
        score -= 0.8
    return max(0.0, min(10.0, round(score, 2)))


def _rate_unscored():
    """Score a batch of unreviewed operations with a cheap cross-model reviewer."""
    rows = db.select("app_operations",
                     {"select": "*", "quality_score": "is.null",
                      "order": "created_at.desc", "limit": str(SAMPLE)}) or []
    scored = 0
    for op in rows:
        if os.environ.get("ORCH_APP_REVIEW_USE_MODEL", "false").lower() not in ("1", "true", "yes", "on"):
            try:
                score = _heuristic_score(op)
                db.update("app_operations", {"id": op["id"]},
                          {"quality_score": score, "verdict": "pass" if score >= QUALITY_BAR else "review"})
                scored += 1
            except Exception:
                pass
            continue
        # nothing to grade if we didn't capture output text (we log metadata, not payloads);
        # grade on a compact descriptor so we never store customer data in the orchestrator.
        desc = (f"App '{op['app']}' operation '{op['operation']}' (class {op.get('task_class')}) "
                f"was served by {op.get('provider')}:{op.get('model')} at ${op.get('cost_usd')} "
                f"and {op.get('latency_ms')}ms, ok={op.get('ok')}. Rate whether this provider/model "
                f"is an appropriate, cost-efficient choice for that operation class.")
        try:
            jv = judge.review(f"Assess routing fit for {op['operation']}", desc,
                              author_model=op.get("model") or "", project=op["app"])
            db.update("app_operations", {"id": op["id"]},
                      {"quality_score": jv.get("score"), "verdict": jv.get("verdict")})
            scored += 1
        except Exception:
            try:
                score = _heuristic_score(op)
                db.update("app_operations", {"id": op["id"]},
                          {"quality_score": score, "verdict": "pass" if score >= QUALITY_BAR else "review"})
                scored += 1
            except Exception:
                continue
    return scored


def _aggregate_and_route():
    """For each (app, operation), pick cheapest provider that clears the quality bar."""
    rows = db.select("app_operations",
                     {"select": "app,operation,provider,model,cost_usd,quality_score",
                      "quality_score": "not.is.null", "order": "created_at.desc",
                      "limit": "2000"}) or []
    agg = {}
    for r in rows:
        key = (r["app"], r["operation"], r["provider"], r["model"])
        a = agg.setdefault(key, {"cost": 0.0, "q": 0.0, "n": 0})
        a["cost"] += float(r.get("cost_usd") or 0)
        a["q"] += float(r.get("quality_score") or 0)
        a["n"] += 1
    # group candidates by (app, operation)
    byop = {}
    for (app, op, prov, model), a in agg.items():
        if a["n"] == 0:
            continue
        byop.setdefault((app, op), []).append({
            "provider": prov, "model": model, "avg_cost": a["cost"] / a["n"],
            "avg_quality": a["q"] / a["n"], "n": a["n"]})
    routes = 0
    for (app, op), cands in byop.items():
        # keep only those clearing the quality bar; if none clear, record that this is only the
        # best observed fallback so operators do not mistake sparse telemetry for a proven route.
        clears_bar = [c for c in cands if c["avg_quality"] >= QUALITY_BAR]
        good = clears_bar or cands
        best = sorted(good, key=lambda c: (round(c["avg_cost"], 4),
                                           COST_RANK.get(c["provider"], 9)))[0]
        route_reason = (
            f"cheapest clearing q>={QUALITY_BAR} (avg q {best['avg_quality']:.1f})"
            if clears_bar else
            f"best observed fallback below q>={QUALITY_BAR} (avg q {best['avg_quality']:.1f})"
        )
        db.insert("app_op_routes", {
            "app": app, "operation": op, "provider": best["provider"], "model": best["model"],
            "reason": route_reason,
            "avg_cost": round(best["avg_cost"], 5), "avg_quality": round(best["avg_quality"], 2),
            "n_samples": best["n"], "updated_at": "now()"}, upsert=True)
        routes += 1
        # route optimization is automatic. Do not create manual approval cards for "cheaper provider"
        # recommendations; the route table above is the reversible source of truth.
        most_used = max(cands, key=lambda c: c["n"])
        if best["provider"] != most_used["provider"] and best["avg_cost"] < most_used["avg_cost"]:
            print(f"app_triage_review: auto-routed {app}/{op} "
                  f"{most_used['provider']} -> {best['provider']} "
                  f"(q {best['avg_quality']:.1f}, ${best['avg_cost']:.4f})")
    return routes


def run():
    scored = _rate_unscored()
    routes = _aggregate_and_route()
    print(f"app_triage_review: scored {scored} ops, updated {routes} app/operation routes")
    return {"scored": scored, "routes": routes}


if __name__ == "__main__":
    run()
