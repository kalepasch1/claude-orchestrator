"""Auto-queue missing branches with deduplication.

Discovers branches not yet in the task queue, validates against existing
slugs to prevent duplicates, and queues valid ones.
"""

import re
import logging
from typing import Dict, List, Any, Optional, Set

log = logging.getLogger(__name__)


def normalize_slug(slug: str) -> str:
    s = slug.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _token_similarity(a: str, b: str) -> float:
    tokens_a = set(a.split("-"))
    tokens_b = set(b.split("-"))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def is_duplicate(candidate: str, existing_slugs: Set[str],
                 similarity_threshold: float = 0.85) -> bool:
    norm_candidate = normalize_slug(candidate)
    for existing in existing_slugs:
        norm_existing = normalize_slug(existing)
        if norm_candidate == norm_existing:
            return True
        if _token_similarity(norm_candidate, norm_existing) >= similarity_threshold:
            return True
    return False


def discover_missing_branches(all_branches: List[str],
                              queued_slugs: Set[str],
                              prefix: str = "agent/") -> List[str]:
    missing = []
    for branch in all_branches:
        if not branch.startswith(prefix):
            continue
        slug = branch[len(prefix):]
        if slug and slug not in queued_slugs:
            missing.append(slug)
    return missing


class AutoQueueResult:
    def __init__(self):
        self.queued: List[str] = []
        self.skipped_duplicate: List[str] = []
        self.skipped_error: List[Dict[str, str]] = []

    @property
    def total_processed(self) -> int:
        return len(self.queued) + len(self.skipped_duplicate) + len(self.skipped_error)


def auto_queue_missing_branches(
    project_configs: Dict[str, Dict[str, Any]],
    get_branches_fn=None, get_queued_slugs_fn=None, enqueue_fn=None,
) -> AutoQueueResult:
    result = AutoQueueResult()
    for project_id, config in project_configs.items():
        project_name = config.get("name", project_id)
        prefix = config.get("prefix", "agent/")
        try:
            if get_branches_fn is None:
                continue
            branches = get_branches_fn(project_id)
        except Exception as e:
            result.skipped_error.append({"project": project_name, "error": f"branch discovery failed: {e}"})
            continue
        try:
            if get_queued_slugs_fn is None:
                continue
            existing_slugs = get_queued_slugs_fn(project_id)
        except Exception as e:
            result.skipped_error.append({"project": project_name, "error": f"slug fetch failed: {e}"})
            continue
        missing = discover_missing_branches(branches, existing_slugs, prefix)
        for slug in missing:
            if is_duplicate(slug, existing_slugs):
                result.skipped_duplicate.append(slug)
                continue
            try:
                if enqueue_fn is None:
                    result.skipped_error.append({"project": project_name, "slug": slug, "error": "no enqueue function"})
                    continue
                success = enqueue_fn(project_id, slug)
                if success:
                    result.queued.append(slug)
                    existing_slugs.add(slug)
                else:
                    result.skipped_error.append({"project": project_name, "slug": slug, "error": "enqueue returned False"})
            except Exception as e:
                result.skipped_error.append({"project": project_name, "slug": slug, "error": str(e)})
    return result
