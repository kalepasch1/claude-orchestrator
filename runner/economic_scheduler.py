#!/usr/bin/env python3
"""
economic_scheduler.py - Revenue-focused task prioritization.

The fleet has multiple independent schedulers (ev_scheduler, marginal_value_scheduler, etc.)
that each optimize for different signals, but none explicitly optimize for REVENUE-GENERATING work.

This module scores QUEUED tasks by predicted revenue impact, routes revenue-critical work to fast
lanes, and deprioritizes speculative work if cost exceeds expected revenue delta.

Core functions:
  predict_revenue(task, ctx)    - estimates $/merge impact for a task
  cost_benefit(task, ctx)       - returns revenue/cost analysis with ROI
  score(task, ctx)              - combined economic score (deterministic, unit-testable)
  apply_routing(scored)         - route top revenue tasks to revenue-critical lane
  predict_revenue_bulk(tasks)   - bulk prediction for ev_scheduler context
  run()                         - daily job: compute revenue scoring, apply routing, log stats

Fail-soft throughout: missing revenue data returns 0 score, task stays queued but unprioritized.
Deterministic: same task+ctx → same score every time.
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Feature flag: disable by default, enable via ORCH_ECONOMIC_SCHEDULER_ENABLED=true
ENABLED = os.environ.get("ORCH_ECONOMIC_SCHEDULER_ENABLED", "false").lower() in ("true", "1", "yes")

# Cost/benefit threshold: only pursue work if predicted_revenue > (1.5 * estimated_cost)
ROI_THRESHOLD = float(os.environ.get("ORCH_ECONOMIC_ROI_THRESHOLD", "1.5"))

# Top N tasks routed to revenue-critical lane
TOP_REVENUE_TASKS = int(os.environ.get("ORCH_TOP_REVENUE_TASKS", "20"))

# Revenue keywords to boost
REVENUE_KEYWORDS = ("pricing", "payment", "stripe", "marketplace", "billing", "subscription",
                    "revenue", "monetization", "paywall", "purchase")

# Project tags that indicate high-growth/in-flight initiatives (radar_tag in approvals)
HIGH_GROWTH_TAGS = ("revenue-initiative", "high-growth", "strategic-growth", "priority-growth")


def predict_revenue(task, ctx):
    """
    Estimate $/merge impact for a task.

    Returns:
      {
        "point_estimate": float (USD),    # best guess at revenue delta
        "confidence_low": float (USD),    # lower bound
        "confidence_high": float (USD),   # upper bound
      }

    Fail-soft: missing revenue data returns 0 estimate, task stays queued but unprioritized.
    """
    if not task:
        return {"point_estimate": 0.0, "confidence_low": 0.0, "confidence_high": 0.0}

    try:
        project = task.get("project") or ""
        kind = (task.get("kind") or "").lower()
        prompt = (task.get("prompt") or "").lower()

        # Base: look up kind's historical avg_delta from kind_roi
        kind_roi = (ctx.get("surface_returns") or {}).get(kind, 0.0)
        point = max(0.0, float(kind_roi or 0))

        # Adjust: if project is high-growth/in-flight (via radar_tag), boost 2x
        high_growth_projects = ctx.get("high_growth_projects") or set()
        if project in high_growth_projects:
            point *= 2.0

        # Adjust: if task mentions revenue keywords, boost 1.5x
        if any(kw in prompt for kw in REVENUE_KEYWORDS):
            point *= 1.5

        # Adjust: if error_rate spike detected for this project, boost bugfix-kind tasks 1.5x
        app_signals = (ctx.get("app_signals") or {}).get(project, {})
        error_rate = float(app_signals.get("error_rate") or 0)
        if error_rate > 0.3 and kind in ("bugfix", "fix", "hotfix"):
            point *= 1.5

        # Confidence interval: ±25% around point estimate (conservative band)
        low = max(0.0, point * 0.75)
        high = point * 1.25

        return {
            "point_estimate": round(point, 2),
            "confidence_low": round(low, 2),
            "confidence_high": round(high, 2),
        }
    except Exception:
        return {"point_estimate": 0.0, "confidence_low": 0.0, "confidence_high": 0.0}


def cost_benefit(task, ctx):
    """
    Return revenue/cost analysis with ROI.

    Returns:
      {
        "predicted_revenue": float (USD),
        "estimated_cost": float (USD),
        "roi": float (ratio),
        "worthwhile": bool,  # True if predicted_revenue > (1.5 * estimated_cost)
      }

    Fail-soft: missing data returns sensible defaults.
    """
    if not task:
        return {
            "predicted_revenue": 0.0,
            "estimated_cost": 0.0,
            "roi": 0.0,
            "worthwhile": False,
        }

    try:
        project = task.get("project") or ""
        stats = (ctx.get("outcome_stats") or {}).get(project, {}) or {}
        estimated_cost = float(stats.get("avg_usd") or 0)

        rev = predict_revenue(task, ctx)
        predicted_revenue = rev.get("point_estimate", 0.0)

        if estimated_cost > 0:
            roi = predicted_revenue / estimated_cost
        else:
            roi = float("inf") if predicted_revenue > 0 else 0.0

        worthwhile = predicted_revenue > (ROI_THRESHOLD * estimated_cost)

        return {
            "predicted_revenue": round(predicted_revenue, 2),
            "estimated_cost": round(estimated_cost, 2),
            "roi": round(roi, 2) if roi != float("inf") else float("inf"),
            "worthwhile": worthwhile,
        }
    except Exception:
        return {
            "predicted_revenue": 0.0,
            "estimated_cost": 0.0,
            "roi": 0.0,
            "worthwhile": False,
        }


def score(task, ctx):
    """
    Combined economic score (deterministic, unit-testable).

    Formula:
      score = (predicted_revenue / estimated_cost) × (1 + success_rate) × kind_outcome_weight(ctx)

    Returns a float >= 0. Pure function: same task+ctx → same score every time.
    """
    if not task:
        return 0.0

    try:
        project = task.get("project") or ""
        stats = (ctx.get("outcome_stats") or {}).get(project, {}) or {}
        success_rate = float(stats.get("success_rate", 0.7))
        estimated_cost = float(stats.get("avg_usd") or 0) + 0.5  # avoid division by zero

        rev = predict_revenue(task, ctx)
        predicted_revenue = rev.get("point_estimate", 0.0)

        # Compute outcome weight (similar to ev_scheduler's outcome_weight)
        kind = (task.get("kind") or "").lower()
        family = (ctx.get("family_outcomes") or {}).get(kind, {})
        if family and family.get("total"):
            total = float(family["total"])
            merged_green = float(family.get("merged_green", 0))
            retries = float(family.get("retries", 0))
            rejected = float(family.get("rejected", 0))
            success = merged_green / total
            retry_drag = 1.0 - min(retries / (total * 3), 0.5)
            reject_drag = 1.0 - min(rejected / total, 0.5)
            kind_weight = max(success * retry_drag * reject_drag, 0.1)
        else:
            kind_weight = 1.0

        s = (predicted_revenue / estimated_cost) * (1.0 + success_rate) * kind_weight
        return round(max(0.0, s), 6)
    except Exception:
        return 0.0


def apply_routing(scored):
    """
    Route top revenue tasks to revenue-critical lane.

    Top TOP_REVENUE_TASKS revenue-predicted tasks get lane='revenue-critical' annotation.
    Create or update lane annotations as needed.

    Args:
      scored: [(score, task), ...] sorted desc by score

    Returns:
      {"routed": count, "lane": "revenue-critical"}

    Fail-soft: errors in routing don't block execution.
    """
    if not scored:
        return {"routed": 0, "lane": "revenue-critical"}

    routed = 0
    top_tasks = scored[:TOP_REVENUE_TASKS]

    for _, task in top_tasks:
        if not task or not task.get("id"):
            continue
        try:
            # Annotate task with revenue-critical lane
            db.update("tasks", {"id": task["id"]}, {
                "lane": "revenue-critical",
                "updated_at": "now()"
            })
            routed += 1
        except Exception:
            pass

    return {"routed": routed, "lane": "revenue-critical"}


def predict_revenue_bulk(tasks, ctx=None):
    """
    Bulk revenue prediction for ev_scheduler integration.

    Returns dict mapping task_id -> revenue_estimate (float USD).
    Used to feed economic signals back into app_signals context.
    """
    if ctx is None:
        ctx = _load_ctx()

    result = {}
    for task in (tasks or []):
        if task and task.get("id"):
            rev = predict_revenue(task, ctx)
            result[task["id"]] = rev.get("point_estimate", 0.0)
    return result


def _load_ctx():
    """
    Build the scoring context from db. Every read is fail-soft.

    Similar to ev_scheduler.load_ctx(), but adds economic-specific fields.
    """
    ctx = {
        "revenue_by_project": {},
        "surface_returns": {},
        "outcome_stats": {},
        "family_outcomes": {},
        "app_signals": {},
        "high_growth_projects": set(),
    }

    try:
        for r in db.select("app_revenue", {"select": "app,mrr_usd"}) or []:
            ctx["revenue_by_project"][r.get("app")] = float(r.get("mrr_usd") or 0)
    except Exception:
        pass

    try:
        agg = {}
        for r in db.select("outcomes", {"select": "project,usd,integrated", "limit": "5000"}) or []:
            a = agg.setdefault(r.get("project") or "?", [0.0, 0, 0])
            a[0] += float(r.get("usd") or 0)
            a[1] += 1
            a[2] += 1 if r.get("integrated") else 0
        for p, (usd, n, ok) in agg.items():
            if n:
                ctx["outcome_stats"][p] = {
                    "success_rate": ok / n,
                    "avg_usd": usd / n,
                }
    except Exception:
        pass

    try:
        agg = {}
        for r in db.select("merge_revenue", {"select": "kind,revenue_delta"}) or []:
            a = agg.setdefault((r.get("kind") or "?").lower(), [0.0, 0])
            a[0] += float(r.get("revenue_delta") or 0)
            a[1] += 1
        ctx["surface_returns"] = {k: v[0] / v[1] for k, v in agg.items() if v[1]}
    except Exception:
        pass

    try:
        # Load family_outcomes (kind-level outcome stats from learned merges)
        agg = {}
        for r in db.select("outcomes", {"select": "kind,integrated,transient_retries,human_rejected",
                                        "limit": "1000"}) or []:
            kind = (r.get("kind") or "?").lower()
            a = agg.setdefault(kind, {"merged_green": 0, "total": 0, "retries": 0, "rejected": 0})
            a["total"] += 1
            a["merged_green"] += 1 if r.get("integrated") else 0
            a["retries"] += int(r.get("transient_retries") or 0)
            a["rejected"] += 1 if r.get("human_rejected") else 0
        ctx["family_outcomes"] = agg
    except Exception:
        pass

    try:
        # Load app_signals (error_rate, usage_trend from telemetry_ingest)
        for r in db.select("app_telemetry", {"select": "app,error_rate,usage_trend"}) or []:
            app = r.get("app")
            if app:
                ctx["app_signals"][app] = {
                    "error_rate": float(r.get("error_rate") or 0),
                    "usage_trend": float(r.get("usage_trend") or 0),
                }
    except Exception:
        pass

    try:
        # Load high-growth projects (radar_tag in approvals)
        for r in db.select("approvals", {"select": "project,radar_tag",
                                         "radar_tag": "not.is.null",
                                         "status": "eq.approved"}) or []:
            radar_tag = (r.get("radar_tag") or "").lower()
            if any(tag in radar_tag for tag in HIGH_GROWTH_TAGS):
                ctx["high_growth_projects"].add(r.get("project"))
    except Exception:
        pass

    return ctx


def run():
    """
    Daily job: compute revenue scoring, apply routing, log stats.

    Returns:
      {
        "scored": count,
        "routed": count,
        "high_roi_count": count,
        "status": "success" | "disabled"
      }
    """
    if not ENABLED:
        return {"status": "disabled"}

    try:
        ctx = _load_ctx()
        tasks = db.select("tasks", {"select": "*", "state": "eq.QUEUED", "limit": str(500)}) or []

        # Score each task
        scored = [(score(t, ctx), t) for t in tasks]
        scored.sort(key=lambda p: (-p[0], p[1].get("created_at") or "", str(p[1].get("id"))))

        # Apply routing for top revenue tasks
        routed = apply_routing(scored)

        # Count high-ROI tasks
        high_roi_count = sum(1 for s, t in scored if cost_benefit(t, ctx)["worthwhile"])

        print(f"economic_scheduler: scored {len(scored)} queued tasks, "
              f"routed {routed['routed']} to revenue-critical lane, "
              f"high_roi_count={high_roi_count}")

        return {
            "scored": len(scored),
            "routed": routed["routed"],
            "high_roi_count": high_roi_count,
            "status": "success",
        }
    except Exception as e:
        print(f"economic_scheduler: error ({e})")
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
