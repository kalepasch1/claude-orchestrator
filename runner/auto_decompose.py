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


def should_decompose(prompt: str) -> bool:
    """Heuristic: should this prompt be auto-decomposed?"""
    if not _ENABLED:
        return False
    try:
        files = extract_file_scopes(prompt)
        items = extract_numbered_items(prompt)
        return len(files) > _MAX_FILES or len(items) > 2
    except Exception:
        return False


def decompose(slug: str, prompt: str, base_branch: str = "master") -> list:
    """Auto-decompose a task into sub-tasks. Returns list of task dicts.
    Falls back to returning the original as a single task. Fail-soft."""
    if not _ENABLED:
        return [{"slug": slug, "prompt": prompt, "deps": [], "base_branch": base_branch}]
    try:
        files = extract_file_scopes(prompt)
        items = extract_numbered_items(prompt)

        # Strategy 1: split by numbered items
        if len(items) > 2:
            tasks = []
            for item in items:
                sub_slug = f"{slug}-item-{item['num']}"
                tasks.append({"slug": sub_slug, "prompt": item["text"],
                              "deps": [], "base_branch": base_branch})
            return tasks

        # Strategy 2: split by file scope
        if len(files) > _MAX_FILES:
            tasks = []
            for i, f in enumerate(files):
                sub_slug = f"{slug}-file-{i}"
                file_prompt = f"In file {f}:\n{prompt}"
                tasks.append({"slug": sub_slug, "prompt": file_prompt,
                              "deps": [], "base_branch": base_branch})
            return tasks

        # No decomposition needed
        return [{"slug": slug, "prompt": prompt, "deps": [], "base_branch": base_branch}]
    except Exception:
        return [{"slug": slug, "prompt": prompt, "deps": [], "base_branch": base_branch}]


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
