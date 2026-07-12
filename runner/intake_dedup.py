#!/usr/bin/env python3
"""
intake_dedup.py - Semantic deduplication for intake tasks.

PURE function candidate_matches(prompt, existing) -> list of (ref, score) that ranks
a new task prompt against existing capabilities and in-flight/queued task slugs+prompts.
Uses capability.py's embedding dedup path when EMBED_PROVIDER is set, else a cheap
token-overlap (Jaccard) fallback (no network in the fallback path).
"""
import os, sys, re, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEDUP_THRESHOLD = float(os.environ.get("INTAKE_DEDUP_THRESHOLD", "0.70"))

try:
    import knowledge_embed as _ke
    _EMBED_OK = bool(os.environ.get("EMBED_PROVIDER"))
except ImportError:
    _ke = None
    _EMBED_OK = False


def _tokenize(text):
    """Extract lowercase alpha tokens (len >= 3) for Jaccard similarity."""
    return set(re.findall(r"[a-z]{3,}", (text or "").lower()))


def _jaccard(a_tokens, b_tokens):
    """Jaccard similarity between two token sets."""
    if not a_tokens or not b_tokens:
        return 0.0
    inter = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return inter / union if union else 0.0


def _cosine(a, b):
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


def candidate_matches(prompt, existing_prompts=None):
    """Score a new task prompt against existing items.

    Args:
        prompt: the new task's prompt text
        existing_prompts: list of dicts with keys 'ref' (slug/id) and 'text' (prompt/summary).
                          If None, fetches from DB (capabilities + in-flight tasks).

    Returns:
        list of (ref, score) sorted by score descending.
    """
    if not prompt:
        return []

    if existing_prompts is None:
        existing_prompts = _fetch_existing()

    if not existing_prompts:
        return []

    if _EMBED_OK and _ke:
        try:
            return _embed_matches(prompt, existing_prompts)
        except Exception:
            pass

    return _jaccard_matches(prompt, existing_prompts)


def _embed_matches(prompt, existing):
    """Score using embedding cosine similarity."""
    vec = _ke.embed(prompt)
    if not vec:
        return _jaccard_matches(prompt, existing)
    results = []
    for item in existing:
        ev = _ke.embed(item.get("text") or "")
        if ev:
            score = _cosine(vec, ev)
            results.append((item["ref"], round(score, 4)))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def _jaccard_matches(prompt, existing):
    """Score using token-overlap Jaccard similarity."""
    prompt_tokens = _tokenize(prompt)
    if not prompt_tokens:
        return []
    results = []
    for item in existing:
        other_tokens = _tokenize(item.get("text") or "")
        score = _jaccard(prompt_tokens, other_tokens)
        if score > 0:
            results.append((item["ref"], round(score, 4)))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def _fetch_existing():
    """Fetch capabilities + in-flight tasks from DB. Fail-open on any error."""
    try:
        import db as _db
    except Exception:
        return []
    items = []
    try:
        caps = _db.select("capabilities", {"select": "slug,summary"}) or []
        for c in caps:
            items.append({"ref": f"cap:{c.get('slug', '')}", "text": c.get("summary") or ""})
    except Exception:
        pass
    try:
        tasks = _db.select("tasks", {
            "select": "slug,prompt",
            "state": "in.(QUEUED,RUNNING)",
        }) or []
        for t in tasks:
            items.append({"ref": f"task:{t.get('slug', '')}", "text": t.get("prompt") or ""})
    except Exception:
        pass
    return items
