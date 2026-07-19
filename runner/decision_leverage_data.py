#!/usr/bin/env python3
"""
decision_leverage_data.py - enrich decision briefs with concrete leverage data.

Pulls historical precedents, project outcomes, cost context, timing pressure,
and alternatives from the orchestrator's own databases so that decision briefs
(from decision_engine.py) contain real numbers instead of generic advice.

Usage:
    leverage = gather(approval_id)
    enriched = enrich_brief(brief_dict, leverage)

All functions fail soft: a database error returns empty/default data, never raises.
"""
import os, sys, json, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# ── Configuration ────────────────────────────────────────────────────────────
PRECEDENT_LIMIT = int(os.environ.get("ORCH_LEVERAGE_PRECEDENT_LIMIT", "20"))
OUTCOME_WINDOW_DAYS = int(os.environ.get("ORCH_LEVERAGE_OUTCOME_DAYS", "30"))
COST_VIEW = os.environ.get("ORCH_LEVERAGE_COST_VIEW", "v_provider_spend_mtd")

# ── Module statistics ────────────────────────────────────────────────────────
_stats = {"gather_calls": 0, "enrichments": 0, "cache_hits": 0, "errors": 0}
_cache = {}  # approval_id -> (timestamp, leverage_dict)
CACHE_TTL = int(os.environ.get("ORCH_LEVERAGE_CACHE_TTL", "300"))


def stats() -> dict:
    """Return module statistics: calls made, enrichments performed, cache hits."""
    return dict(_stats)


def _safe_select(table, params):
    """Wrapper around db.select that never raises."""
    try:
        return db.select(table, params) or []
    except Exception:
        _stats["errors"] += 1
        return []


def historical_precedents(project: str, category: str) -> list:
    """Query past decided approvals with a similar category to show what was decided before.

    Returns a list of dicts with keys: id, title, status, decision_type, decided_at, project.
    Useful for anchoring negotiations ("last time we faced X, we chose Y").
    """
    params = {
        "select": "id,title,status,decision_type,decision_text,decided_at,project",
        "status": "in.(approved,denied)",
        "order": "decided_at.desc",
        "limit": str(PRECEDENT_LIMIT),
    }
    if category:
        params["kind"] = f"eq.{category}"
    if project:
        params["project"] = f"eq.{project}"
    rows = _safe_select("approvals", params)
    return [
        {
            "id": r.get("id"),
            "title": r.get("title", ""),
            "status": r.get("status"),
            "decision_type": r.get("decision_type"),
            "decision_text": (r.get("decision_text") or "")[:200],
            "decided_at": r.get("decided_at"),
            "project": r.get("project"),
        }
        for r in rows
    ]


def related_outcomes(project: str) -> dict:
    """Get recent task outcomes to show project health/velocity as negotiation context.

    Returns a dict with keys: total, merged, failed, avg_duration_s, recent (last 10 outcomes).
    A healthy project with high velocity strengthens the negotiating position.
    """
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=OUTCOME_WINDOW_DAYS)).isoformat()
    params = {
        "select": "id,task_id,verdict,created_at,elapsed_s,usd",
        "order": "created_at.desc",
        "limit": "200",
        "created_at": f"gte.{cutoff}",
    }
    if project:
        params["project"] = f"eq.{project}"
    rows = _safe_select("outcomes", params)
    merged = [r for r in rows if r.get("verdict") == "merged"]
    failed = [r for r in rows if r.get("verdict") not in ("merged", None)]
    durations = [r["elapsed_s"] for r in rows if r.get("elapsed_s")]
    avg_dur = round(sum(durations) / len(durations), 1) if durations else 0
    return {
        "total": len(rows),
        "merged": len(merged),
        "failed": len(failed),
        "merge_rate": round(len(merged) / max(len(rows), 1) * 100, 1),
        "avg_duration_s": avg_dur,
        "window_days": OUTCOME_WINDOW_DAYS,
        "recent": rows[:10],
    }


