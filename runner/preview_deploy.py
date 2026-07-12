#!/usr/bin/env python3
"""
preview_deploy.py — wire preview deployment into the merge/deploy path.

After a merge completes, triggers a preview deploy to the isolated preview_env,
captures deployment metadata (env URL, timestamp, git SHA), and logs deploy
start/completion.

Integrates with merge_train.py as a post-merge hook.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
DEPLOY_LOG = os.path.join(HOME, "preview-deployments.json")
os.makedirs(HOME, exist_ok=True)


def _load_deploy_log():
    try:
        with open(DEPLOY_LOG) as f:
            return json.load(f)
    except Exception:
        return []


def _save_deploy_log(entries):
    with open(DEPLOY_LOG, "w") as f:
        json.dump(entries, f, indent=2)


def _get_git_sha(repo_path):
    """Get current HEAD SHA for the repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def trigger_preview_deploy(task_id, repo_path=None, slug=None):
    """Trigger a preview deploy after merge completes.

    1. Creates/gets preview env
    2. Records deployment metadata
    3. Logs deploy start/completion

    Returns deployment metadata dict.
    """
    import preview_env_manager

    ts_start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    git_sha = _get_git_sha(repo_path) if repo_path else "unknown"

    # Create or get preview env
    env = preview_env_manager.create_preview_env(task_id)
    if not env or env.get("error"):
        return {"status": "failed", "error": env.get("error", "env creation failed")}

    # Build deployment metadata
    metadata = {
        "task_id": str(task_id),
        "slug": slug or "",
        "env_url": env.get("url", ""),
        "git_sha": git_sha,
        "deploy_started_at": ts_start,
        "deploy_completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "deployed",
        "env_vars": env.get("env_vars", {}),
        "db_ref": env.get("db_ref", ""),
    }

    # Store deployment log
    entries = _load_deploy_log()
    entries.append(metadata)
    _save_deploy_log(entries)

    return metadata


def get_deployment(task_id):
    """Retrieve deployment metadata for a task_id."""
    entries = _load_deploy_log()
    for entry in reversed(entries):
        if entry.get("task_id") == str(task_id):
            return entry
    return None


def list_deployments(status=None):
    """List all deployments, optionally filtered by status."""
    entries = _load_deploy_log()
    if status:
        return [e for e in entries if e.get("status") == status]
    return entries


def post_merge_hook(task_id, repo_path, slug=None):
    """Called by merge_train after a successful merge.

    Synchronously triggers preview deploy and returns metadata.
    """
    print(f"preview_deploy: triggering preview deploy for task {task_id}")
    metadata = trigger_preview_deploy(task_id, repo_path, slug)
    if metadata.get("status") == "deployed":
        print(f"preview_deploy: deployed to {metadata.get('env_url')} (sha: {metadata.get('git_sha')})")
    else:
        print(f"preview_deploy: deploy failed — {metadata.get('error', 'unknown')}")
    return metadata
