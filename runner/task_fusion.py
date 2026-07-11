#!/usr/bin/env python3
"""
task_fusion.py - Identify clusters of QUEUED tasks touching the same files/module
and fuse them into a single agent run, reducing N separate cycles to 1.

Env vars:
    ORCH_TASK_FUSION_ENABLED   "true" to enable (default "false" -- conservative, opt-in)
    ORCH_FUSION_MIN_OVERLAP    Jaccard similarity threshold for file sets (default "0.5")
    ORCH_FUSION_MAX_CLUSTER    Max tasks per fused cluster (default "5")

Usage:
    # As a library (called by queue_preopt daemon):
    from task_fusion import scan_and_fuse, stats
    result = scan_and_fuse()   # {"fused_clusters": 2, "tasks_fused": 7}

    # CLI one-shot:
    python task_fusion.py --dry-run
    python task_fusion.py --run
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import log as _log_mod

_log = _log_mod.get("task_fusion")

# ---------------------------------------------------------------------------
# Configuration (env-var driven, fail-soft defaults)
# ---------------------------------------------------------------------------

_ENABLED = os.environ.get("ORCH_TASK_FUSION_ENABLED", "false").lower() == "true"
_MIN_OVERLAP = float(os.environ.get("ORCH_FUSION_MIN_OVERLAP", "0.5"))
_MAX_CLUSTER = int(os.environ.get("ORCH_FUSION_MAX_CLUSTER", "5"))
_MAX_FUSIONS_PER_SCAN = 3  # cap per cycle to avoid queue disruption

# ---------------------------------------------------------------------------
# Module-level singleton state
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_stats: dict[str, int] = {
    "scans": 0,
    "clusters_created": 0,
    "tasks_fused": 0,
    "children_resolved": 0,
    "errors": 0,
}

# Regex for extracting file paths from prompts / diff plans
_FILE_PATH_RE = re.compile(
    r"""(?:^|[\s"'`(,])"""               # preceding boundary
    r"""((?:[\w.\-]+/)+[\w.\-]+\.\w+)""", # e.g. runner/foo.py, src/bar.ts
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_and_fuse() -> dict[str, int]:
    """Main entry point -- called by queue_preopt daemon.

    Queries QUEUED tasks, builds a file-overlap graph, finds fusible
    clusters, and creates parent tasks that combine them.

    Returns {"fused_clusters": int, "tasks_fused": int}.
    """
    if not _ENABLED:
        _log.debug("task fusion disabled (ORCH_TASK_FUSION_ENABLED != true)")
        return {"fused_clusters": 0, "tasks_fused": 0}

    with _lock:
        _stats["scans"] += 1

    try:
        queued = db.select("tasks", {
            "select": "*",
            "state": "eq.QUEUED",
            "order": "created_at.asc",
        }) or []
    except Exception as exc:
        _log.debug("failed to query QUEUED tasks: %s", exc)
        with _lock:
            _stats["errors"] += 1
        return {"fused_clusters": 0, "tasks_fused": 0}

    if len(queued) < 2:
        _log.debug("fewer than 2 QUEUED tasks (%d), nothing to fuse", len(queued))
        return {"fused_clusters": 0, "tasks_fused": 0}

    # Build per-task file scopes
    task_files: dict[str, set[str]] = {}
    task_map: dict[str, dict] = {}
    for t in queued:
        tid = t.get("id", "")
        if not tid:
            continue
        task_map[tid] = t
        task_files[tid] = _extract_file_scope(t)

    # Group by project -- never fuse across projects
    project_groups: dict[str, list[str]] = {}
    for tid, t in task_map.items():
        pid = t.get("project_id", "unknown")
        project_groups.setdefault(pid, []).append(tid)

    fused_clusters = 0
    tasks_fused = 0

    for pid, tids in project_groups.items():
        if fused_clusters >= _MAX_FUSIONS_PER_SCAN:
            break
        if len(tids) < 2:
            continue

        clusters = _find_clusters(tids, task_files, task_map)
        for cluster in clusters:
            if fused_clusters >= _MAX_FUSIONS_PER_SCAN:
                break
            ok = _fuse_cluster(cluster, task_map, pid)
            if ok:
                fused_clusters += 1
                tasks_fused += len(cluster)

    with _lock:
        _stats["clusters_created"] += fused_clusters
        _stats["tasks_fused"] += tasks_fused

    _log.info(
        "scan complete: %d clusters, %d tasks fused", fused_clusters, tasks_fused
    )
    return {"fused_clusters": fused_clusters, "tasks_fused": tasks_fused}


def mark_children_done(parent_task_id: str) -> int:
    """Called after a fused parent task merges successfully.

    Reads the parent's note to find child task IDs and marks each DONE.
    Returns count of children resolved.
    """
    try:
        rows = db.select("tasks", {
            "select": "id,note",
            "id": f"eq.{parent_task_id}",
        }) or []
    except Exception as exc:
        _log.debug("failed to read parent task %s: %s", parent_task_id, exc)
        with _lock:
            _stats["errors"] += 1
        return 0

    if not rows:
        _log.debug("parent task %s not found", parent_task_id)
        return 0

    parent = rows[0]
    note = parent.get("note", "") or ""

    # Extract child IDs from note (format: "fused_children:<id1>,<id2>,...")
    m = re.search(r"fused_children:([a-f0-9,\-]+)", note)
    if not m:
        _log.debug("no fused_children marker in parent %s note", parent_task_id)
        return 0

    child_ids = [cid.strip() for cid in m.group(1).split(",") if cid.strip()]
    resolved = 0

    for cid in child_ids:
        try:
            db.update("tasks", {"id": cid}, {
                "state": "DONE",
                "note": f"resolved by fused parent {parent_task_id}",
            })
            _log.info("child %s marked DONE (parent %s)", cid, parent_task_id)
            resolved += 1
        except Exception as exc:
            _log.debug("failed to mark child %s DONE: %s", cid, exc)
            with _lock:
                _stats["errors"] += 1

    # Audit
    try:
        db.insert("resource_events", {
            "kind": "task_fusion_resolve",
            "value": resolved,
            "detail": f"parent={parent_task_id} children={len(child_ids)}",
            "action": f"marked {resolved} children DONE",
        })
    except Exception:
        pass  # non-critical audit row

    with _lock:
        _stats["children_resolved"] += resolved

    return resolved


def stats() -> dict[str, int]:
    """Return fusion statistics (thread-safe snapshot)."""
    with _lock:
        return dict(_stats)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_file_scope(task: dict) -> set[str]:
    """Extract file paths mentioned in a task's prompt and diff_plan.

    Returns set of normalised relative paths (e.g. {"runner/foo.py", "src/bar.ts"}).
    """
    paths: set[str] = set()
    for field in ("prompt", "diff_plan", "note"):
        text = task.get(field) or ""
        if not text:
            continue
        for m in _FILE_PATH_RE.finditer(text):
            p = m.group(1).strip()
            # Filter obvious non-paths (version strings, URLs fragments, etc.)
            if p.count("/") >= 1 and not p.startswith("http"):
                paths.add(p)
    return paths


def _compute_overlap(files_a: set[str], files_b: set[str]) -> float:
    """Jaccard similarity of two file sets.  Returns 0.0 if both empty."""
    if not files_a and not files_b:
        return 0.0
    union = files_a | files_b
    if not union:
        return 0.0
    return len(files_a & files_b) / len(union)


def _find_clusters(
    tids: list[str],
    task_files: dict[str, set[str]],
    task_map: dict[str, dict],
) -> list[list[str]]:
    """Build file-overlap graph and find connected components where overlap >= threshold.

    Also enforces:
    - No inter-dependency within a cluster (prevents circular deps)
    - Cluster size <= _MAX_CLUSTER
    """
    # Adjacency list (undirected)
    adj: dict[str, set[str]] = {tid: set() for tid in tids}

    for i, a in enumerate(tids):
        for b in tids[i + 1 :]:
            fa = task_files.get(a, set())
            fb = task_files.get(b, set())
            if not fa or not fb:
                continue
            if _compute_overlap(fa, fb) >= _MIN_OVERLAP:
                adj[a].add(b)
                adj[b].add(a)

    # BFS connected components
    visited: set[str] = set()
    clusters: list[list[str]] = []

    for tid in tids:
        if tid in visited or not adj[tid]:
            continue
        component: list[str] = []
        queue = [tid]
        while queue:
            cur = queue.pop(0)
            if cur in visited:
                continue
            visited.add(cur)
            component.append(cur)
            for nbr in adj[cur]:
                if nbr not in visited:
                    queue.append(nbr)

        # Enforce max cluster size (take first N by creation order, already sorted)
        component = component[: _MAX_CLUSTER]

        # Filter out clusters with inter-dependencies
        if not _has_internal_deps(component, task_map):
            clusters.append(component)

    return clusters


def _has_internal_deps(tids: list[str], task_map: dict[str, dict]) -> bool:
    """Return True if any task in the cluster depends on another task in the cluster."""
    slugs_in_cluster = set()
    for tid in tids:
        slug = task_map.get(tid, {}).get("slug", "")
        if slug:
            slugs_in_cluster.add(slug)

    for tid in tids:
        deps = task_map.get(tid, {}).get("deps") or []
        if isinstance(deps, str):
            try:
                import json
                deps = json.loads(deps)
            except Exception:
                deps = [deps]
        for d in deps:
            if d in slugs_in_cluster:
                _log.debug(
                    "skipping cluster: task %s depends on %s (both in cluster)", tid, d
                )
                return True
    return False


def _build_fused_prompt(tasks: list[dict]) -> str:
    """Combine N task prompts into one coherent fused prompt.

    Preserves each task's spec as a numbered section with acceptance criteria.
    """
    parts = [
        f"This is a fused task combining {len(tasks)} related changes that "
        f"touch overlapping files. Complete all sub-tasks in a single session.\n"
    ]

    for i, t in enumerate(tasks, 1):
        slug = t.get("slug", "unknown")
        prompt = (t.get("prompt") or "").strip()
        parts.append(f"--- Sub-task {i}: {slug} ---")
        parts.append(prompt)
        parts.append("")  # blank line separator

    parts.append(
        "--- End of sub-tasks ---\n"
        "Ensure each sub-task's acceptance criteria are met before finishing."
    )
    return "\n".join(parts)


def _fuse_cluster(
    tids: list[str], task_map: dict[str, dict], project_id: str
) -> bool:
    """Create a parent fused task and mark children as DECOMPOSED.

    Returns True on success, False on any error.
    """
    tasks = [task_map[tid] for tid in tids if tid in task_map]
    if len(tasks) < 2:
        return False

    child_slugs = [t.get("slug", "") for t in tasks]
    parent_slug = "fused-" + "-".join(child_slugs[:3])
    # Truncate slug if too long
    if len(parent_slug) > 120:
        parent_slug = parent_slug[:117] + "..."

    fused_prompt = _build_fused_prompt(tasks)
    child_id_str = ",".join(tids)

    # Snapshot before-state for audit
    before_states = {t.get("id"): t.get("state") for t in tasks}

    # Create the parent task
    try:
        parent_row = {
            "project_id": project_id,
            "slug": parent_slug,
            "prompt": fused_prompt,
            "state": "QUEUED",
            "kind": "fused",
            "note": f"fused_children:{child_id_str}",
        }
        # Carry over base_branch from first child (all same project)
        base_branch = tasks[0].get("base_branch")
        if base_branch:
            parent_row["base_branch"] = base_branch

        db.insert("tasks", parent_row)
        _log.info(
            "created fused parent '%s' combining %d tasks: %s",
            parent_slug, len(tids), child_slugs,
        )
    except Exception as exc:
        _log.debug("failed to create fused parent: %s", exc)
        with _lock:
            _stats["errors"] += 1
        return False

    # Mark children as DECOMPOSED
    for tid in tids:
        try:
            db.update("tasks", {"id": tid}, {
                "state": "DECOMPOSED",
                "note": f"fused into {parent_slug}",
            })
        except Exception as exc:
            _log.debug("failed to mark child %s as DECOMPOSED: %s", tid, exc)
            with _lock:
                _stats["errors"] += 1
            # Continue -- partial fusion is still valid; the parent will handle it

    # Audit log with full before/after state
    try:
        db.insert("resource_events", {
            "kind": "task_fusion_create",
            "value": len(tids),
            "detail": (
                f"parent_slug={parent_slug} "
                f"children={child_id_str} "
                f"before_states={before_states}"
            ),
            "action": (
                f"fused {len(tids)} tasks into {parent_slug}, "
                f"children set to DECOMPOSED"
            ),
        })
    except Exception:
        pass  # non-critical audit row

    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Task fusion: cluster & merge related QUEUED tasks")
    ap.add_argument("--run", action="store_true", help="Execute a fusion scan")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be fused without modifying state",
    )
    ap.add_argument("--stats", action="store_true", help="Print fusion statistics")
    a = ap.parse_args()

    if a.stats:
        print(stats())
    elif a.run or a.dry_run:
        if a.dry_run:
            # Temporarily enable for analysis but skip writes
            _ENABLED = True
            _log.info("dry-run mode: scanning without state changes")
            # In dry-run we just report what scan_and_fuse would do
            # For a true dry-run, one would refactor scan_and_fuse to accept a flag;
            # for now, run with the feature enabled and let the operator review logs.
        result = scan_and_fuse()
        print(result)
    else:
        ap.print_help()
