#!/usr/bin/env python3
"""
speculative_parallel.py — Parallel speculative executor for independent subtasks.

Analyzes the task DAG to find groups of independent subtasks (no file conflicts,
no shared build artifacts), then spawns parallel executor workers per group.

This unblocks throughput beyond what sequential execution allows, even with
perfect branch management.

Env vars:
    ORCH_SPEC_PARALLEL_ENABLED    – "true" (default) / "false"
    ORCH_SPEC_PARALLEL_WORKERS    – max parallel workers per group (default 8)
    ORCH_SPEC_PARALLEL_TIMEOUT    – per-task timeout in seconds (default 90)
    ORCH_SPEC_PARALLEL_SKIP_INTEG – skip integration tests in speculation (default "true")
"""
import os, sys, re, threading, time, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("speculative_parallel")

ENABLED = os.environ.get("ORCH_SPEC_PARALLEL_ENABLED", "true").lower() == "true"
MAX_WORKERS = int(os.environ.get("ORCH_SPEC_PARALLEL_WORKERS", "8"))
TASK_TIMEOUT = int(os.environ.get("ORCH_SPEC_PARALLEL_TIMEOUT", "90"))
SKIP_INTEGRATION = os.environ.get("ORCH_SPEC_PARALLEL_SKIP_INTEG", "true").lower() == "true"

_lock = threading.Lock()
_stats = {
    "groups_analyzed": 0,
    "tasks_speculated": 0,
    "tasks_passed": 0,
    "tasks_failed": 0,
    "tasks_timed_out": 0,
}


# ---------------------------------------------------------------------------
# File-scope conflict detection
# ---------------------------------------------------------------------------

def _extract_file_scope(prompt):
    """Extract file paths mentioned in a task prompt."""
    if not prompt:
        return set()
    patterns = [
        r'(?:^|\s)([\w/\-\.]+\.(?:py|ts|tsx|js|jsx|json|yaml|yml|md|sql|sh))\b',
        r'(?:file|path|edit|modify|create|update)\s*:?\s*([\w/\-\.]+)',
    ]
    files = set()
    for pat in patterns:
        for m in re.finditer(pat, prompt, re.I):
            f = m.group(1).strip()
            if len(f) > 3 and '/' in f or '.' in f:
                files.add(f)
    return files


def find_independent_groups(tasks):
    """Partition tasks into groups where no two tasks in a group share files.

    Returns list of groups, each group is a list of tasks.
    Tasks with deps on each other are never in the same parallel group.
    """
    if not tasks:
        return []

    # Build file scope map
    scoped = []
    for t in tasks:
        files = _extract_file_scope(t.get("prompt", ""))
        slug = t.get("slug", "")
        deps = set(t.get("deps") or [])
        scoped.append({"task": t, "files": files, "slug": slug, "deps": deps})

    # Greedy grouping: add task to first group with no file overlap and no dep conflict
    groups = []
    for item in scoped:
        placed = False
        for group in groups:
            conflict = False
            for member in group:
                # Check file overlap
                if item["files"] & member["files"]:
                    conflict = True
                    break
                # Check dep conflict
                if item["slug"] in member["deps"] or member["slug"] in item["deps"]:
                    conflict = True
                    break
            if not conflict:
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])

    with _lock:
        _stats["groups_analyzed"] += len(groups)

    return [[item["task"] for item in group] for group in groups]


# ---------------------------------------------------------------------------
# Speculative execution
# ---------------------------------------------------------------------------

def _run_speculative_task(task, executor_fn, timeout_s):
    """Run a single task speculatively with timeout.

    executor_fn(task) should return {"ok": bool, "output": str, "error": Optional[str]}
    """
    slug = task.get("slug", "?")
    t0 = time.time()
    try:
        result = {"slug": slug, "ok": False, "output": "", "error": None, "elapsed": 0}
        # Use a thread-based timeout
        container = [None]

        def _run():
            container[0] = executor_fn(task)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=timeout_s)
        elapsed = time.time() - t0

        if t.is_alive():
            with _lock:
                _stats["tasks_timed_out"] += 1
            return {"slug": slug, "ok": False, "output": "",
                    "error": f"timeout after {timeout_s}s", "elapsed": elapsed,
                    "tag": "speculation-failed"}

        inner = container[0] or {"ok": False, "output": "", "error": "no result"}
        result = {
            "slug": slug,
            "ok": inner.get("ok", False),
            "output": inner.get("output", ""),
            "error": inner.get("error"),
            "elapsed": elapsed,
        }

        with _lock:
            if result["ok"]:
                _stats["tasks_passed"] += 1
            else:
                _stats["tasks_failed"] += 1
                result["tag"] = "speculation-failed"

        return result
    except Exception as e:
        with _lock:
            _stats["tasks_failed"] += 1
        return {"slug": slug, "ok": False, "output": "",
                "error": str(e), "elapsed": time.time() - t0,
                "tag": "speculation-failed"}


def run_parallel_speculation(tasks, executor_fn, max_workers=None, timeout=None):
    """Run a group of independent tasks in parallel speculatively.

    Args:
        tasks: list of task dicts
        executor_fn: callable(task) -> {"ok": bool, "output": str, "error": Optional[str]}
        max_workers: override for ORCH_SPEC_PARALLEL_WORKERS
        timeout: override for ORCH_SPEC_PARALLEL_TIMEOUT

    Returns:
        {"passed": [results], "failed": [results], "groups": int}
    """
    if not ENABLED:
        return {"passed": [], "failed": [], "groups": 0, "reason": "disabled"}

    workers = max_workers or MAX_WORKERS
    tout = timeout or TASK_TIMEOUT

    groups = find_independent_groups(tasks)
    passed = []
    failed = []

    for group in groups:
        effective_workers = min(workers, len(group))
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            futures = {
                pool.submit(_run_speculative_task, t, executor_fn, tout): t
                for t in group
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as e:
                    task = futures[future]
                    result = {"slug": task.get("slug", "?"), "ok": False,
                              "error": str(e), "tag": "speculation-failed"}

                if result.get("ok"):
                    passed.append(result)
                else:
                    failed.append(result)

        with _lock:
            _stats["tasks_speculated"] += len(group)

    return {"passed": passed, "failed": failed, "groups": len(groups)}


def stats():
    """Return copy of speculation stats."""
    with _lock:
        return dict(_stats)
