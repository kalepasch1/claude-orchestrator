#!/usr/bin/env python3
"""
memory_retrieval.py - keyword retrieval over merged-diff memory exemplars.

Consolidates the dropbox-prompt-merged-diff-memory-system group-11 spec:
retrieve_exemplars(keyword, limit) filters exemplars case-insensitively
(over 'keywords', 'title' and 'content'), orders alphabetically by title,
applies the limit (<= 0 returns []), and loads from the real merged-diff
memory backend fail-soft (backend errors -> [] with a warning, never raise).

An in-memory store (add_exemplar/get_all_exemplars) is provided for tests
and for callers that stage exemplars before the backend has any.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)

# ── In-memory exemplar store (module-level, spec group-11 bullet 18) ─────────
_STORE: list = []


def add_exemplar(item):
    """Store one exemplar dict (expects at least id/content/keywords)."""
    if isinstance(item, dict):
        _STORE.append(item)


def get_all_exemplars():
    """All exemplars staged in the in-memory store, in insertion order."""
    return list(_STORE)


def clear_exemplars():
    """Test hook: empty the in-memory store."""
    _STORE.clear()


def load_exemplars_from_store():
    """Load exemplars from the merged-diff memory backend, fail-soft.

    Backend rows (merged_diff_memory.get_recent_merges) are mapped onto the
    exemplar shape: title <- branch/name, content <- summary, keywords <-
    files_changed basenames. ImportError or backend errors -> [] + warning.
    """
    try:
        import merged_diff_memory
    except ImportError:
        log.warning("merged_diff_memory backend unavailable; no stored exemplars")
        return []
    try:
        rows = merged_diff_memory.get_recent_merges(limit=100) or []
    except Exception as e:
        log.warning("merged-diff memory read failed (%s); returning no exemplars", e)
        return []
    exemplars = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        exemplars.append({
            "id": row.get("commit") or row.get("hash") or row.get("branch") or "",
            "title": row.get("branch") or row.get("name") or "",
            "content": row.get("summary") or "",
            "keywords": [os.path.basename(f) for f in (row.get("files_changed") or []) if f],
        })
    return exemplars


def _matches(exemplar, needle):
    """Case-insensitive match over keywords, title and content."""
    if needle in (exemplar.get("title") or "").lower():
        return True
    if needle in (exemplar.get("content") or "").lower():
        return True
    return any(needle in str(kw).lower() for kw in (exemplar.get("keywords") or []))


def retrieve_exemplars(keyword=None, limit=5):
    """Retrieve exemplars filtered by keyword, ordered by title, capped at limit.

    - keyword None/empty (or non-str) -> all exemplars (up to limit)
    - matching is case-insensitive over keywords, title and content
    - ordering: alphabetical by title, case-insensitive (deterministic)
    - limit <= 0 -> []; limit beyond matches -> all matches
    - fail-soft everywhere: bad store data or backend errors never raise
    """
    log.info("Retrieving exemplars... keyword=%r limit=%r", keyword, limit)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    if limit <= 0:
        log.debug("retrieve_exemplars: limit<=0, returning []")
        return []

    exemplars = get_all_exemplars() or load_exemplars_from_store()
    if not isinstance(keyword, str) or not keyword.strip():
        matches = list(exemplars)
    else:
        needle = keyword.strip().lower()
        matches = [e for e in exemplars if isinstance(e, dict) and _matches(e, needle)]

    matches.sort(key=lambda e: str(e.get("title") or "").lower())
    result = matches[:limit]
    log.debug("retrieve_exemplars: %d result(s)", len(result))
    return result