def cost_context(project: str) -> dict:
    """Pull spend data to contextualize cost-related decisions.

    Tries the v_provider_spend_mtd view first (aggregated spend by provider);
    falls back to summing the outcomes.usd column directly.
    Returns: total_usd, by_provider (dict), task_count, avg_cost_per_task.
    """
    # Try the aggregated view first
    view_rows = _safe_select(COST_VIEW, {"select": "*"})
    if view_rows:
        total = sum(float(r.get("total_usd") or r.get("usd") or 0) for r in view_rows)
        by_provider = {}
        for r in view_rows:
            prov = r.get("provider") or "unknown"
            by_provider[prov] = by_provider.get(prov, 0) + float(r.get("total_usd") or r.get("usd") or 0)
        return {
            "source": COST_VIEW,
            "total_usd": round(total, 2),
            "by_provider": by_provider,
            "task_count": sum(int(r.get("task_count") or 0) for r in view_rows),
        }
    # Fallback: sum outcomes.usd
    params = {"select": "usd,task_id", "usd": "not.is.null"}
    if project:
        params["project"] = f"eq.{project}"
    rows = _safe_select("outcomes", params)
    costs = [float(r.get("usd") or 0) for r in rows if r.get("usd")]
    total = sum(costs)
    avg = round(total / len(costs), 4) if costs else 0
    return {
        "source": "outcomes",
        "total_usd": round(total, 2),
        "by_provider": {},
        "task_count": len(costs),
        "avg_cost_per_task": avg,
    }


def timing_leverage(approval: dict) -> dict:
    """Analyze timing factors that create urgency or patience leverage.

    Checks: how long the decision has been pending, whether related tasks are
    blocked, and if there are deadline signals in the approval metadata.
    Returns: pending_hours, blocked_tasks (count), urgency (low/medium/high),
    timing_advantage (description).
    """
    created = approval.get("created_at") or approval.get("inserted_at")
    pending_hours = 0
    if created:
        try:
            if isinstance(created, str):
                # Handle ISO format, strip trailing Z
                clean = created.replace("Z", "+00:00")
                if "+" not in clean and "T" in clean:
                    clean += "+00:00"
                ct = datetime.datetime.fromisoformat(clean)
                ct = ct.replace(tzinfo=None)
            else:
                ct = created
            pending_hours = round((datetime.datetime.utcnow() - ct).total_seconds() / 3600, 1)
        except Exception:
            pass

    # Check for blocked tasks referencing this approval
    blocked_count = 0
    aid = approval.get("id")
    if aid:
        blocked = _safe_select("tasks", {
            "select": "id",
            "state": "eq.BLOCKED",
            "limit": "50",
        })
        # Filter for tasks whose deps or prompt mention this approval
        blocked_count = len([t for t in blocked if str(aid) in json.dumps(t)])

    # Determine urgency
    urgency = "low"
    if pending_hours > 72 or blocked_count > 3:
        urgency = "high"
    elif pending_hours > 24 or blocked_count > 0:
        urgency = "medium"

    # Timing advantage analysis
    advantage = "No time pressure — negotiate from patience."
    if urgency == "high":
        advantage = (f"Decision pending {pending_hours:.0f}h with {blocked_count} blocked task(s). "
                     "Delays compound — act or explicitly defer.")
    elif urgency == "medium":
        advantage = (f"Pending {pending_hours:.0f}h. Some downstream work waiting. "
                     "Moderate pressure to decide, but not urgent enough to accept bad terms.")

    return {
        "pending_hours": pending_hours,
        "blocked_tasks": blocked_count,
        "urgency": urgency,
        "timing_advantage": advantage,
    }


