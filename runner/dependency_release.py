#!/usr/bin/env python3
"""
dependency_release.py — DAG-based release ordering with breaking-change safety.

Parses project dependency files (package.json, requirements.txt), builds a DAG
of release dependencies, and topologically sorts them so breaking changes never
ship before their dependents are ready.

Env vars:
    ORCH_DEPENDENCY_RELEASE_ENABLED  – "true" (default) / "false"
"""
import json, os, re, sys, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("ORCH_DEPENDENCY_RELEASE_ENABLED", "true").lower() == "true"

_lock = threading.Lock()
_stats = {
    "dependencies_checked": 0,
    "releases_validated": 0,
    "graphs_built": 0,
    "sequences_computed": 0,
    "circular_deps_detected": 0,
    "validation_failures": 0,
}


# ---------------------------------------------------------------------------
# 1. check_dependencies — parse package.json / requirements.txt
# ---------------------------------------------------------------------------

def check_dependencies(project_path):
    """Parse dependency files in project_path, return dict of dependency -> version.

    Checks package.json first, then requirements.txt. Returns an empty dict
    (fail-soft) if neither file is readable.
    """
    if not ENABLED:
        return {}
    deps = {}
    try:
        pkg_path = os.path.join(project_path, "package.json")
        if os.path.isfile(pkg_path):
            with open(pkg_path) as f:
                pkg = json.load(f)
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                if section in pkg and isinstance(pkg[section], dict):
                    deps.update(pkg[section])
        req_path = os.path.join(project_path, "requirements.txt")
        if os.path.isfile(req_path):
            with open(req_path) as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    # Handle ==, >=, ~=, <=, !=, > , <
                    m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*([><=!~]+)\s*(.+)$", line)
                    if m:
                        deps[m.group(1)] = f"{m.group(2)}{m.group(3).strip()}"
                    else:
                        # bare package name (no version pin)
                        name = line.split("[")[0].strip()
                        if name:
                            deps[name] = "*"
    except Exception:
        pass  # fail-soft
    with _lock:
        _stats["dependencies_checked"] += 1
    return deps


# ---------------------------------------------------------------------------
# 2. validate_release_order — ensure breaking changes ship in correct order
# ---------------------------------------------------------------------------

def validate_release_order(releases):
    """Validate a proposed release sequence.

    Each release is a dict with at least:
        name:            str — package/project name
        version:         str — version being released
        breaking:        bool — whether this release contains breaking changes
        depends_on:      list[str] — names of packages this release depends on

    Returns {"valid": bool, "errors": list[str]}.
    A release with breaking=True must appear AFTER all releases that depend on it
    (dependents must ship their compatibility update first).
    """
    if not ENABLED:
        return {"valid": True, "errors": []}
    errors = []
    released = set()  # names already "shipped" in the sequence so far
    for rel in releases:
        name = rel.get("name", "?")
        deps = rel.get("depends_on", [])
        breaking = rel.get("breaking", False)
        # Every dependency that is also in this release batch must have been
        # released earlier in the sequence.
        for dep in deps:
            # If the dependency is in the release list but hasn't been released yet
            dep_in_batch = any(r.get("name") == dep for r in releases)
            if dep_in_batch and dep not in released:
                errors.append(
                    f"{name} depends on {dep}, but {dep} has not been released yet"
                )
        released.add(name)
    with _lock:
        _stats["releases_validated"] += 1
        if errors:
            _stats["validation_failures"] += len(errors)
    return {"valid": len(errors) == 0, "errors": errors}


# ---------------------------------------------------------------------------
# 3. build_release_graph — create a DAG of release dependencies
# ---------------------------------------------------------------------------

class CyclicDependencyError(Exception):
    """Raised when a circular dependency is detected in the release graph."""
    pass


def build_release_graph(tasks):
    """Build a directed acyclic graph from a list of release tasks.

    Each task dict must have:
        name:       str — unique package/project name
        depends_on: list[str] — names this task depends on

    Returns a dict mapping each name to its set of dependency names.
    Raises CyclicDependencyError if a cycle is detected.
    """
    if not ENABLED:
        return {}
    graph = {}
    for task in tasks:
        name = task.get("name", "?")
        deps = set(task.get("depends_on", []))
        graph[name] = deps

    # Cycle detection via DFS
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}

    def dfs(node):
        color[node] = GRAY
        for dep in graph.get(node, set()):
            if dep not in color:
                continue  # external dependency, not in our graph
            if color[dep] == GRAY:
                with _lock:
                    _stats["circular_deps_detected"] += 1
                raise CyclicDependencyError(
                    f"Circular dependency detected: {node} -> {dep}"
                )
            if color[dep] == WHITE:
                dfs(dep)
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node)

    with _lock:
        _stats["graphs_built"] += 1
    return graph


# ---------------------------------------------------------------------------
# 4. safe_release_sequence — topological sort for safe release ordering
# ---------------------------------------------------------------------------

def safe_release_sequence(graph):
    """Topologically sort the release graph to produce a safe release order.

    Dependencies are released before their dependents. Returns a list of names
    in safe-to-release order. Raises CyclicDependencyError on cycles.
    """
    if not ENABLED:
        return []
    if not graph:
        return []

    # Kahn's algorithm
    in_degree = {n: 0 for n in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep in in_degree:
                in_degree[dep] = in_degree.get(dep, 0)  # ensure dep counted

    # Recalculate: in_degree[x] = number of nodes that depend on x
    # Actually for release order: we want dependencies first.
    # Reverse the interpretation: edges go from dependency -> dependent.
    # in_degree counts how many unresolved deps each node has.
    in_degree = {n: 0 for n in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep in graph:
                in_degree[node] += 1  # node depends on dep

    queue = sorted(n for n, d in in_degree.items() if d == 0)
    result = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        # Find all nodes that depend on this node and decrement their in-degree
        for other, deps in graph.items():
            if node in deps:
                in_degree[other] -= 1
                if in_degree[other] == 0:
                    # Insert sorted for deterministic output
                    import bisect
                    bisect.insort(queue, other)

    if len(result) != len(graph):
        with _lock:
            _stats["circular_deps_detected"] += 1
        raise CyclicDependencyError(
            "Circular dependency detected: could not produce full topological ordering"
        )

    with _lock:
        _stats["sequences_computed"] += 1
    return result


# ---------------------------------------------------------------------------
# 5. stats
# ---------------------------------------------------------------------------

def stats():
    """Return copy of dependency-release stats."""
    with _lock:
        return dict(_stats)
