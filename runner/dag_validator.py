#!/usr/bin/env python3
"""
dag_validator.py - async DAG validation before queue admission.

Checks: cycles, missing deps, depth limit, duplicate slugs, size limit.

Env vars:
    ORCH_DAG_VALIDATOR           "true" (default) to enable
    ORCH_DAG_MAX_DEPTH           max dependency chain depth (default: 5)
    ORCH_DAG_MAX_TASKS           max tasks in a single DAG (default: 50)
"""
import os, sys
from collections import defaultdict, deque
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("dag_validator")

ENABLED = os.environ.get("ORCH_DAG_VALIDATOR", "true").lower() in ("1", "true", "yes", "on")
MAX_DEPTH = int(os.environ.get("ORCH_DAG_MAX_DEPTH", "5"))
MAX_TASKS = int(os.environ.get("ORCH_DAG_MAX_TASKS", "50"))

class DAGValidationError:
    def __init__(self, kind, message, slugs=None):
        self.kind = kind
        self.message = message
        self.slugs = slugs or []
    def to_dict(self):
        return {"kind": self.kind, "message": self.message, "slugs": self.slugs}

def _detect_cycles(tasks_by_slug):
    in_degree = defaultdict(int)
    graph = defaultdict(list)
    all_slugs = set(tasks_by_slug.keys())
    for slug, task in tasks_by_slug.items():
        for dep in (task.get("deps") or []):
            if dep in all_slugs:
                graph[dep].append(slug)
                in_degree[slug] += 1
        if slug not in in_degree:
            in_degree[slug] = 0
    queue = deque(s for s, d in in_degree.items() if d == 0)
    visited = set()
    while queue:
        node = queue.popleft()
        visited.add(node)
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    return [s for s in all_slugs if s not in visited]

def _compute_depth(tasks_by_slug):
    cache = {}
    def depth(slug):
        if slug in cache:
            return cache[slug]
        task = tasks_by_slug.get(slug)
        if not task or not task.get("deps"):
            cache[slug] = 0
            return 0
        d = 1 + max((depth(dep) for dep in task["deps"] if dep in tasks_by_slug), default=0)
        cache[slug] = d
        return d
    max_d, deepest = 0, ""
    for slug in tasks_by_slug:
        d = depth(slug)
        if d > max_d:
            max_d, deepest = d, slug
    return max_d, deepest

def validate(tasks, existing_slugs=None):
    if not ENABLED:
        return {"valid": True, "errors": []}
    errors = []
    existing_slugs = existing_slugs or set()
    batch_slugs = set()
    if len(tasks) > MAX_TASKS:
        errors.append(DAGValidationError("size", f"DAG has {len(tasks)} tasks, max {MAX_TASKS}"))
    for t in tasks:
        slug = t.get("slug", "")
        if slug in batch_slugs:
            errors.append(DAGValidationError("duplicate", f"duplicate slug: {slug}", [slug]))
        batch_slugs.add(slug)
    tasks_by_slug = {t["slug"]: t for t in tasks if t.get("slug")}
    for t in tasks:
        for dep in (t.get("deps") or []):
            if dep not in batch_slugs and dep not in existing_slugs:
                errors.append(DAGValidationError("missing_dep",
                    f"'{t.get('slug','')}' depends on unknown '{dep}'", [t.get("slug",""), dep]))
    cycle_slugs = _detect_cycles(tasks_by_slug)
    if cycle_slugs:
        errors.append(DAGValidationError("cycle",
            f"circular dependency: {', '.join(sorted(cycle_slugs))}", sorted(cycle_slugs)))
    if not cycle_slugs:
        max_depth, deepest = _compute_depth(tasks_by_slug)
        if max_depth > MAX_DEPTH:
            errors.append(DAGValidationError("depth",
                f"DAG depth {max_depth} exceeds max {MAX_DEPTH}", [deepest]))
    return {"valid": len(errors) == 0, "errors": errors}

def validate_before_admission(tasks, project_id=None):
    if not ENABLED:
        return {"valid": True, "errors": [], "admitted": len(tasks)}
    existing_slugs = set()
    if project_id:
        try:
            import db
            rows = db.select("tasks", {"select": "slug", "project_id": f"eq.{project_id}", "limit": "5000"}) or []
            existing_slugs = {r["slug"] for r in rows}
        except Exception as e:
            _log.warning("slug fetch failed: %s", e)
    result = validate(tasks, existing_slugs)
    result["admitted"] = len(tasks) if result["valid"] else 0
    if not result["valid"]:
        _log.warning("DAG rejected: %s", "; ".join(e.message for e in result["errors"]))
    return result
