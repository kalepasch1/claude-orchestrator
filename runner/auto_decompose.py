#!/usr/bin/env python3
"""
auto_decompose.py - Automated task decomposition helpers.

Augments planner.py with heuristics for automatic decomposition of
large tasks without requiring a model call. Handles common patterns:
    - Tasks with multiple file scopes → split by file
    - Tasks with numbered sub-items → split by item
    - Recovery tasks → reconstruct minimal patches

Also provides bottleneck-aware prioritization: reads live queue state
and adjusts decomposition to favor tasks that unblock the most work.

Env:
    ORCH_AUTO_DECOMPOSE_ENABLED   (default "true")
    ORCH_DECOMPOSE_MAX_FILES      (default "3") — split if more files
"""
import os, sys, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ENABLED = os.environ.get("ORCH_AUTO_DECOMPOSE_ENABLED", "true").lower() in ("true", "1")
_MAX_FILES = int(os.environ.get("ORCH_DECOMPOSE_MAX_FILES", "3"))
# Hard cap on children emitted per parent; overflow goes to ONE remainder task,
# never silently dropped. Bounds the slice-N fan-out (swarm backlog rank 6).
_MAX_CHILDREN = int(os.environ.get("ORCH_DECOMPOSE_MAX_CHILDREN", "8"))

# A slug that is itself a decomposition child. Re-decomposing children is the
# multiplier that turned ~1,782 parents into ~8,318 slice-N tokens; refuse it.
_CHILD_SUFFIX = re.compile(r'-(?:item|file|slice)-\d+$', re.I)


def is_decomposition_child(slug: str) -> bool:
    """True if slug was already produced by a prior decomposition."""
    return bool(_CHILD_SUFFIX.search(slug or ""))


def _finalize(tasks: list, slug: str, base_branch: str) -> list:
    """Cap fan-out to _MAX_CHILDREN (+1 remainder carrying the overflow, never a
    silent drop) and stamp a deterministic dedup_key so retries coalesce on the
    enqueue side instead of minting duplicate rows."""
    if len(tasks) > _MAX_CHILDREN:
        head = tasks[:_MAX_CHILDREN]
        overflow = tasks[_MAX_CHILDREN:]
        head.append({
            "slug": f"{slug}-remainder",
            "prompt": "Remaining decomposed items (NOT dropped — process these too):\n\n"
                      + "\n\n".join(t.get("prompt", "") for t in overflow),
            "deps": [],
            "base_branch": base_branch,
        })
        tasks = head
    for t in tasks:
        t.setdefault("dedup_key", t["slug"])
    return tasks

def extract_file_scopes(prompt: str) -> list:
    """Extract file paths mentioned in a task prompt."""
    try:
        patterns = [
            re.compile(r'(?:runner|scripts|packages|web|deploy)/[\w/]+\.(?:py|ts|js|sql)', re.I),
            re.compile(r'[\w_]+\.(?:py|ts|js)', re.I),
        ]
        files = set()
        for pat in patterns:
            files.update(pat.findall(prompt))
        return sorted(files)
    except Exception:
        return []


def extract_numbered_items(prompt: str) -> list:
    """Extract numbered sub-items from a prompt (e.g. '1. Do X  2. Do Y')."""
    try:
        items = re.findall(r'(?:^|\n)\s*(\d+)\.\s+(.+?)(?=\n\s*\d+\.|\n\n|$)', prompt, re.S)
        return [{"num": int(n), "text": t.strip()} for n, t in items if t.strip()]
    except Exception:
        return []


def should_decompose(prompt: str, slug: str = None) -> bool:
    """Heuristic: should this prompt be auto-decomposed?"""
    if not _ENABLED:
        return False
    if is_decomposition_child(slug):
        return False
    try:
        files = extract_file_scopes(prompt)
        items = extract_numbered_items(prompt)
        return len(files) > _MAX_FILES or len(items) > 2
    except Exception:
        return False


def _emit_decomposition(slug, tasks, repo_path, base_branch):
    """Notify the branch provisioner after a real decomposition. Fail-soft."""
    if len(tasks) <= 1:
        return tasks
    try:
        if __package__:
            from . import decomposition_events
        else:
            import decomposition_events
        decomposition_events.on_decomposition_completed(
            slug, tasks, repo_path=repo_path, base_branch=base_branch
        )
    except Exception:
        pass
    return tasks


def decompose(slug: str, prompt: str, base_branch: str = "master",
              repo_path: str = None) -> list:
    """Auto-decompose a task into sub-tasks. Returns list of task dicts.
    Falls back to returning the original as a single task. Fail-soft."""
    single = [{"slug": slug, "prompt": prompt, "deps": [],
               "base_branch": base_branch, "dedup_key": slug}]
    if not _ENABLED:
        return single
    # Idempotency guard: a task that is itself a decomposition child is NEVER
    # re-decomposed (that recursion is the slice-N multiplier). Return as-is.
    if is_decomposition_child(slug):
        return single
    try:
        files = extract_file_scopes(prompt)
        items = extract_numbered_items(prompt)

        # Strategy 1: split by numbered items
        if len(items) > 2:
            tasks = [{"slug": f"{slug}-item-{item['num']}", "prompt": item["text"],
                      "deps": [], "base_branch": base_branch} for item in items]
            return _emit_decomposition(slug, _finalize(tasks, slug, base_branch),
                                       repo_path, base_branch)

        # Strategy 2: split by file scope
        if len(files) > _MAX_FILES:
            tasks = [{"slug": f"{slug}-file-{i}", "prompt": f"In file {f}:\n{prompt}",
                      "deps": [], "base_branch": base_branch} for i, f in enumerate(files)]
            return _emit_decomposition(slug, _finalize(tasks, slug, base_branch),
                                       repo_path, base_branch)

        # No decomposition needed
        return single
    except Exception:
        return single


def prioritize_by_bottleneck(tasks: list, queue_stats: dict) -> list:
    """Re-order tasks to favor those that unblock the most downstream work.
    queue_stats has keys like missing_branch, passed_waiting. Fail-soft."""
    try:
        missing = queue_stats.get("missing_branch", 0)
        if missing > 5:
            # Prioritize recovery/branch-related tasks
            def _key(t):
                p = t.get("prompt", "").lower()
                if "branch" in p or "recover" in p or "missing" in p:
                    return 0
                return 1
            return sorted(tasks, key=_key)
        return tasks
    except Exception:
        return tasks
