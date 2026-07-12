#!/usr/bin/env python3
"""
semantic_dedupe.py — embedding-similarity deduplication for QUEUED tasks.

Near-identical titles/prompts collapse to one QUEUED task. Exact-slug dedupe
(already in queue_groom.py) stays intact; this layer catches paraphrases.

The embedder is INJECTED so unit tests run offline (no network). Production
callers pass a real embedder; tests pass a deterministic fake.
"""
import os, sys
from typing import Callable, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Conservative: only dedup when similarity is very high (near-identical phrasing)
DEFAULT_THRESHOLD = float(os.environ.get("SEMANTIC_DEDUPE_THRESHOLD", "0.92"))


def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _task_text(task: dict) -> str:
    """Combine slug + title + prompt into a single string for embedding."""
    parts = []
    for key in ("slug", "title", "prompt"):
        v = task.get(key)
        if v:
            parts.append(str(v)[:500])  # truncate long prompts
    return " ".join(parts)


def find_duplicates(
    tasks: Sequence[dict],
    embedder: Callable[[List[str]], List[List[float]]],
    threshold: float = DEFAULT_THRESHOLD,
) -> List[Tuple[dict, dict, float]]:
    """Return pairs of tasks whose embeddings exceed *threshold*.

    Each pair is (keeper, duplicate, similarity).  The keeper is the task with
    the earlier created_at (or lower index).  A task only appears as a duplicate
    once (greedy, first-match).
    """
    if len(tasks) < 2:
        return []

    texts = [_task_text(t) for t in tasks]
    embeddings = embedder(texts)

    duplicates: list[tuple[dict, dict, float]] = []
    removed: set[int] = set()

    for i in range(len(tasks)):
        if i in removed:
            continue
        for j in range(i + 1, len(tasks)):
            if j in removed:
                continue
            sim = _cosine(embeddings[i], embeddings[j])
            if sim >= threshold:
                duplicates.append((tasks[i], tasks[j], sim))
                removed.add(j)

    return duplicates


def dedupe_queued(
    tasks: Sequence[dict],
    embedder: Callable[[List[str]], List[List[float]]],
    threshold: float = DEFAULT_THRESHOLD,
    mark_fn: Optional[Callable[[dict, dict, float], None]] = None,
) -> int:
    """Find and mark duplicate QUEUED tasks.

    *mark_fn(keeper, dup, similarity)* is called for each duplicate found.
    If None, duplicates are identified but not acted on (dry-run).
    Returns count of duplicates found.
    """
    dupes = find_duplicates(tasks, embedder, threshold)
    if mark_fn:
        for keeper, dup, sim in dupes:
            mark_fn(keeper, dup, sim)
    return len(dupes)
