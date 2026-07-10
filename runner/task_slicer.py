#!/usr/bin/env python3
"""Automatic sub-subtask slicing before expensive agentic work."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

THRESHOLD = int(os.environ.get("ORCH_SLICE_PROMPT_CHARS", "2400"))
MAX_PARTS = int(os.environ.get("ORCH_SLICE_MAX_PARTS", "5"))
MAX_DEPTH = int(os.environ.get("ORCH_SLICE_MAX_DEPTH", "1"))
MARK = "auto-sliced-before-agent"
PROTECTED_PREFIXES = (
    "qafix-", "relfix-", "buildfix-", "deployfix-",
    "recover-missing-branch-", "rework-",
)


def should_slice(task):
    if not isinstance(task, dict):
        return False
    if os.environ.get("ORCH_AUTO_SLICE", "true").lower() not in ("1", "true", "yes", "on"):
        return False
    if MARK in str(task.get("note") or ""):
        return False
    slug = str(task.get("slug") or "")
    if slug.startswith(PROTECTED_PREFIXES):
        return False
    if slug.count("-slice-") >= MAX_DEPTH:
        return False
    prompt = str(task.get("prompt") or "")
    return len(prompt) >= THRESHOLD or prompt.count("\n- ") >= 6 or prompt.lower().count(" and ") >= 8


def _sentences(prompt):
    chunks = [c.strip(" -\n\t") for c in re.split(r"\n\s*[-*]\s+|(?<=[.!?])\s+", prompt) if c.strip()]
    return chunks or [prompt]


def slice_task(task):
    prompt = str(task.get("prompt") or "")
    chunks = _sentences(prompt)
    if len(chunks) <= 1:
        return []
    groups = [[] for _ in range(min(MAX_PARTS, max(2, len(chunks) // 2)))]
    for i, chunk in enumerate(chunks):
        groups[i % len(groups)].append(chunk)
    parts = []
    base = str(task.get("slug") or task.get("id") or "task")[:50]
    prev = None
    for idx, group in enumerate(groups):
        title = f"{base}-slice-{idx + 1}"
        body = "\n".join(f"- {g}" for g in group)
        deps = [prev] if prev else []
        parts.append({"slug": title, "prompt": body, "deps": deps})
        prev = title
    return parts


def pre_agent_hook(task):
    if not isinstance(task, dict) or not should_slice(task):
        return False
    parts = slice_task(task)
    if len(parts) < 2:
        return False
    inserted = 0
    for part in parts:
        row = {"project_id": task.get("project_id"), "slug": part["slug"],
               "kind": task.get("kind") or "build", "state": "QUEUED",
               "prompt": part["prompt"] + f"\n\nParent task: {task.get('slug')}",
               "deps": part["deps"], "base_branch": task.get("base_branch"),
               "note": f"{MARK}: parent={task.get('slug')}"}
        try:
            _insert_task(row)
            inserted += 1
        except Exception:
            pass
    if inserted:
        db.update("tasks", {"id": task["id"]}, {"state": "DECOMPOSED", "updated_at": "now()",
                                                "note": f"{MARK}: spawned {inserted} sub-subtasks"})
        return True
    return False


def _insert_task(row):
    variants = [
        row,
        {k: v for k, v in row.items() if k != "deps"},
        {k: v for k, v in row.items() if k not in ("deps", "base_branch")},
    ]
    for candidate in variants:
        try:
            db.insert("tasks", candidate)
            return True
        except Exception:
            continue
    raise RuntimeError("no compatible task insert shape")
