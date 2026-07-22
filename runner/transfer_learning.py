#!/usr/bin/env python3
from __future__ import annotations
"""
transfer_learning.py — Cross-project transfer learning (100X pattern reuse).

When "add middleware" succeeds in Project A, transfer the pattern to Project B
without re-discovering it. Uses intent_graph + cross_project_templates for the
data, adds a cross-project similarity matcher that adapts paths and conventions.

The key insight: most codebases share structural patterns (add route, add component,
add migration, add test). The code differs but the shape is identical.

Flow:
  1. Normalize task intent (strip project-specific details)
  2. Search ALL projects' intent graphs for matching patterns
  3. Adapt the winning pattern: map paths, conventions, frameworks
  4. Inject as a "transfer template" into the agent prompt

Usage:
    import transfer_learning
    transfer = transfer_learning.find_transfer(task, current_project, all_projects)
    if transfer:
        prompt = transfer_learning.inject_transfer(prompt, transfer)
"""
import os, sys, json, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TRANSFER_MIN_CONFIDENCE = float(os.environ.get("ORCH_TRANSFER_MIN_CONF", "0.6"))

# Project-specific path mappings for adaptation
PROJECT_CONVENTIONS = {
    "tomorrow": {
        "api_prefix": "server/api/",
        "component_prefix": "components/",
        "test_prefix": "server/utils/",
        "migration_prefix": "prisma/migrations/",
        "framework": "nuxt3",
        "lang": "typescript",
    },
    "smarter": {
        "api_prefix": "api/",
        "component_prefix": "src/components/",
        "test_prefix": "tests/",
        "migration_prefix": "migrations/",
        "framework": "next",
        "lang": "typescript",
    },
    "apparently": {
        "api_prefix": "server/",
        "component_prefix": "components/",
        "test_prefix": "tests/",
        "migration_prefix": "prisma/migrations/",
        "framework": "nuxt3",
        "lang": "typescript",
    },
    "beethoven": {
        "api_prefix": "runner/",
        "component_prefix": "web/components/",
        "test_prefix": "runner/",
        "migration_prefix": "supabase/migrations/",
        "framework": "python+nuxt",
        "lang": "python",
    },
}


def _normalize_for_transfer(prompt):
    """Normalize prompt for cross-project matching."""
    text = (prompt or "").lower()
    text = re.sub(r"\s+", " ", text)
    # Remove project-specific names
    for proj in PROJECT_CONVENTIONS:
        text = text.replace(proj, "PROJECT")
    # Remove specific file paths
    text = re.sub(r"[/\\][\w./-]+\.\w+", " FILE ", text)
    # Remove specific identifiers
    text = re.sub(r"[A-Z][a-z]+[A-Z]\w+", "IDENTIFIER", text)  # camelCase
    return text.strip()[:400]


def _adapt_paths(source_project, target_project, files):
    """Adapt file paths from source project conventions to target."""
    source_conv = PROJECT_CONVENTIONS.get(source_project, {})
    target_conv = PROJECT_CONVENTIONS.get(target_project, {})

    if not source_conv or not target_conv:
        return files

    adapted = []
    for f in files:
        adapted_f = f
        for key in ("api_prefix", "component_prefix", "test_prefix", "migration_prefix"):
            src = source_conv.get(key, "")
            tgt = target_conv.get(key, "")
            if src and tgt and src in adapted_f:
                adapted_f = adapted_f.replace(src, tgt)
        adapted.append(adapted_f)
    return adapted


def _keyword_overlap(a, b):
    """Keyword overlap score."""
    words_a = set(a.lower().split()) - {"the", "a", "an", "is", "to", "in", "for", "of"}
    words_b = set(b.lower().split()) - {"the", "a", "an", "is", "to", "in", "for", "of"}
    if not words_a or not words_b:
        return 0
    return len(words_a & words_b) / len(words_a | words_b)


