#!/usr/bin/env python3
"""
dependency_aware_release.py — When apps share a capability, sequence releases
so a breaking change never ships to a dependent before its update does.

Problem: App A provides capability C. App B consumes C. If A ships a breaking
change to C before B's update is ready, B breaks in production.

Solution: Build a release dependency graph from the capability registry.
When releasing, topologically sort: providers ship first, then consumers.
If a consumer's update isn't ready, hold the provider's release too.

Integrates with release_train.py's batch promotion flow.
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("ORCH_DEP_AWARE_RELEASE", "true").lower() in ("1", "true", "yes")


def _get_capability_graph(project_id=None):
    """Build a provider->consumer dependency graph from capabilities table.

    Returns {capability_slug: {"providers": [project_ids], "consumers": [project_ids]}}
    """
    try:
        caps = db.select("capabilities", {
            "select": "slug,source_project,consumers",
        }) or []
    except Exception:
        return {}

    graph = {}
    for cap in caps:
        slug = cap.get("slug", "")
        provider = cap.get("source_project", "")
        consumers = cap.get("consumers") or []
        if isinstance(consumers, str):
            try:
                consumers = json.loads(consumers)
            except Exception:
                consumers = []
        graph[slug] = {"providers": [provider] if provider else [],
                       "consumers": consumers}
    return graph


def build_release_order(project_ids, cap_graph=None):
    """Topologically sort projects so providers release before consumers.

    Returns {"order": [project_ids in safe release order], "blocked": {pid: reason}}
    """
    if not ENABLED:
        return {"order": list(project_ids), "blocked": {}}

    if cap_graph is None:
        cap_graph = _get_capability_graph()

    # Build adjacency: project A -> B means "A must release before B"
    must_precede = {}  # {project: set of projects that must come after}
    for slug, info in cap_graph.items():
        for provider in info["providers"]:
            if provider not in project_ids:
                continue
            for consumer in info["consumers"]:
                if consumer not in project_ids:
                    continue
                if provider != consumer:
                    must_precede.setdefault(provider, set()).add(consumer)

    # Topological sort (Kahn's algorithm)
    in_degree = {pid: 0 for pid in project_ids}
    for src, dsts in must_precede.items():
        for dst in dsts:
            if dst in in_degree:
                in_degree[dst] = in_degree.get(dst, 0) + 1

    queue = [pid for pid in project_ids if in_degree.get(pid, 0) == 0]
    order = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for dst in must_precede.get(node, set()):
            if dst in in_degree:
                in_degree[dst] -= 1
                if in_degree[dst] == 0:
                    queue.append(dst)

    # Detect cycles (blocked releases)
    blocked = {}
    for pid in project_ids:
        if pid not in order:
            blocked[pid] = "circular dependency detected"

    return {"order": order, "blocked": blocked}


def check_release_safety(project_id, pending_tasks=None):
    """Check if it's safe to release a project given its capability dependencies.

    Returns {"safe": bool, "reason": str, "blocking_projects": list}
    """
    if not ENABLED:
        return {"safe": True, "reason": "dependency-aware release disabled", "blocking_projects": []}

    cap_graph = _get_capability_graph()

    # Find capabilities this project provides
    provided_caps = []
    for slug, info in cap_graph.items():
        if project_id in info["providers"]:
            provided_caps.append(slug)

    if not provided_caps:
        return {"safe": True, "reason": "project provides no shared capabilities",
                "blocking_projects": []}

    # Check if consumers have pending updates
    blocking = []
    for cap_slug in provided_caps:
        info = cap_graph.get(cap_slug, {})
        for consumer_pid in info.get("consumers", []):
            if consumer_pid == project_id:
                continue
            # Check if consumer has QUEUED/RUNNING tasks (meaning it's updating)
            try:
                rows = db.select("tasks", {
                    "select": "id,slug,state",
                    "project_id": f"eq.{consumer_pid}",
                    "state": "in.(QUEUED,RUNNING)",
                    "limit": "5",
                }) or []
                if rows:
                    blocking.append(consumer_pid)
            except Exception:
                pass  # fail-soft: don't block on query failure

    if blocking:
        return {"safe": False,
                "reason": f"consumers {blocking} still updating shared capabilities",
                "blocking_projects": blocking}

    return {"safe": True, "reason": "all consumers up to date", "blocking_projects": []}


def sequence_batch(task_slugs, project_id):
    """Given a batch of tasks ready to release, return them in dependency-safe order.

    Tasks that modify shared capabilities go first; tasks that consume them go after.
    """
    if not ENABLED or not task_slugs:
        return list(task_slugs)

    # Fetch task details
    tasks = []
    for slug in task_slugs:
        try:
            rows = db.select("tasks", {
                "select": "slug,prompt,kind,deps",
                "slug": f"eq.{slug}",
                "project_id": f"eq.{project_id}",
                "limit": "1",
            }) or []
            if rows:
                tasks.append(rows[0])
        except Exception:
            tasks.append({"slug": slug})

    # Simple heuristic: tasks with deps go after their dependencies
    dep_map = {}
    for t in tasks:
        for dep in (t.get("deps") or []):
            if dep in task_slugs:
                dep_map.setdefault(t["slug"], set()).add(dep)

    # Topological sort
    ordered = []
    remaining = set(task_slugs)
    while remaining:
        # Find tasks with no unresolved deps
        ready = [s for s in remaining if not (dep_map.get(s, set()) - set(ordered))]
        if not ready:
            ordered.extend(sorted(remaining))  # cycle: just append rest
            break
        ordered.extend(sorted(ready))
        remaining -= set(ready)

    return ordered
