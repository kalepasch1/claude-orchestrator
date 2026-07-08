#!/usr/bin/env python3
"""Same-task agentic repair helpers.

The orchestrator still needs a claimable task state for workers to pick up work,
but a technical failure should not become a blind "try again" loop. These helpers
turn failures into an explicit repair contract on the original task: preserve prior
work, reproduce the concrete failure, fix the root cause, run checks, and commit.
"""
import os

import pipeline_contract


MARKER = "AGENTIC-REPAIR DIRECTIVE"
MAX_PROMPT_CHARS = int(os.environ.get("ORCH_AGENTIC_REPAIR_PROMPT_CHARS", "18000"))
TECHNICAL_CATEGORIES = {
    "buildfail",
    "testfail",
    "quality",
    "verify",
    "judge",
    "noop",
    "missing-branch",
    "conflict",
    "timeout",
    "runner-exception",
    "capacity",
    "transient",
    "orphaned-running",
    "stale-merging",
    "approval",
    "oversized",
    "rework",
}
REPLACEMENT_ONLY_CATEGORIES = {"legal", "secret", "security"}


def is_technical(category):
    return str(category or "rework") in TECHNICAL_CATEGORIES


def replacement_required(category):
    return str(category or "") in REPLACEMENT_ONLY_CATEGORIES


def _original_prompt(task):
    raw = task.get("prompt") or f"Implement the queued task '{task.get('slug')}'."
    try:
        raw = pipeline_contract.original_request(raw)
    except Exception:
        pass
    raw = raw.split(MARKER, 1)[0].rstrip()
    if len(raw) <= MAX_PROMPT_CHARS:
        return raw
    head = min(4500, MAX_PROMPT_CHARS // 3)
    tail = MAX_PROMPT_CHARS - head
    return (
        raw[:head].rstrip()
        + "\n\n[agentic-repair compaction: bulky middle context omitted. Inspect repository files, task artifacts, and logs directly.]\n\n"
        + raw[-tail:].lstrip()
    )


def _best_non_claude(task):
    try:
        import agentic_coders

        sensitivity = agentic_coders._task_sensitivity(task)
        candidates = []
        for spec in agentic_coders._pool():
            if spec.get("name") == "claude":
                continue
            if not agentic_coders._within_cap(spec):
                continue
            if not agentic_coders._allowed_by_terms(spec, sensitivity):
                continue
            candidates.append(spec)
        if candidates:
            candidates.sort(key=lambda c: (float(c.get("cost") or 9), -int(c.get("cap") or 0), c.get("name") or ""))
            return candidates[0].get("name")
    except Exception:
        pass
    return None


def _default_coder():
    return os.environ.get("ORCH_REPAIR_CODER") or os.environ.get("ORCH_AGENTIC_REPAIR_DEFAULT_CODER") or "ollama"


def choose_coder(task, category="rework", prefer_non_claude=False):
    forced = str(task.get("force_coder") or "").strip()
    if forced:
        return forced
    existing = str(task.get("model") or "").strip()
    if existing and existing.lower() not in ("auto", "claude", "sonnet", "opus"):
        return existing
    if prefer_non_claude or category in {"capacity", "transient"}:
        # Remediation must never block on expensive route-economics DB queries. Use a
        # configured/local repair coder first; opt into the full router only below.
        return _default_coder()
    if os.environ.get("ORCH_AGENTIC_REPAIR_USE_ROUTER", "false").lower() not in ("1", "true", "yes", "on"):
        return _default_coder()
    try:
        import agentic_coders

        need = 9 if category in {"buildfail", "testfail", "conflict", "missing-branch"} else 8
        return agentic_coders.pick({**task, "_need": need, "kind": task.get("kind") or "bugfix"})
    except Exception:
        return _default_coder()


def _agentic_artifacts_context(slug):
    """Return a formatted block of prior task artifacts for repair context, or empty string."""
    if not slug:
        return ""
    try:
        import task_artifacts
        art = task_artifacts.get_artifacts(str(slug))
        if not art:
            return ""
        parts = []
        touched = art.get("touched_files") or ""
        if touched and touched != "[]":
            try:
                import json as _json
                files = _json.loads(touched) if isinstance(touched, str) else touched
                if files:
                    parts.append("Touched files from prior run: " + ", ".join(str(f) for f in files[:20]))
            except Exception:
                parts.append(f"Touched files from prior run: {touched[:300]}")
        sha = art.get("commit_sha") or ""
        if sha:
            parts.append(f"Prior commit SHA: {sha}")
        diff = art.get("patch_diff") or ""
        if diff:
            diff_head = diff[:3000].rstrip()
            parts.append(f"Prior patch diff (truncated):\n```diff\n{diff_head}\n```")
        if not parts:
            return ""
        return "Agentic analysis artifacts from prior run:\n" + "\n".join(parts) + "\n\n"
    except Exception:
        return ""


def repair_prompt(task, failure, directive, category="rework"):
    failure_text = str(failure or "")[-5000:]
    category = str(category or "rework")
    slug = task.get("slug") or task.get("id")
    artifacts_context = _agentic_artifacts_context(slug)
    return (
        f"{_original_prompt(task)}\n\n"
        f"{MARKER}\n"
        f"Repair category: {category}\n"
        f"Original task slug: {slug}\n\n"
        "This is not a fresh requeue. Continue the same implementation to completion. Preserve any useful prior work, "
        "inspect the existing branch/worktree/artifacts first, and fix the root cause of the failure below.\n\n"
        f"{directive}\n\n"
        "Required completion behavior:\n"
        "- Reproduce or inspect the concrete failure before changing broad strategy.\n"
        "- If dependencies/build tools are missing, repair the repo setup or install path minimally.\n"
        "- If tests/build fail, fix source/config/tests until the relevant checks are green.\n"
        "- If the branch/worktree is missing, reconstruct the smallest equivalent patch from artifacts, templates, or prior diffs.\n"
        "- Commit the final implementation on the task branch. Do not finish with only analysis, a plan, or no file changes.\n\n"
        f"{artifacts_context}"
        "Failure context:\n"
        f"```\n{failure_text}\n```\n"
    )


def in_session_prompt(task, failure, category="rework", directive=None):
    directive = directive or "Fix the error in-place and rerun the failing checks before returning."
    return repair_prompt(task, failure, directive, category=category)


def repair_patch(task, failure, category="rework", directive=None, prefer_non_claude=False):
    category = str(category or "rework")
    coder = choose_coder(task, category=category, prefer_non_claude=prefer_non_claude)
    rc = int(task.get("remediation_count") or 0) + 1
    directive = directive or "Complete the implementation through the agentic coder and make the build/test path green."
    patch = {
        "state": "QUEUED",
        "account": None,
        "updated_at": "now()",
        "remediation_count": rc,
        "attempt": int(task.get("attempt") or 0) + 1,
        "prompt": repair_prompt(task, failure, directive, category=category),
        "note": f"agentic-repair:{category}; same-task repair via {coder}",
    }
    if coder:
        patch["force_coder"] = coder
        patch["model"] = coder
    return patch