def gather(approval_id: str) -> dict:
    """Main entry point. Collect all leverage data for a given approval/decision.

    Returns a dict with keys: historical_precedents, related_outcomes,
    cost_context, timing_leverage, alternatives.
    Results are cached for CACHE_TTL seconds.
    """
    _stats["gather_calls"] += 1

    # Check cache
    if approval_id in _cache:
        ts, cached = _cache[approval_id]
        if time.time() - ts < CACHE_TTL:
            _stats["cache_hits"] += 1
            return cached

    # Fetch the approval record
    rows = _safe_select("approvals", {"select": "*", "id": f"eq.{approval_id}"})
    approval = rows[0] if rows else {}
    project = approval.get("project") or ""
    category = approval.get("kind") or ""

    result = {
        "historical_precedents": historical_precedents(project, category),
        "related_outcomes": related_outcomes(project),
        "cost_context": cost_context(project),
        "timing_leverage": timing_leverage(approval),
        "alternatives": _find_alternatives(approval),
    }

    _cache[approval_id] = (time.time(), result)
    return result


def _find_alternatives(approval: dict) -> list:
    """Find alternative approaches based on similar past decisions that chose differently.

    Looks for approved decisions with different decision_types for the same kind of issue.
    """
    kind = approval.get("kind") or ""
    if not kind:
        return []
    rows = _safe_select("approvals", {
        "select": "id,title,decision_type,decision_text,status",
        "kind": f"eq.{kind}",
        "status": "eq.approved",
        "order": "decided_at.desc",
        "limit": "10",
    })
    seen_types = set()
    alts = []
    for r in rows:
        dt = r.get("decision_type") or "approve"
        if dt not in seen_types:
            seen_types.add(dt)
            alts.append({
                "decision_type": dt,
                "example_title": r.get("title", ""),
                "example_text": (r.get("decision_text") or "")[:200],
            })
    return alts


def enrich_brief(brief: dict, leverage: dict) -> dict:
    """Merge leverage data into a decision brief from decision_engine.py.

    Adds concrete numbers to the negotiation section, appends precedent
    context to scenarios, and injects cost/timing data.
    Returns a new dict (does not mutate the original).
    """
    _stats["enrichments"] += 1
    enriched = dict(brief)

    # Enrich negotiation section with concrete leverage
    neg = dict(enriched.get("negotiation") or {})
    timing = leverage.get("timing_leverage") or {}
    precedents = leverage.get("historical_precedents") or []
    costs = leverage.get("cost_context") or {}
    outcomes = leverage.get("related_outcomes") or {}

    # Add timing pressure to leverage
    if timing.get("timing_advantage"):
        existing = neg.get("leverage") or ""
        neg["leverage"] = f"{existing} | Timing: {timing['timing_advantage']}".strip(" |")

    # Add cost context to BATNA
    if costs.get("total_usd"):
        existing_batna = neg.get("batna") or ""
        neg["batna"] = (f"{existing_batna} | Cost context: ${costs['total_usd']:.2f} "
                        f"total spend ({costs.get('task_count', 0)} tasks).").strip(" |")

    # Add precedent to counter-move
    if precedents:
        last = precedents[0]
        existing_counter = neg.get("counter") or ""
        prec_note = f"Precedent: '{last['title']}' was {last['status']}"
        neg["counter"] = f"{existing_counter} | {prec_note}".strip(" |")

    enriched["negotiation"] = neg

    # Add project health to a new section
    if outcomes.get("total"):
        enriched["project_health"] = {
            "merge_rate": f"{outcomes['merge_rate']}%",
            "tasks_in_window": outcomes["total"],
            "avg_duration_s": outcomes["avg_duration_s"],
        }

    # Add timing metadata
    enriched["timing"] = timing

    # Add alternatives section
    alts = leverage.get("alternatives") or []
    if alts:
        enriched["alternative_approaches"] = alts

    return enriched


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1:
        aid = _sys.argv[1]
        lev = gather(aid)
        print(json.dumps(lev, indent=2, default=str))
    else:
        print("Usage: python3 decision_leverage_data.py <approval_id>")
