#!/usr/bin/env python3
"""Find tested-but-unintegrated work and feed it into the canonical merge train.

If passed work lost its agent branch, queue a tiny recovery task instead of
spending a full fresh draft immediately. Recovery prompts are reuse-first:
result cache, patch transplant, and patch templates are injected before any
agentic coder sees the task.
"""
import datetime
import json
import os
import sys
import subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import merge_train

LIMIT = int(os.environ.get("INTEGRATION_SWEEPER_LIMIT", "80"))
RUN_TRAIN = os.environ.get("INTEGRATION_SWEEPER_RUN_TRAIN", "true").lower() in ("true", "1", "yes")
RECOVERY_PREFIX = "recover-missing-branch-"
PRESSURE_KEY = "merge_train_pressure"
ACTIVE_STATES = "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,QUARANTINED)"

def _existing_recovery(project_id, slug):
    # Placeholder implementation for _existing_recovery function
    pass

def _normalize_base(repo, proj, base_branch):
    # Placeholder implementation for _normalize_base function
    return base_branch

def _reuse_context(task, proj, repo, base):
    # Placeholder implementation for _reuse_context function
    return ""

def _branch_exists(repo, branch):
    if not repo or not os.path.isdir(repo):
        return False
    return subprocess.run(["git", "rev-parse", "--verify", branch],
                          cwd=repo, capture_output=True).returncode == 0

def _branch_exists_anywhere(repo, branch):
    # Placeholder implementation for _branch_exists_anywhere function
    return False

# Added function to handle missing agent branches
def _handle_missing_branch(task, proj):
    slug = task.get("slug")
    if not slug or _existing_recovery(task.get("project_id"), slug):
        return False
    repo = proj.get("repo_path", "")
    base = _normalize_base(repo, proj, task.get("base_branch") or proj.get("default_base") or proj.get("prod_branch") or "main")
    reuse = _reuse_context(task, proj, repo, base)
    recovery_slug = f"{RECOVERY_PREFIX}{slug}"
    prompt = (
        "Recover tested-but-not-integrated work whose agent branch is missing.\n"
        f"Goal: recreate the smallest equivalent patch, commit it on agent/{recovery_slug}, "
        "run the project build/tests, and let the canonical merge train integrate it.\n"
        "Do not add new scope. Prefer cache/transplant/template context below before drafting.\n\n"
        f"Original slug: {slug}\n"
        f"Original task note: {(task.get('note') or '')[:1200]}\n\n"
        f"{reuse}\n\n"
        "Original prompt:\n"
        f"{task.get('prompt') or ''}"
    )
    force = task.get("force_coder") or "ollama"
    row = {"project_id": task.get("project_id"), "slug": recovery_slug, "prompt": prompt,
           "base_branch": base, "kind": task.get("kind") or "bugfix", "state": "QUEUED",
           "deps": [], "material": bool(task.get("material")),
           "force_coder": force,
           "model": force,
           "note": f"integration_sweeper: rebuild missing branch for {slug} using reuse-first context"}
    try:
        db.insert("tasks", row, upsert=True)
        db.update("tasks", {"id": task["id"]},
                  {"note": f"integration_sweeper: missing branch; queued recovery {recovery_slug}"})
        return True
    except Exception:
        return False

# Modified _queue_recovery function to use the new _handle_missing_branch function
def _queue_recovery(task, proj):
    if not _branch_exists_anywhere(proj.get("repo_path", ""), f"agent/{task.get('slug')}"):
        return _handle_missing_branch(task, proj)
    return False

# Rest of the file remains unchanged