def find_transfer(task, current_project, all_projects=None):
    """Find a transferable pattern from another project.

    Returns: {
        source_project, confidence, original_intent, adapted_files,
        approach, framework_adaptation
    } or None
    """
    if all_projects is None:
        try:
            projs = db.select("projects", {"select": "id,name"}) or []
            all_projects = [p.get("name", "") for p in projs]
        except Exception:
            all_projects = list(PROJECT_CONVENTIONS.keys())

    # Exclude current project
    other_projects = [p for p in all_projects if p != current_project]
    if not other_projects:
        return None

    norm_intent = _normalize_for_transfer(task.get("prompt", ""))
    best_match = None
    best_score = 0

    # Search cross-project templates first (faster)
    try:
        import cross_project_templates
        templates = cross_project_templates.find_templates(task, current_project, max_results=5)
        for t in templates:
            if t.get("source_project") == current_project:
                continue
            score = t.get("relevance", 0)
            if score > best_score:
                best_score = score
                best_match = {
                    "source_project": t["source_project"],
                    "confidence": score,
                    "original_intent": t.get("normalized_intent", ""),
                    "files": t.get("files_changed", []),
                    "approach": t.get("diff_summary", ""),
                    "merge_count": t.get("merge_count", 0),
                }
    except Exception:
        pass

    # Also search intent graph for cross-project matches
    try:
        import intent_graph
        graph = intent_graph._graph()
        for fp, intent in graph.get("intents", {}).items():
            if intent.get("project_id") == current_project:
                continue
            sim = _keyword_overlap(norm_intent, intent.get("normalized", ""))
            if sim > best_score and intent.get("successes", 0) >= 2:
                # Find the best edge for this intent
                edges = [e for e in graph.get("edges", [])
                         if e.get("intent_fp") == fp and e.get("merged")]
                if edges:
                    latest = max(edges, key=lambda e: e.get("timestamp", 0))
                    change = graph.get("changes", {}).get(latest.get("change_key", ""), {})
                    best_score = sim
                    best_match = {
                        "source_project": intent.get("project_id", "unknown"),
                        "confidence": round(sim, 3),
                        "original_intent": intent.get("normalized", ""),
                        "files": change.get("files", []),
                        "approach": "",
                        "merge_count": intent.get("successes", 0),
                    }
    except Exception:
        pass

    if not best_match or best_score < TRANSFER_MIN_CONFIDENCE:
        return None

    # Adapt paths from source → target project
    source = best_match["source_project"]
    adapted_files = _adapt_paths(source, current_project, best_match["files"])
    best_match["adapted_files"] = adapted_files

    # Note framework differences
    source_conv = PROJECT_CONVENTIONS.get(source, {})
    target_conv = PROJECT_CONVENTIONS.get(current_project, {})
    if source_conv.get("framework") != target_conv.get("framework"):
        best_match["framework_adaptation"] = (
            f"Source uses {source_conv.get('framework', '?')}, "
            f"target uses {target_conv.get('framework', '?')} — adapt accordingly"
        )
    else:
        best_match["framework_adaptation"] = "same framework — direct transfer"

    return best_match


def inject_transfer(prompt, transfer):
    """Inject transfer learning context into the agent prompt."""
    if not transfer:
        return prompt

    injection = "\n\n## TRANSFER LEARNING (proven pattern from another project)\n"
    injection += f"Source: {transfer['source_project']} ({transfer['merge_count']} successful merges)\n"
    injection += f"Confidence: {transfer['confidence']:.0%}\n"

    adapted = transfer.get("adapted_files", [])
    if adapted:
        injection += f"Adapted target files: {', '.join(adapted[:8])}\n"

    approach = transfer.get("approach", "")
    if approach:
        injection += f"Prior approach: {approach[:300]}\n"

    fw = transfer.get("framework_adaptation", "")
    if fw:
        injection += f"Note: {fw}\n"

    injection += "\nAdapt this proven pattern to the current project's conventions.\n"

    return injection + "\n" + prompt
