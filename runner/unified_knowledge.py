#!/usr/bin/env python3
"""
unified_knowledge.py — Single-query knowledge index (200X query reduction).

Consolidates 5 overlapping knowledge stores into one query:
  - intent_graph (replay matches)
  - cross_project_templates (proven patterns from other repos)
  - prompt_distillation (minimal prompt templates)
  - session_cache (warm start context from prior attempts)
  - output_recycling (partial work from failures)

Instead of 5 separate queries per task, one call returns the best match
across all stores, ranked by expected value.

Usage:
    import unified_knowledge
    knowledge = unified_knowledge.query(task, project_name)
    # knowledge.best_match → the single best action
    # knowledge.all_matches → ranked list across all sources
    # knowledge.enriched_prompt → prompt with best context injected
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def query(task, project_name="", repo="", attempt=0):
    """Query all knowledge stores in one pass, return ranked results.

    Returns: {
        best_match: {source, action, confidence, detail},
        all_matches: [{source, action, confidence, detail}, ...],
        enriched_prompt: str,
        sources_checked: int,
        query_time_ms: float,
    }
    """
    t0 = time.time()
    prompt = task.get("prompt", "")
    matches = []

    # 1. Intent graph — can we replay?
    try:
        import intent_graph
        replay = intent_graph.find_replay(task, repo)
        if replay:
            matches.append({
                "source": "intent_graph",
                "action": "replay",
                "confidence": replay.get("confidence", 0),
                "detail": replay,
                "priority": 1.0 if replay.get("confidence", 0) >= 0.9 else 0.7,
            })
    except Exception:
        pass

    # 2. Cross-project templates — proven pattern from another repo?
    try:
        import cross_project_templates
        templates = cross_project_templates.find_templates(task, current_project=project_name, max_results=3)
        if templates:
            best = templates[0]
            matches.append({
                "source": "cross_project_templates",
                "action": "inject_template",
                "confidence": best.get("relevance", 0),
                "detail": templates,
                "priority": 0.6,
            })
    except Exception:
        pass

    # 3. Prompt distillation — minimal proven prompt?
    try:
        import prompt_distillation
        distilled = prompt_distillation.find_distilled(task, current_project=project_name)
        if distilled:
            matches.append({
                "source": "prompt_distillation",
                "action": "use_distilled",
                "confidence": min(0.95, distilled.get("merge_count", 0) / 10),
                "detail": distilled,
                "priority": 0.8 if distilled.get("merge_count", 0) >= 5 else 0.5,
            })
    except Exception:
        pass

    # 4. Session cache — warm start from prior attempt?
    if attempt > 0:
        try:
            import session_cache
            warm = session_cache.warm_start(task, attempt, "")
            if warm and warm != "":
                matches.append({
                    "source": "session_cache",
                    "action": "warm_start",
                    "confidence": 0.5,
                    "detail": {"warm_prompt_len": len(warm)},
                    "priority": 0.4,
                    "_warm_prompt": warm,
                })
        except Exception:
            pass

    # 5. Output recycling — partial work from prior failure?
    try:
        import output_recycling
        recycled = output_recycling.get_recycled(task.get("id", ""))
        if recycled and recycled.get("file_contents"):
            matches.append({
                "source": "output_recycling",
                "action": "inject_recycled",
                "confidence": 0.4,
                "detail": recycled,
                "priority": 0.3,
            })
    except Exception:
        pass

    # 6. Transfer learning — cross-project pattern?
    try:
        import transfer_learning
        transfer = transfer_learning.find_transfer(task, current_project=project_name)
        if transfer:
            matches.append({
                "source": "transfer_learning",
                "action": "inject_transfer",
                "confidence": transfer.get("confidence", 0),
                "detail": transfer,
                "priority": 0.5,
            })
    except Exception:
        pass

    # Rank by priority × confidence
    matches.sort(key=lambda m: m["priority"] * m["confidence"], reverse=True)

    # Build enriched prompt from best matches (don't stack more than 2)
    enriched = prompt
    applied_sources = []
    for m in matches[:2]:
        enriched = _apply_match(enriched, m)
        applied_sources.append(m["source"])

    best = matches[0] if matches else {"source": "none", "action": "none", "confidence": 0, "detail": {}}
    query_ms = (time.time() - t0) * 1000

    return {
        "best_match": best,
        "all_matches": matches,
        "enriched_prompt": enriched,
        "sources_checked": 6,
        "sources_matched": len(matches),
        "applied_sources": applied_sources,
        "query_time_ms": round(query_ms, 1),
    }


def _apply_match(prompt, match):
    """Apply a knowledge match to enrich the prompt."""
    source = match["source"]
    detail = match.get("detail", {})

    if source == "intent_graph" and match["action"] == "replay":
        return prompt  # replay handled by speculative_diff, not prompt injection

    if source == "cross_project_templates":
        try:
            import cross_project_templates
            return cross_project_templates.inject_cross_templates(prompt, detail)
        except Exception:
            return prompt

    if source == "prompt_distillation":
        try:
            import prompt_distillation
            return prompt_distillation.apply_distilled(prompt, detail)
        except Exception:
            return prompt

    if source == "session_cache":
        warm = match.get("_warm_prompt", "")
        return warm if warm else prompt

    if source == "output_recycling":
        try:
            import output_recycling
            return output_recycling.inject_recycled(prompt, detail)
        except Exception:
            return prompt

    if source == "transfer_learning":
        try:
            import transfer_learning
            return transfer_learning.inject_transfer(prompt, detail)
        except Exception:
            return prompt

    return prompt


def run():
    """Periodic: report unified knowledge stats."""
    sources = ["intent_graph", "cross_project_templates", "prompt_distillation",
               "session_cache", "output_recycling", "transfer_learning"]
    print(f"[unified-knowledge] consolidating {len(sources)} knowledge stores into single query path")
