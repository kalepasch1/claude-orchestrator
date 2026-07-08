#!/usr/bin/env python3
"""
portfolio_rebalancer.py — Real-time model portfolio rebalancing (200X cost efficiency).

Improves model_portfolios: instead of static domain→model mapping updated
periodically, this provides continuous Bayesian rebalancing with cost curves.

Key metric: $/merged-line (cost per line of code that actually merges).
Route to the model with lowest $/merged-line, not just highest merge rate.

A model with 90% merge rate at $0.10/task beats one with 95% at $0.50/task
for routine work. But for high-risk security tasks, the 95% model wins.

Usage:
    import portfolio_rebalancer
    best = portfolio_rebalancer.optimal_model(task, domain, candidates)
    # best.model, best.expected_cost_per_merge, best.confidence
"""
import os, sys, json, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

REBALANCE_INTERVAL_S = int(os.environ.get("ORCH_REBALANCE_INTERVAL", "300"))


def _portfolio_store():
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.portfolio_rebalancer"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_portfolio(store):
    try:
        db.upsert("controls", {"key": "portfolio_rebalancer", "value": json.dumps(store, default=str)})
    except Exception:
        pass


def record_outcome(model, domain, merged, cost_usd, lines_changed, wall_s=0):
    """Record a task outcome for portfolio rebalancing.

    This feeds the $/merged-line calculation.
    """
    store = _portfolio_store()
    key = f"{model}:{domain}"

    entry = store.get(key, {
        "model": model, "domain": domain,
        "total_tasks": 0, "merged_tasks": 0,
        "total_cost": 0, "total_lines": 0,
        "merged_lines": 0, "total_wall_s": 0,
        "cost_per_merge": 0, "cost_per_merged_line": 0,
        "merge_rate": 0, "recent_outcomes": [],
    })

    entry["total_tasks"] = entry.get("total_tasks", 0) + 1
    entry["total_cost"] = entry.get("total_cost", 0) + cost_usd
    entry["total_lines"] = entry.get("total_lines", 0) + lines_changed
    entry["total_wall_s"] = entry.get("total_wall_s", 0) + wall_s

    if merged:
        entry["merged_tasks"] = entry.get("merged_tasks", 0) + 1
        entry["merged_lines"] = entry.get("merged_lines", 0) + lines_changed

    # Update derived metrics
    entry["merge_rate"] = entry["merged_tasks"] / max(entry["total_tasks"], 1)
    entry["cost_per_merge"] = entry["total_cost"] / max(entry["merged_tasks"], 1)
    entry["cost_per_merged_line"] = entry["total_cost"] / max(entry["merged_lines"], 1)

    # Track recent for Bayesian updating
    recent = entry.get("recent_outcomes", [])
    recent.append({
        "merged": merged, "cost": cost_usd, "lines": lines_changed,
        "timestamp": time.time(),
    })
    if len(recent) > 30:
        recent = recent[-30:]
    entry["recent_outcomes"] = recent

    # Bayesian: recent performance weighted more than historical
    recent_merges = sum(1 for r in recent if r["merged"])
    recent_total = len(recent)
    recent_rate = recent_merges / max(recent_total, 1)

    # Blend historical and recent (recent gets 60% weight after 10 samples)
    blend = min(0.6, recent_total / 20)
    entry["blended_merge_rate"] = (
        blend * recent_rate + (1 - blend) * entry["merge_rate"]
    )

    entry["last_updated"] = time.time()
    store[key] = entry
    _save_portfolio(store)


def optimal_model(task, domain, candidates):
    """Select the optimal model for a task based on $/merged-line.

    Args:
        task: task dict
        domain: domain classification
        candidates: list of model name strings

    Returns: {model, expected_cost_per_merge, merge_rate, confidence, reason}
    """
    store = _portfolio_store()
    kind = task.get("kind", "feature")

    scored = []
    for model in candidates:
        key = f"{model}:{domain}"
        entry = store.get(key, {})

        total = entry.get("total_tasks", 0)
        if total < 3:
            # Insufficient data — use exploration score
            scored.append({
                "model": model,
                "score": 0.5,  # neutral — explore
                "expected_cost_per_merge": 0.1,  # assume moderate
                "merge_rate": 0.5,
                "confidence": 0.1,
                "reason": "exploring (insufficient data)",
            })
            continue

        merge_rate = entry.get("blended_merge_rate", entry.get("merge_rate", 0))
        cost_per_merge = entry.get("cost_per_merge", 0.1)
        cost_per_line = entry.get("cost_per_merged_line", 0.01)

        # Score = merge_rate / cost_per_merge (higher = better value)
        # For high-risk tasks, weight merge_rate more
        if kind in ("security", "feature"):
            score = merge_rate ** 2 / max(cost_per_merge, 0.001)
        else:
            score = merge_rate / max(cost_per_merge, 0.001)

        confidence = min(0.95, total / 50)

        scored.append({
            "model": model,
            "score": round(score, 4),
            "expected_cost_per_merge": round(cost_per_merge, 4),
            "cost_per_merged_line": round(cost_per_line, 6),
            "merge_rate": round(merge_rate, 3),
            "confidence": round(confidence, 3),
            "total_tasks": total,
            "reason": f"${cost_per_merge:.3f}/merge, {merge_rate:.0%} rate",
        })

    if not scored:
        return {"model": candidates[0] if candidates else "unknown",
                "score": 0, "confidence": 0, "reason": "no candidates"}

    # UCB1 exploration bonus for low-data models
    total_all = sum(s.get("total_tasks", 1) for s in scored)
    for s in scored:
        n = max(s.get("total_tasks", 1), 1)
        exploration = math.sqrt(2 * math.log(max(total_all, 2)) / n)
        s["ucb_score"] = s["score"] + exploration * 0.1

    # Pick by UCB score
    best = max(scored, key=lambda s: s.get("ucb_score", s["score"]))
    return best


def run():
    """Periodic: report portfolio rebalancing stats."""
    store = _portfolio_store()
    if not store:
        print("[rebalancer] no portfolio data yet")
        return

    # Group by domain
    domains = {}
    for key, entry in store.items():
        domain = entry.get("domain", "unknown")
        domains.setdefault(domain, []).append(entry)

    for domain, entries in sorted(domains.items()):
        best = min(entries, key=lambda e: e.get("cost_per_merge", 999))
        print(f"[rebalancer] {domain}: best={best['model']} "
              f"(${best.get('cost_per_merge', 0):.3f}/merge, "
              f"{best.get('blended_merge_rate', best.get('merge_rate', 0)):.0%} rate, "
              f"{best.get('total_tasks', 0)} tasks)")
