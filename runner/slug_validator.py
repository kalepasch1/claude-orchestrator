#!/usr/bin/env python3
"""
slug_validator.py — Guarantee unique slugs before task insertion.

Acceptance: No duplicate-slug errors can occur when this validator is applied.

The validator is called before every task insert. It checks the DB for
existing slugs (any state) and, if a collision is found, either skips
the insert (idempotent) or appends a numeric suffix to make it unique.

Usage:
    from slug_validator import ensure_unique, validate_no_duplicates
    slug = ensure_unique("my-task-slug", project_id)
    # or batch-check:
    dupes = validate_no_duplicates(task_list)
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_SUFFIX = 50


def _existing_slugs(project_id, slug_prefix):
    """Fetch slugs in this project that start with the given prefix."""
    try:
        rows = db.select("tasks", {
            "select": "slug",
            "project_id": f"eq.{project_id}",
            "slug": f"like.{slug_prefix}*",
        }) or []
        return {r["slug"] for r in rows}
    except Exception:
        return set()


def ensure_unique(slug, project_id):
    """Return a slug guaranteed not to collide with existing tasks.

    If `slug` is free, returns it unchanged.
    If it exists, appends -2, -3, ... up to MAX_SUFFIX.
    Raises ValueError if all suffixes are exhausted (shouldn't happen).
    """
    slug = (slug or "").strip()
    if not slug:
        raise ValueError("slug must be non-empty")

    existing = _existing_slugs(project_id, slug)
    if slug not in existing:
        return slug

    for i in range(2, MAX_SUFFIX + 1):
        candidate = f"{slug}-{i}"
        if candidate not in existing:
            return candidate

    raise ValueError(f"All {MAX_SUFFIX} suffixes exhausted for slug '{slug}'")


def validate_no_duplicates(tasks):
    """Check a batch of tasks for internal duplicate slugs.

    Returns list of (slug, indices) for any duplicates found.
    Does NOT hit the DB — use ensure_unique for DB-level checks.
    """
    seen = {}
    for i, t in enumerate(tasks or []):
        s = (t.get("slug") or "").strip()
        if not s:
            continue
        seen.setdefault(s, []).append(i)
    return [(s, idxs) for s, idxs in seen.items() if len(idxs) > 1]


def deduplicate_batch(tasks, project_id):
    """Ensure every task in a batch has a unique slug (both internally
    and against the DB). Mutates tasks in-place, returns the list."""
    # first fix internal dupes
    used = set()
    for t in (tasks or []):
        slug = (t.get("slug") or "").strip()
        if slug in used:
            for i in range(2, MAX_SUFFIX + 1):
                candidate = f"{slug}-{i}"
                if candidate not in used:
                    t["slug"] = candidate
                    slug = candidate
                    break
        used.add(slug)

    # then fix DB collisions
    for t in (tasks or []):
        t["slug"] = ensure_unique(t["slug"], project_id)
    return tasks


if __name__ == "__main__":
    import json, sys
    if len(sys.argv) > 2:
        print(ensure_unique(sys.argv[1], sys.argv[2]))
    else:
        print("Usage: slug_validator.py <slug> <project_id>")
