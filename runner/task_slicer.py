#!/usr/bin/env python3
"""Automatic sub-subtask slicing before expensive agentic work."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

THRESHOLD = int(os.environ.get("ORCH_SLICE_PROMPT_CHARS", "2400"))
MAX_PARTS = int(os.environ.get("ORCH_SLICE_MAX_PARTS", "5"))
MAX_DEPTH = int(os.environ.get("ORCH_SLICE_MAX_DEPTH", "1"))
MARK = "auto-sliced-before-agent"
AI_SLICE_MODEL = os.environ.get("ORCH_AI_SLICE_MODEL", "claude-haiku-4-5-20251001")
PROTECTED_PREFIXES = (
    "qafix-", "relfix-", "buildfix-", "deployfix-",
    "recover-missing-branch-", "rework-",
)


def should_slice(task):
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


_AI_SLICE_PROMPT = """\
You are a task decomposition assistant for an autonomous code orchestration system.
Break the following task prompt into {n} independent sub-tasks that can be worked
on sequentially. Each sub-task should be a self-contained unit of work.

Return ONLY a JSON array with {n} objects, each with:
  "title": short kebab-case suffix (will be appended to the parent slug)
  "prompt": the full sub-task prompt (copy relevant context from the parent)

Keep titles under 20 chars. Do not include explanations outside the JSON.

Parent slug: {slug}
Parent prompt:
{prompt}
"""


def ai_slice_task(task):
    """Use Claude to decompose a task into semantically meaningful slices.

    Returns the same format as slice_task() — list of {"slug", "prompt", "deps"} dicts —
    or None if AI slicing is disabled, fails, or produces unusable output.
    """
    if os.environ.get("ORCH_AI_SLICE", "false").lower() not in ("1", "true", "yes", "on"):
        return None
    try:
        import claude_cli
    except ImportError:
        return None

    prompt = str(task.get("prompt") or "")
    slug = str(task.get("slug") or task.get("id") or "task")
    n = min(MAX_PARTS, max(2, len(prompt) // 800))
    ai_prompt = _AI_SLICE_PROMPT.format(n=n, slug=slug, prompt=prompt[:6000])
    try:
        result = claude_cli.run(ai_prompt, AI_SLICE_MODEL, max_turns=1, timeout=60)
        raw = (result.get("text") or "").strip()
    except Exception:
        return None

    # Extract JSON array from the response (may have surrounding prose)
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if not match:
        return None
    try:
        items = json.loads(match.group(0))
    except Exception:
        return None
    if not isinstance(items, list) or len(items) < 2:
        return None

    base = slug[:50]
    parts = []
    prev = None
    for idx, item in enumerate(items[:MAX_PARTS]):
        if not isinstance(item, dict):
            continue
        title_suffix = re.sub(r"[^a-z0-9-]", "-", str(item.get("title") or f"part-{idx+1}").lower())[:20].strip("-")
        slice_slug = f"{base}-slice-{idx + 1}"
        body = str(item.get("prompt") or "").strip()
        if not body:
            continue
        deps = [prev] if prev else []
        parts.append({"slug": slice_slug, "prompt": body, "deps": deps})
        prev = slice_slug

    return parts if len(parts) >= 2 else None


def _slice_exists(task, slug):
    """True if a slice row with this slug already exists for the task's project (any state)."""
    try:
        rows = db.select("tasks", {"select": "id",
                                   "project_id": f"eq.{task.get('project_id')}",
                                   "slug": f"eq.{slug}",
                                   "limit": "1"}) or []
        # The DB contract is a list. Treat mock/sentinel/invalid return values
        # as no match instead of silently retiring a parent without children.
        return isinstance(rows, list) and bool(rows)
    except Exception:
        # DB unreachable: report absent so the normal path (which is also fail-soft) proceeds.
        return False


def pre_agent_hook(task):
    if not isinstance(task, dict) or not should_slice(task):
        return False
    parts = ai_slice_task(task) or slice_task(task)
    if len(parts) < 2:
        return False
    # Idempotency guard (2026-07-10): the parent used to flip to DECOMPOSED only AFTER the
    # slice inserts. Any DB blip on that final update left a QUEUED parent that re-sliced on
    # the next claim, re-inserting the same 5 slugs — the dominant source of sentinel-dedupe
    # quarantines (235/255 quarantined rows on 2026-07-09/10 were *-slice-N). If slices
    # already exist, just finish flipping the parent.
    if _slice_exists(task, parts[0]["slug"]):
        try:
            db.update("tasks", {"id": task["id"]},
                      {"state": "DECOMPOSED", "updated_at": "now()",
                       "note": f"{MARK}: slices already present; parent flip retried"})
        except Exception:
            pass
        return True
    # Flip the parent BEFORE inserting slices so a mid-insert failure can never leave a
    # QUEUED parent alongside live slices. If the flip itself fails, do nothing this cycle.
    try:
        db.update("tasks", {"id": task["id"]},
                  {"state": "DECOMPOSED", "updated_at": "now()",
                   "note": f"{MARK}: spawning {len(parts)} sub-subtasks"})
    except Exception:
        return False
    inserted = 0
    for part in parts:
        row = {"project_id": task.get("project_id"), "slug": part["slug"],
               "kind": task.get("kind") or "build", "state": "QUEUED",
               "prompt": part["prompt"] + f"\n\nParent task: {task.get('slug')}",
               "deps": part["deps"], "base_branch": task.get("base_branch"),
               "note": f"{MARK}: parent={task.get('slug')}"}
        try:
            if _slice_exists(task, part["slug"]):
                inserted += 1  # already landed on a previous attempt
                continue
            _insert_task(row)
            inserted += 1
        except Exception:
            pass
    if not inserted:
        # Nothing landed — restore the parent so the work isn't silently lost.
        try:
            db.update("tasks", {"id": task["id"]},
                      {"state": "QUEUED", "updated_at": "now()",
                       "note": f"{MARK}: slice inserts failed; parent restored"})
        except Exception:
            pass
        return False
    return True


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
