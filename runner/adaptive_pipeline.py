#!/usr/bin/env python3
"""
adaptive_pipeline.py — Adaptive pipeline collapse (100X on mature repos).

Multi-agent pipeline currently runs fixed 2-4 stages. This module dynamically
collapses stages when earlier stages find cached/proven results:

  Scout finds intent match → skip planner + implementer (use cached diff)
  Scout finds transfer → skip planner (use transferred plan)
  Planner finds distilled prompt → skip implementer (use distilled)
  Full pipeline only when no shortcuts found

Each skipped stage saves a full model call (typically 2K-8K tokens).

Usage:
    import adaptive_pipeline
    result = adaptive_pipeline.plan(task, project, repo)
    # result.collapsed_stages tells you what was skipped
    # result.enriched_prompt is ready for the remaining stages
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def plan(task, project_name, repo=""):
    """Plan the adaptive pipeline — determine which stages can be collapsed.

    Returns: {
        stages: list of stage names to actually run,
        collapsed: list of stage names skipped,
        enriched_prompt: str (prompt with all cached context injected),
        shortcut: str describing what shortcut was found,
        estimated_savings_tokens: int,
    }
    """
    prompt = task.get("prompt", "")
    all_stages = ["scout", "planner", "implementer", "verifier"]
    collapsed = []
    shortcut = "none"
    enriched = prompt
    savings = 0

    # 1. Check if intent graph has a direct replay (skip scout + planner + implementer)
    try:
        import intent_graph
        replay = intent_graph.find_replay(task, repo)
        if replay and replay.get("confidence", 0) >= 0.9:
            collapsed = ["scout", "planner", "implementer"]
            shortcut = f"intent_replay (conf={replay['confidence']:.0%})"
            savings = 12000  # ~3 model calls saved
            enriched = f"## PROVEN PATTERN — apply directly\n{replay.get('approach', '')}\n\n{prompt}"
            return _result(all_stages, collapsed, enriched, shortcut, savings)
    except Exception:
        pass

    # 2. Check transfer learning (skip scout, maybe planner)
    try:
        import transfer_learning
        transfer = transfer_learning.find_transfer(task, current_project=project_name)
        if transfer and transfer.get("confidence", 0) >= 0.7:
            collapsed.append("scout")
            savings += 4000
            enriched = transfer_learning.inject_transfer(enriched, transfer)
            shortcut = f"transfer_from_{transfer['source_project']}"

            # If transfer has adapted files, skip planner too
            if transfer.get("adapted_files") and len(transfer["adapted_files"]) >= 2:
                collapsed.append("planner")
                savings += 4000
                shortcut += "+plan"
    except Exception:
        pass

    # 3. Check prompt distillation (skip implementer overhead)
    if "implementer" not in collapsed:
        try:
            import prompt_distillation
            distilled = prompt_distillation.find_distilled(task, current_project=project_name)
            if distilled and distilled.get("merge_count", 0) >= 3:
                enriched = prompt_distillation.apply_distilled(enriched, distilled)
                # Don't skip implementer (still need to write code) but savings come
                # from much shorter prompt
                savings += int(distilled.get("original_length", 0) - distilled.get("distilled_length", 0))
                if not shortcut or shortcut == "none":
                    shortcut = f"distilled ({distilled['merge_count']} merges)"
        except Exception:
            pass

    # 4. Check cross-project templates (enrich, may skip scout)
    if "scout" not in collapsed:
        try:
            import cross_project_templates
            templates = cross_project_templates.find_templates(task, current_project=project_name, max_results=3)
            if templates and templates[0].get("relevance", 0) >= 0.5:
                collapsed.append("scout") if "scout" not in collapsed else None
                savings += 4000
                enriched = cross_project_templates.inject_cross_templates(enriched, templates)
                if not shortcut or shortcut == "none":
                    shortcut = f"cross_template ({len(templates)} matches)"
        except Exception:
            pass

    return _result(all_stages, collapsed, enriched, shortcut, savings)


def _result(all_stages, collapsed, enriched, shortcut, savings):
    remaining = [s for s in all_stages if s not in collapsed]
    return {
        "stages": remaining,
        "collapsed": collapsed,
        "enriched_prompt": enriched,
        "shortcut": shortcut,
        "estimated_savings_tokens": savings,
        "stage_count": len(remaining),
    }


def should_use_pipeline(task, project_name, repo=""):
    """Quick check: is it worth running the adaptive pipeline at all?

    For very simple tasks or tasks with zero cached knowledge, skip the
    pipeline entirely (direct agent call is faster).
    """
    prompt_len = len(task.get("prompt", ""))
    kind = task.get("kind", "")

    # Very short prompts → direct call
    if prompt_len < 200 and kind in ("mechanical", "config"):
        return False

    # Check if we have ANY cached knowledge
    try:
        import intent_graph
        replay = intent_graph.find_replay(task, repo)
        if replay:
            return True
    except Exception:
        pass

    try:
        import prompt_distillation
        distilled = prompt_distillation.find_distilled(task)
        if distilled:
            return True
    except Exception:
        pass

    # Default: use pipeline for complex tasks
    return prompt_len > 1000 or kind in ("feature", "refactor", "security")


def run():
    """Periodic: report pipeline collapse stats."""
    print("[adaptive-pipeline] module loaded — collapses run inline per-task")
