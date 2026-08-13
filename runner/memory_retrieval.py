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
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)

# ── In-memory exemplar store (module-level, spec group-11 bullet 18) ─────────
_STORE: list = []

# ── Backend-load cache ──────────────────────────────────────────────────────
# retrieve_exemplars() used to call load_exemplars_from_store() on EVERY call,
# re-reading up to 100 rows out of the merged-diff backend per retrieval. Hot
# callers (the planner ranks candidates in a loop) paid that read N times for
# an identical answer. Cache the mapped exemplars behind a short TTL.
#
# ORCH_-prefixed so it is fleet-pushable via fleet_control.py; 0 disables the
# cache entirely (restores the previous read-every-call behaviour).
_CACHE_TTL_DEFAULT = 60.0
_cache_lock = threading.Lock()
_cache_value: list = []
_cache_at: float = 0.0
_cache_hits = 0
_cache_misses = 0


def _cache_ttl():
    """TTL in seconds for the backend exemplar cache; fail-soft to default."""
    try:
        return max(0.0, float(os.environ.get("ORCH_MEMORY_EXEMPLAR_CACHE_TTL",
                                             _CACHE_TTL_DEFAULT)))
    except (TypeError, ValueError):
        return _CACHE_TTL_DEFAULT


def invalidate_cache():
    """Drop the cached backend exemplars (next read re-loads)."""
    global _cache_value, _cache_at
    with _cache_lock:
        _cache_value = []
        _cache_at = 0.0


def cache_stats():
    """Observability hook: {hits, misses, size, age_s, ttl_s}."""
    with _cache_lock:
        age = (time.monotonic() - _cache_at) if _cache_at else None
        return {
            "hits": _cache_hits,
            "misses": _cache_misses,
            "size": len(_cache_value),
            "age_s": age,
            "ttl_s": _cache_ttl(),
        }


def add_exemplar(item):
    """Store one exemplar dict (expects at least id/content/keywords)."""
    if isinstance(item, dict):
        _STORE.append(item)


def get_all_exemplars():
    """All exemplars staged in the in-memory store, in insertion order."""
    return list(_STORE)


def clear_exemplars():
    """Test hook: empty the in-memory store (and the backend cache with it)."""
    _STORE.clear()
    invalidate_cache()


def _cached_load_exemplars():
    """load_exemplars_from_store() behind the TTL cache.

    Cache misses do the (slow) backend read OUTSIDE the lock so a slow or hung
    backend never serialises every other caller behind it; the lock only
    guards the tiny publish step. TTL 0 bypasses the cache entirely.
    """
    global _cache_value, _cache_at, _cache_hits, _cache_misses
    ttl = _cache_ttl()
    if ttl <= 0:
        return load_exemplars_from_store()

    now = time.monotonic()
    with _cache_lock:
        if _cache_at and (now - _cache_at) < ttl:
            _cache_hits += 1
            return list(_cache_value)
        _cache_misses += 1

    loaded = load_exemplars_from_store()
    with _cache_lock:
        _cache_value = list(loaded)
        _cache_at = time.monotonic()
    return loaded


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

    exemplars = _STORE or _cached_load_exemplars()
    if not isinstance(keyword, str) or not keyword.strip():
        matches = list(exemplars)
    else:
        needle = keyword.strip().lower()
        matches = [e for e in exemplars if isinstance(e, dict) and _matches(e, needle)]

    matches.sort(key=lambda e: str(e.get("title") or "").lower())
    result = matches[:limit]
    log.debug("retrieve_exemplars: %d result(s)", len(result))
    return result
