#!/usr/bin/env python3
"""
cross_project_templates.py — Cross-project template transfer (100X-1000X).

diff_compiler currently searches within one project. This module maintains a shared
merged_diff_library across ALL projects (tomorrow/smarter/apparently/beethoven) so a
pattern proven in one repo instantly applies to all three.

Knowledge flywheel: every merge anywhere teaches every project.

Mechanics:
  1. After each successful merge, index the diff template with normalized intent
  2. On new task, search ALL projects' templates (not just current)
  3. Rank by: domain similarity × merge rate × recency
  4. Return adapted template with source attribution

Storage: controls.cross_project_templates (JSON, pruned to top N)

Usage:
    import cross_project_templates
    matches = cross_project_templates.find_templates(task, current_project)
    # Returns templates from ANY project, ranked by relevance
"""
import os, sys, json, hashlib, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_TEMPLATES = int(os.environ.get("ORCH_CROSS_TEMPLATES_MAX", "500"))
MIN_SIMILARITY = float(os.environ.get("ORCH_CROSS_TEMPLATE_MIN_SIM", "0.3"))


def _normalize_intent(prompt):
    """Normalize prompt to structural intent — strip project-specific paths/names."""
    text = (prompt or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[0-9a-f]{8,}", "HASH", text)
    text = re.sub(r"\d{4,}", "NUM", text)
    text = re.sub(r"['\"].*?['\"]", "STR", text)
    # Strip project-specific paths
    text = re.sub(r"(tomorrow|smarter|apparently|beethoven)[/\\]", "PROJECT/", text)
    return text[:400]


def _intent_hash(prompt, kind=""):
    """Hash the normalized intent for dedup/lookup."""
    norm = _normalize_intent(prompt)
    raw = f"{kind}|{norm}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _library():
    """Load the cross-project template library."""
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.cross_project_templates"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_library(lib):
    """Save library, pruning to MAX_TEMPLATES."""
    if len(lib) > MAX_TEMPLATES:
        by_score = sorted(lib.items(), key=lambda x: x[1].get("score", 0))
        lib = dict(by_score[-MAX_TEMPLATES:])
    try:
        db.upsert("controls", {"key": "cross_project_templates",
                                "value": json.dumps(lib, default=str)})
    except Exception:
        pass


def index_merge(task, project_name, files_changed, diff_summary="", merge_rate=1.0):
    """Index a successful merge into the cross-project library.

    Called after every successful integration — this is how the flywheel turns.
    """
    prompt = task.get("prompt", "")
    kind = task.get("kind", "")
    intent = _intent_hash(prompt, kind)

    lib = _library()

    # Classify the structural pattern (strip project-specific details)
    pattern = {
        "intent_hash": intent,
        "normalized_intent": _normalize_intent(prompt)[:200],
        "kind": kind,
        "source_project": project_name,
        "files_changed": [_generalize_path(f) for f in (files_changed or [])[:20]],
        "diff_summary": (diff_summary or "")[:500],
        "merge_count": 0,
        "projects_proven": [],
        "last_used": time.time(),
        "first_seen": time.time(),
        "score": 0,
    }

    existing = lib.get(intent, pattern)
    existing["merge_count"] = existing.get("merge_count", 0) + 1
    existing["last_used"] = time.time()

    # Track which projects this pattern has been proven in
    proven = set(existing.get("projects_proven", []))
    proven.add(project_name)
    existing["projects_proven"] = list(proven)

    # Score: merge_count × project_diversity × recency
    age_days = max(1, (time.time() - existing.get("first_seen", time.time())) / 86400)
    existing["score"] = (
        existing["merge_count"] * len(proven) * (1.0 / (1.0 + age_days / 30))
    )

    lib[intent] = existing
    _save_library(lib)
    return intent


def _generalize_path(filepath):
    """Generalize a file path to be project-agnostic.

    server/api/otc/foo.ts → server/api/*/foo.ts
    components/app/Bar.vue → components/app/*.vue
    """
    parts = filepath.replace("\\", "/").split("/")
    # Keep structure but generalize the deepest specific directory
    if len(parts) > 2:
        # Keep first 2 and last part, wildcard the middle
        ext = os.path.splitext(parts[-1])[1]
        return "/".join(parts[:2]) + "/*" + ext
    return filepath


def _keyword_similarity(a, b):
    """Simple keyword overlap similarity between two normalized intents."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def find_templates(task, current_project="", max_results=5):
    """Find cross-project templates matching a task intent.

    Returns templates from ANY project, ranked by relevance.
    Boosts templates proven across multiple projects.
    """
    lib = _library()
    if not lib:
        return []

    prompt = task.get("prompt", "")
    kind = task.get("kind", "")
    norm_intent = _normalize_intent(prompt)
    intent_hash = _intent_hash(prompt, kind)

    # Exact hash match
    if intent_hash in lib:
        exact = lib[intent_hash]
        exact["match_type"] = "exact"
        exact["relevance"] = 1.0
        return [exact]

    # Fuzzy match by keyword similarity
    candidates = []
    for key, template in lib.items():
        sim = _keyword_similarity(norm_intent, template.get("normalized_intent", ""))
        if sim < MIN_SIMILARITY:
            continue

        # Boost if proven across multiple projects
        cross_project_boost = len(template.get("projects_proven", [])) * 0.1

        # Boost if kind matches
        kind_boost = 0.15 if template.get("kind") == kind else 0

        # Boost if NOT from current project (cross-pollination is the point)
        cross_boost = 0.1 if template.get("source_project") != current_project else 0

        relevance = min(sim + cross_project_boost + kind_boost + cross_boost, 1.0)

        candidates.append({
            **template,
            "match_type": "fuzzy",
            "relevance": round(relevance, 3),
            "similarity": round(sim, 3),
        })

    candidates.sort(key=lambda c: -c["relevance"])
    return candidates[:max_results]


def inject_cross_templates(prompt, templates):
    """Inject cross-project template hints into the agent prompt."""
    if not templates:
        return prompt

    injection = "\n\n## CROSS-PROJECT TEMPLATES (proven patterns from other repos)\n"
    for i, t in enumerate(templates[:3]):
        source = t.get("source_project", "unknown")
        merges = t.get("merge_count", 0)
        projects = ", ".join(t.get("projects_proven", []))
        injection += f"\n### Template {i+1} (from {source}, {merges} merges, proven in: {projects})\n"
        injection += f"Intent: {t.get('normalized_intent', '')[:150]}\n"
        files = t.get("files_changed", [])
        if files:
            injection += f"Files pattern: {', '.join(files[:5])}\n"
        summary = t.get("diff_summary", "")
        if summary:
            injection += f"Approach: {summary[:200]}\n"

    return injection + "\n" + prompt


def stats():
    """Library statistics."""
    lib = _library()
    total = len(lib)
    multi_project = sum(1 for t in lib.values() if len(t.get("projects_proven", [])) > 1)
    avg_merges = sum(t.get("merge_count", 0) for t in lib.values()) / max(total, 1)
    return {
        "total_templates": total,
        "multi_project_templates": multi_project,
        "avg_merge_count": round(avg_merges, 1),
    }


def run():
    """Periodic: log stats."""
    s = stats()
    print(f"[cross-templates] {s['total_templates']} templates, "
          f"{s['multi_project_templates']} cross-project, "
          f"avg {s['avg_merge_count']} merges each")
