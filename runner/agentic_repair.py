#!/usr/bin/env python3
"""Same-task agentic repair helpers.

repair_patch(): build a db.update patch that re-queues a task in place, with an
agentic-repair prompt instead of the original. Used by auto_remediate, merge_train,
queue_janitor, blocker_quarantine, and runner.

in_session_prompt(): build the repair prompt string for callers that inject it
directly into a live in-session task dict (runner._agentic_repair_continue).
"""
import os

MARKER = "AGENTIC-REPAIR DIRECTIVE"

_DEFAULT_DIRECTIVE = (
    "Reproduce or inspect the concrete failure before changing broad strategy. "
    "Preserve any useful prior work, repair the root cause, run the relevant checks, and commit."
)


def choose_coder(task):
    """Return the coder to use for agentic repair of this task.

    Checks ORCH_AGENTIC_REPAIR_DEFAULT_CODER first; if unset, delegates to
    agentic_coders.pick() so the full router decides. Falls back to 'ollama' if
    the router is unavailable.
    """
    default = os.environ.get("ORCH_AGENTIC_REPAIR_DEFAULT_CODER")
    if default:
        return default
    try:
        import agentic_coders  # type: ignore
        return agentic_coders.pick(task) or "ollama"
    except Exception:
        return "ollama"


def in_session_prompt(task, failure, category="rework", directive=None):
    directive = directive or _DEFAULT_DIRECTIVE
    base = (task.get("prompt") or f"Complete the task '{task.get('slug')}'.").strip()
    touched = task.get("touched_files") or "unknown"
    sha = task.get("commit_sha") or "unknown"
    log = str(task.get("log_tail") or task.get("note") or failure or "")[:1000]
    diff = str(failure or "")[:2000]
    repair = (
        f"\n\n{MARKER}\n"
        f"Repair category: {category}\n"
        f"Original task slug: {task.get('slug') or task.get('id')}\n\n"
        f"This is not a fresh requeue. Continue the same implementation to completion. "
        f"Preserve any useful prior work, inspect the existing branch/worktree/artifacts first, "
        f"and fix the root cause of the failure below.\n\n"
        f"{directive}\n\n"
        f"Required completion behavior:\n"
        f"- Reproduce or inspect the concrete failure before changing broad strategy.\n"
        f"- If dependencies/build tools are missing, repair the repo setup or install path minimally.\n"
        f"- If tests/build fail, fix source/config/tests until the relevant checks are green.\n"
        f"- If the branch/worktree is missing, reconstruct the smallest equivalent patch from artifacts, templates, or prior diffs.\n"
        f"- Commit the final implementation on the task branch. Do not finish with only analysis, a plan, or no file changes.\n\n"
        f"Agentic analysis artifacts from prior run:\n"
        f"Touched files from prior run: {touched}\n"
        f"Prior commit SHA: {sha}\n"
        f"Prior patch diff (truncated):\n```diff\n{diff}\n```\n\n"
        f"Failure context:\n```\n{log}\n```\n\n"
        f"bugfix"
    )
    return base + repair


def repair_patch(task, signal, category="rework", directive=None, prefer_non_claude=False):
    """Return a db.update patch dict that re-queues a task with an agentic repair prompt.

    Values are never logged; pass the result directly to db.update.
    """
    prompt = in_session_prompt(task, signal, category=category, directive=directive)
    rc = int(task.get("remediation_count") or 0)
    coder = choose_coder(task)
    patch = {
        "state": "QUEUED",
        "prompt": prompt,
        "account": None,
        "updated_at": "now()",
        "remediation_count": rc + 1,
        "force_coder": coder,
        "model": coder,
        "note": f"agentic-repair:{category}",
    }
    return patch
