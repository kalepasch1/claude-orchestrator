#!/usr/bin/env python3
"""
promote_rollback.py — promotion and rollback logic for preview→prod deployments.

Provides:
  promote_to_prod(deployment_metadata) — swap prod to point to preview code/schema
  rollback(previous_deployment)        — revert prod to prior state

Both are exposed as CLI commands via runner.py integration.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
PROD_STATE_FILE = os.path.join(HOME, "prod-state.json")
PROMOTE_LOG = os.path.join(HOME, "promote-log.json")
os.makedirs(HOME, exist_ok=True)


def _load_prod_state():
    try:
        with open(PROD_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"current_deployment": None, "history": []}


def _save_prod_state(state):
    with open(PROD_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _append_promote_log(entry):
    try:
        log = []
        if os.path.isfile(PROMOTE_LOG):
            with open(PROMOTE_LOG) as f:
                log = json.load(f)
        log.append(entry)
        with open(PROMOTE_LOG, "w") as f:
            json.dump(log, f, indent=2)
    except Exception:
        pass


def promote_to_prod(deployment_metadata):
    """Promote a preview deployment to production.

    Reads deployment_metadata, swaps prod to point to preview code/schema.
    Records previous state for rollback.

    Args:
        deployment_metadata: dict with task_id, env_url, git_sha, db_ref, etc.

    Returns:
        dict with status, previous_deployment, promoted_deployment
    """
    if not deployment_metadata:
        return {"status": "failed", "error": "no deployment metadata provided"}

    task_id = deployment_metadata.get("task_id", "unknown")
    git_sha = deployment_metadata.get("git_sha", "unknown")
    db_ref = deployment_metadata.get("db_ref", "")

    # Safety: never promote if preview env is the target
    env_url = deployment_metadata.get("env_url", "")
    if "preview" in env_url and deployment_metadata.get("status") != "deployed":
        return {"status": "failed", "error": "preview env not fully deployed"}

    state = _load_prod_state()
    previous = state.get("current_deployment")

    # Build new prod state
    new_deployment = {
        "task_id": task_id,
        "git_sha": git_sha,
        "db_ref": db_ref,
        "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "preview",
        "env_url": env_url,
    }

    # Save previous to history
    if previous:
        state.setdefault("history", []).append(previous)

    state["current_deployment"] = new_deployment
    _save_prod_state(state)

    log_entry = {
        "action": "promote",
        "task_id": task_id,
        "git_sha": git_sha,
        "timestamp": new_deployment["promoted_at"],
        "previous_sha": previous.get("git_sha") if previous else None,
    }
    _append_promote_log(log_entry)

    print(f"promote_rollback: promoted task {task_id} (sha: {git_sha}) to prod")

    return {
        "status": "promoted",
        "previous_deployment": previous,
        "promoted_deployment": new_deployment,
    }


def rollback(previous_deployment=None):
    """Rollback prod to a previous deployment state.

    If previous_deployment is None, rolls back to the most recent history entry.

    Returns:
        dict with status, rolled_back_to, rolled_back_from
    """
    state = _load_prod_state()
    current = state.get("current_deployment")

    if previous_deployment is None:
        # Use most recent from history
        history = state.get("history", [])
        if not history:
            return {"status": "failed", "error": "no previous deployment to roll back to"}
        previous_deployment = history.pop()
    else:
        # Remove from history if present
        history = state.get("history", [])
        state["history"] = [h for h in history
                            if h.get("git_sha") != previous_deployment.get("git_sha")]

    # Swap
    rolled_back_from = current
    previous_deployment["restored_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["current_deployment"] = previous_deployment
    _save_prod_state(state)

    log_entry = {
        "action": "rollback",
        "rolled_back_from": rolled_back_from.get("git_sha") if rolled_back_from else None,
        "rolled_back_to": previous_deployment.get("git_sha", "unknown"),
        "timestamp": previous_deployment["restored_at"],
    }
    _append_promote_log(log_entry)

    print(f"promote_rollback: rolled back to sha {previous_deployment.get('git_sha', 'unknown')}")

    return {
        "status": "rolled_back",
        "rolled_back_to": previous_deployment,
        "rolled_back_from": rolled_back_from,
    }


def get_prod_state():
    """Return current production deployment state."""
    return _load_prod_state()


# CLI interface
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Promote/rollback preview deployments")
    sub = parser.add_subparsers(dest="cmd")

    p_promote = sub.add_parser("promote", help="Promote a deployment to prod")
    p_promote.add_argument("--task-id", required=True)
    p_promote.add_argument("--git-sha", default="unknown")
    p_promote.add_argument("--db-ref", default="")

    p_rollback = sub.add_parser("rollback", help="Rollback to previous deployment")
    p_rollback.add_argument("--git-sha", help="Specific SHA to roll back to")

    p_status = sub.add_parser("status", help="Show current prod state")

    args = parser.parse_args()
    if args.cmd == "promote":
        result = promote_to_prod({
            "task_id": args.task_id,
            "git_sha": args.git_sha,
            "db_ref": args.db_ref,
            "status": "deployed",
        })
        print(json.dumps(result, indent=2))
    elif args.cmd == "rollback":
        prev = {"git_sha": args.git_sha} if args.git_sha else None
        result = rollback(prev)
        print(json.dumps(result, indent=2))
    elif args.cmd == "status":
        print(json.dumps(get_prod_state(), indent=2))
    else:
        parser.print_help()
