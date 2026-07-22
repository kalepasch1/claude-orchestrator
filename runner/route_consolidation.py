"""
route_consolidation.py — evaluate and consolidate overlapping routing decision points.

The orchestrator has three routing decision points: bandit.py, model_router.py, and
agentic_coders.py's pick(). This module provides a unified entry point that delegates
to the most appropriate one, avoiding conflicts and redundant computation.
"""
import os, sys, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)


def unified_route(task, available_coders, stage=None):
    """Single routing entry point that consolidates bandit, model_router, and pick().

    Priority:
    1. router_stats (learned empirical routing) — most data, most reliable
    2. agentic_coders.pick() — cost x capability x difficulty
    3. bandit exploration — when samples are insufficient

    Args:
        task: task dict with kind, slug, project_id, confidence, etc.
        available_coders: list of available coder names
        stage: optional pipeline stage override

    Returns:
        (coder_name, routing_source) tuple
    """
    kind = str(task.get("kind") or "build").lower()
    slug = str(task.get("slug") or "")

    # 1. Try learned router first (has the most empirical signal)
    try:
        import router_stats
        learned = router_stats.best_coder(kind, available_coders, stage=stage)
        if learned:
            log.debug("route_consolidation: learned router picked %s for %s", learned, slug)
            return learned, "router_stats"
    except Exception as e:
        log.debug("route_consolidation: router_stats failed: %s", e)

    # 2. Try agentic_coders.pick() (cost x capability x difficulty)
    try:
        import agentic_coders
        if hasattr(agentic_coders, "pick"):
            picked = agentic_coders.pick(task, available_coders)
            if picked and isinstance(picked, str):
                log.debug("route_consolidation: agentic_coders.pick chose %s for %s", picked, slug)
                return picked, "agentic_coders.pick"
    except Exception as e:
        log.debug("route_consolidation: agentic_coders.pick failed: %s", e)

    # 3. Bandit exploration fallback
    try:
        import bandit
        if hasattr(bandit, "select"):
            selected = bandit.select(kind, available_coders)
            if selected:
                log.debug("route_consolidation: bandit selected %s for %s", selected, slug)
                return selected, "bandit"
    except Exception as e:
        log.debug("route_consolidation: bandit failed: %s", e)

    # 4. Ultimate fallback: first available
    default = available_coders[0] if available_coders else "claude"
    log.debug("route_consolidation: falling back to %s for %s", default, slug)
    return default, "fallback"


def routing_diagnosis(task, available_coders, stage=None):
    """Run all three routers and compare their picks for diagnostics."""
    results = {}

    try:
        import router_stats
        results["router_stats"] = router_stats.best_coder(
            str(task.get("kind") or "build"), available_coders, stage=stage)
    except Exception as e:
        results["router_stats"] = f"error: {e}"

    try:
        import agentic_coders
        if hasattr(agentic_coders, "pick"):
            results["agentic_coders"] = agentic_coders.pick(task, available_coders)
    except Exception as e:
        results["agentic_coders"] = f"error: {e}"

    try:
        import bandit
        if hasattr(bandit, "select"):
            results["bandit"] = bandit.select(str(task.get("kind") or "build"), available_coders)
    except Exception as e:
        results["bandit"] = f"error: {e}"

    # Check agreement
    picks = [v for v in results.values() if isinstance(v, str) and not v.startswith("error")]
    results["agreement"] = len(set(picks)) <= 1 if picks else None
    results["unified_pick"] = unified_route(task, available_coders, stage)

    return results


if __name__ == "__main__":
    import json
    task = {"kind": "build", "slug": "test-task", "project_id": "test"}
    coders = ["claude", "deepseek", "openai"]
    coder, source = unified_route(task, coders)
    print(f"Unified route: {coder} (via {source})")
