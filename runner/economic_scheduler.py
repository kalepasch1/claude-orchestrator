#!/usr/bin/env python3
"""
economic_scheduler.py - Revenue-focused task prioritization. Scores queued tasks by predicted
revenue impact, routes high-ROI work to fast lanes, and deprioritizes speculative work if cost
exceeds expected revenue delta.

Key functions:
  predict_revenue(task, ctx)    - estimates $/merge impact for a task (returns float USD)
  cost_benefit(task, ctx)       - returns {"predicted_revenue": USD, "estimated_cost": USD,
                                          "roi": ratio, "worthwhile": bool}
  score(task, ctx)              - combined economic score (deterministic, unit-testable)
  apply_routing(scored)         - route top revenue tasks to high-priority lane
  run()                         - daily job: compute revenue scoring, apply routing, log stats

Integrates with revenue_attribution.kind_roi() for historical revenue-per-kind data.
Feeds back to ev_scheduler's context so economic signals inform all prioritization.
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import revenue_attribution

ENABLED = os.environ.get("ORCH_ECONOMIC_SCHEDULER_ENABLED", "false").lower() in ("true", "1", "yes")
ROI_THRESHOLD = float(os.environ.get("ORCH_ROI_THRESHOLD", "1.5"))  # only pursue if 1.5x ROI
REVENUE_CRITICAL_LANE_SIZE = int(os.environ.get("ORCH_REVENUE_CRITICAL_LANE_SIZE", "20"))
REVENUE_KEYWORDS = ("pricing", "payment", "stripe", "marketplace", "billing", "revenue", "monetize")


def load_ctx():
    """Build economic context from db. Every read is fail-soft."""
    ctx = {
        "kind_roi": {},
        "high_growth_projects": set(),
        "error_rates": {},
    }
    try:
        ctx["kind_roi"] = revenue_attribution.kind_roi() or {}
    except Exception:
        pass
    try:
        for r in db.select("approvals", {"select": "slug,radar_tag",
                                         "radar_tag": "not.is.null",
                                         "status": "eq.approved"}) or []:
            tag = (r.get("radar_tag") or "").lower()
            if "high-growth" in tag or "in-flight-initiative" in tag:
                slug = r.get("slug")
                if slug:
                    ctx["high_growth_projects"].add(slug)
    except Exception:
        pass
    try:
        for r in db.select("app_telemetry", {"select": "app,error_rate"}) or []:
            app = r.get("app")
            if app:
                ctx["error_rates"][app] = float(r.get("error_rate") or 0)
    except Exception:
        pass
    return ctx


def predict_revenue(task, ctx):
    """Estimate $/merge impact for a task.

    Returns: (point_estimate, low_bound, high_bound) in USD

    Base: look up kind's historical avg_delta from revenue_attribution.kind_roi()
    Adjust: if project is "high-growth" or "in-flight initiative", boost 2x
    Adjust: if task mentions revenue keywords, boost 1.5x
    Adjust: if error_rate spike detected, boost bugfix-kind tasks 1.5x
    Cap at $0 if no revenue signal; return confidence interval [low, high]
    """
    ctx = ctx if ctx is not None else load_ctx()

    project = task.get("project") or ""
    kind = (task.get("kind") or "").lower()
    prompt = (task.get("prompt") or "").lower()

    # Base: historical avg_delta for this kind
    base_revenue = float((ctx.get("kind_roi") or {}).get(kind, 0) or 0)
    estimate = max(0.0, base_revenue)

    # Boost for high-growth projects
    if project in (ctx.get("high_growth_projects") or set()):
        estimate *= 2.0

    # Boost for revenue-critical keywords
    if any(w in prompt for w in REVENUE_KEYWORDS):
        estimate *= 1.5

    # Boost bugfix tasks if error rate spike
    error_rate = float((ctx.get("error_rates") or {}).get(project, 0) or 0)
    if error_rate > 0.3 and kind in ("bugfix", "fix", "hotfix"):
        estimate *= 1.5

    # Confidence interval: ±20% around the estimate (wider if no data)
    if base_revenue == 0:
        low, high = 0.0, estimate
    else:
        low = estimate * 0.8
        high = estimate * 1.2

    return estimate, low, high


def cost_benefit(task, ctx):
    """Returns {"predicted_revenue": USD, "estimated_cost": USD, "roi": ratio, "worthwhile": bool}.

    worthwhile = predicted_revenue > (ROI_THRESHOLD × estimated_cost)
    """
    ctx = ctx if ctx is not None else load_ctx()

    predicted_revenue, _, _ = predict_revenue(task, ctx)
    estimated_cost = float(task.get("usd") or 0)

    # Avoid division by zero
    if estimated_cost <= 0:
        estimated_cost = 1.0

    roi = predicted_revenue / estimated_cost if estimated_cost > 0 else 0.0
    worthwhile = predicted_revenue > (ROI_THRESHOLD * estimated_cost)

    return {
        "predicted_revenue": round(predicted_revenue, 2),
        "estimated_cost": round(estimated_cost, 2),
        "roi": round(roi, 2),
        "worthwhile": worthwhile,
    }


def score(task, ctx):
    """Combined economic score (deterministic, unit-testable).

    = (predicted_revenue / estimated_cost) × (1 + success_rate) × kind_outcome_weight(ctx)

    Matches ev_scheduler's pure + deterministic pattern.
    """
    ctx = ctx if ctx is not None else load_ctx()

    predicted_revenue, _, _ = predict_revenue(task, ctx)
    estimated_cost = float(task.get("usd") or 0)

    if estimated_cost <= 0:
        estimated_cost = 1.0

    # Base score: ROI
    s = (predicted_revenue / estimated_cost) if estimated_cost > 0 else predicted_revenue

    # Success rate boost (assume 0.7 baseline if not specified)
    success_rate = float(task.get("success_rate") or 0.7)
    s *= (1.0 + success_rate)

    # Kind outcome weight (future: integrate with outcome_stats from ev_scheduler context)
    # For now, neutral (1.0)
    s *= 1.0

    return s


def predict_revenue_bulk(tasks, ctx=None):
    """Batch predict revenue for multiple tasks. Used by ev_scheduler.load_ctx()."""
    ctx = ctx if ctx is not None else load_ctx()
    results = {}
    for task in tasks or []:
        task_id = task.get("id")
        if task_id:
            results[task_id] = predict_revenue(task, ctx)[0]  # point estimate
    return results


def apply_routing(scored):
    """Route top revenue tasks to high-priority lane.

    Top REVENUE_CRITICAL_LANE_SIZE revenue-predicted tasks get lane="revenue-critical"
    annotation (create or update lane if needed).

    scored: list of (score, task) tuples, sorted descending by score
    """
    if not ENABLED:
        return {"routed": 0}

    # Sort by score descending
    scored_copy = sorted(scored or [], key=lambda x: -x[0])[:REVENUE_CRITICAL_LANE_SIZE]

    routed = 0
    for score_val, task in scored_copy:
        task_id = task.get("id")
        if not task_id:
            continue
        try:
            # Annotate task with revenue-critical lane
            db.update("tasks", {"id": task_id},
                     {"lane": "revenue-critical", "economic_score": round(float(score_val), 4)})
            routed += 1
        except Exception:
            # Fail-soft: skip if update fails
            pass

    return {"routed": routed, "lane": "revenue-critical", "top_n": REVENUE_CRITICAL_LANE_SIZE}


def run():
    """Daily job: compute revenue scoring, apply routing, log stats."""
    if not ENABLED:
        return {"status": "disabled", "message": "ORCH_ECONOMIC_SCHEDULER_ENABLED is false"}

    ctx = load_ctx()

    try:
        # Fetch queued tasks
        tasks = db.select("tasks", {"select": "*", "state": "eq.QUEUED",
                                    "limit": "500"}) or []

        if not tasks:
            return {"status": "success", "tasks_scored": 0, "routed": 0}

        # Score each task
        scored = []
        for task in tasks:
            try:
                task_score = score(task, ctx)
                scored.append((task_score, task))
            except Exception:
                # Fail-soft: skip scoring errors
                pass

        # Sort descending by score
        scored.sort(key=lambda x: -x[0])

        # Apply routing
        routing_result = apply_routing(scored)

        # Compute statistics
        cb_results = []
        worthwhile_count = 0
        total_revenue = 0.0
        for _, task in scored[:50]:
            try:
                cb = cost_benefit(task, ctx)
                cb_results.append(cb)
                if cb["worthwhile"]:
                    worthwhile_count += 1
                total_revenue += cb["predicted_revenue"]
            except Exception:
                pass

        stats = {
            "status": "success",
            "tasks_scored": len(scored),
            "routed": routing_result["routed"],
            "worthwhile_count": worthwhile_count,
            "total_revenue_predicted": round(total_revenue, 2),
            "avg_roi_top50": round(sum(cb["roi"] for cb in cb_results) / len(cb_results), 2) if cb_results else 0,
        }

        return stats

    except Exception as e:
        # Fail-soft: return error context without raising
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result, indent=2, default=str))
