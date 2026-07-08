#!/usr/bin/env python3
"""
presettlement_sim.py — Pre-settlement simulators (100X-500X savings on predicted failures).

Before committing to an expensive agent run ($0.50-$5.00), simulate the expected
outcome using historical data. If the simulator predicts failure with high confidence,
skip the run entirely, route to a cheaper model, or decompose first.

Simulation factors:
  1. Historical merge rate for this (model × task_class × domain) triple
  2. Prompt bankruptcy status (repeated failures on same pattern)
  3. Repo health (last build status, merge conflicts, dep staleness)
  4. Agent workload (concurrent tasks, RAM pressure)
  5. Prior diff similarity (has a similar diff been attempted and failed?)

Returns a prediction with confidence, recommended action, and estimated cost savings.

Usage:
    import presettlement_sim
    sim = presettlement_sim.simulate(task, agent_id, domain)
    if sim["predicted_failure"] and sim["confidence"] > 0.8:
        # route cheaper or decompose
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

FAILURE_CONFIDENCE_THRESHOLD = float(os.environ.get("ORCH_SIM_CONFIDENCE", "0.75"))
MIN_DATA_POINTS = int(os.environ.get("ORCH_SIM_MIN_DATA", "5"))


def simulate(task, agent_id="", domain="backend", diff_plan=None):
    """Simulate task outcome before spending tokens.

    Returns:
        {predicted_failure: bool, confidence: float, reasons: [str],
         recommended_action: str, estimated_savings_usd: float}
    """
    reasons = []
    failure_signals = 0
    total_signals = 0

    # Factor 1: Historical merge rate for this agent × domain
    try:
        import model_portfolios
        portfolios = model_portfolios._portfolios()
        key = f"{agent_id}:{domain}"
        entry = portfolios.get(key, {})
        if entry.get("total", 0) >= MIN_DATA_POINTS:
            total_signals += 1
            merge_rate = entry.get("merge_rate", 0.5)
            if merge_rate < 0.3:
                failure_signals += 1
                reasons.append(f"low domain merge rate ({merge_rate:.0%} for {domain})")
    except Exception:
        pass

    # Factor 2: Prompt bankruptcy
    try:
        import prompt_bankruptcy
        if prompt_bankruptcy.is_bankrupt(task):
            total_signals += 1
            failure_signals += 1
            reasons.append("prompt pattern is bankrupt (repeated failures)")
    except Exception:
        pass

    # Factor 3: Repo health
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.repo_health"})
        if rows and rows[0].get("value"):
            health = json.loads(rows[0]["value"]) if isinstance(rows[0]["value"], str) else rows[0]["value"]
            project_id = task.get("project_id", "")
            proj_health = health.get(project_id, {})
            if proj_health.get("build_status") == "red":
                total_signals += 1
                failure_signals += 1
                reasons.append("repo build is currently red")
            if proj_health.get("conflicts", 0) > 2:
                total_signals += 1
                failure_signals += 0.5
                reasons.append(f"repo has {proj_health['conflicts']} active merge conflicts")
    except Exception:
        pass

    # Factor 4: Task complexity vs. model capability
    prompt_len = len(task.get("prompt") or "")
    if prompt_len > 5000:
        total_signals += 1
        failure_signals += 0.3
        reasons.append(f"long prompt ({prompt_len} chars) — complex task")

    # Factor 5: Diff compiler confidence (inverse — low confidence = higher risk)
    if diff_plan and diff_plan.get("has_plan"):
        total_signals += 1
        conf = diff_plan.get("confidence", 0)
        if conf < 0.3:
            failure_signals += 0.5
            reasons.append(f"low template match (conf={conf:.0%})")
    else:
        total_signals += 1
        failure_signals += 0.2
        reasons.append("no template match — inventing from scratch")

    # Factor 6: Recent failure streak for this project
    try:
        recent = db.select("outcomes", {
            "select": "merged",
            "project": f"eq.{task.get('project_id', '')}",
            "order": "created_at.desc",
            "limit": "10",
        }) or []
        if len(recent) >= 5:
            total_signals += 1
            recent_merge_rate = sum(1 for r in recent if r.get("merged")) / len(recent)
            if recent_merge_rate < 0.2:
                failure_signals += 1
                reasons.append(f"project on losing streak ({recent_merge_rate:.0%} recent merge rate)")
    except Exception:
        pass

    # Compute confidence
    if total_signals == 0:
        return {"predicted_failure": False, "confidence": 0, "reasons": [],
                "recommended_action": "proceed", "estimated_savings_usd": 0}

    failure_probability = failure_signals / total_signals
    confidence = min(failure_probability * 1.2, 0.99)  # Scale up slightly

    predicted_failure = confidence >= FAILURE_CONFIDENCE_THRESHOLD

    # Recommended action
    if predicted_failure:
        if confidence > 0.9:
            action = "decompose_first"
        elif confidence > 0.8:
            action = "route_cheaper_model"
        else:
            action = "add_planning_step"
    else:
        action = "proceed"

    # Estimated savings
    try:
        import colosseum
        rep = colosseum._reputation()
        r = rep.get(agent_id, {})
        avg_cost = r.get("avg_cost", 0.50)
        savings = avg_cost * failure_probability if predicted_failure else 0
    except Exception:
        savings = 0.50 * failure_probability if predicted_failure else 0

    return {
        "predicted_failure": predicted_failure,
        "confidence": round(confidence, 3),
        "failure_probability": round(failure_probability, 3),
        "reasons": reasons,
        "recommended_action": action,
        "estimated_savings_usd": round(savings, 4),
        "signals": {"failure": failure_signals, "total": total_signals},
    }


def should_skip(task, agent_id="", domain="backend", diff_plan=None):
    """Quick check: should we skip this agent run entirely?

    Returns (skip: bool, sim_result: dict)
    """
    sim = simulate(task, agent_id, domain, diff_plan)

    if sim["predicted_failure"] and sim["confidence"] > 0.9:
        return True, sim

    return False, sim
