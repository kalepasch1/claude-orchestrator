#!/usr/bin/env python3
"""
ci_dispatch.py — claim tasks flagged lane=ci and dispatch them to GitHub Actions.

Only safe, non-sensitive task kinds (docs, chore, lint, mechanical, test) with no
unresolved deps are eligible. Fires a repository_dispatch event with slug+prompt payload,
then polls the resulting workflow run status back into the task row.

Guardrails:
  - Per-repo concurrent CI-agent cap (env ORCH_CI_MAX_CONCURRENT, default 2)
  - Never dispatches crown-jewel/sensitive tasks (reuses _task_sensitivity from agentic_coders)
  - Secrets come from GitHub repo secrets only, never the dispatch payload
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Assuming 'db' module is available in the same path or sys.path
import db

CI_ELIGIBLE_KINDS = {"docs", "chore", "lint", "mechanical", "test"}
MAX_CONCURRENT = int(os.environ.get("ORCH_CI_MAX_CONCURRENT", "2"))

# Track in-flight CI dispatches (process-local; coordinator resets on restart)
_in_flight = {}


def _task_sensitivity(task):
    """Reuse agentic_coders sensitivity check, fall back to 'standard'."""
    try:
        from agentic_coders import _task_sensitivity as _ts
        return _ts(task)
    except Exception:
        return "standard"


def is_eligible(task):
    """Return True if the task is safe for CI lane execution."""
    kind = (task.get("kind") or "").lower()
    if kind not in CI_ELIGIBLE_KINDS:
        return False
    # No unresolved deps
    deps = task.get("deps") or []
    if deps and any(d for d in deps):
        return False
    # Sensitivity gate
    sensitivity = _task_sensitivity(task)
    if sensitivity not in ("standard", "public", "routine"):
        return False
    return True


def build_dispatch_payload(task):
    """Build the repository_dispatch client_payload. Never includes secrets."""
    return {
        "event_type": "orch-agent-task",
        "client_payload": {
            "slug": task.get("slug", "unknown"),
            "prompt": (task.get("prompt") or "")[:2000],  # truncate to avoid huge payloads
            "kind": task.get("kind", ""),
            "task_id": str(task.get("id", "")),
        }
    }


# --- restored from 0c0ad897: module state + eligibility/payload helpers that the
# master fragment still called. _github_dispatch()/dispatch() below are master's. ---


def _github_dispatch(repo, payload, github_token):
    """POST repository_dispatch to GitHub API. Returns True on success."""
    if not github_token or not repo:
        return False
    import urllib.request
    import urllib.error
    url = f"https://api.github.com/repos/{repo}/dispatches"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"[ci_dispatch] GitHub API error {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"[ci_dispatch] dispatch failed: {e}")
        return False


def dispatch(task, repo="", github_token=None):
    """Fire a repository_dispatch event for the task. Returns the payload sent.

    In production, this would POST to GitHub API. Currently returns the payload
    for the caller (runner) to dispatch via its own HTTP client.
    """
    if not is_eligible(task):
        return None
    slug = task.get("slug", "unknown")

    # THE CAP WAS NOT A CAP (fixed 2026-08-25). This block used to read:
    #
    #     if len(_in_flight) >= MAX_CONCURRENT:
    #         if slug == 'canary-self-deploy-orchestrator-split-the-build-ta-slice-2':
    #             return None
    #
    # so the only task the limit ever stopped was one hardcoded slug. Every other
    # task sailed past a full _in_flight, and this module's own header advertises
    # "Per-repo concurrent CI-agent cap (env ORCH_CI_MAX_CONCURRENT, default 2)".
    # An unbounded fan-out of repository_dispatch events is how a CI account gets
    # rate-limited, and the operator knob that was supposed to prevent it read as
    # having no effect.
    #
    # Re-dispatching a slug that is already in flight is its own bug and is
    # checked first: it duplicates a CI run rather than adding a new one, so it
    # is wrong even when there is capacity to spare. That was what the hardcoded
    # slug was really working around.
    if slug in _in_flight:
        print(f"ci_dispatch: {slug} is already in flight — not dispatching again")
        return None
    if len(_in_flight) >= MAX_CONCURRENT:
        print(f"ci_dispatch: {len(_in_flight)} CI agents in flight "
              f"(cap {MAX_CONCURRENT}) — deferring {slug}")
        return None

    payload = build_dispatch_payload(task)
    # Fire the actual GitHub dispatch if credentials are available
    if github_token and repo:
        if not _github_dispatch(repo, payload, github_token):
            return None
    _in_flight[slug] = {"dispatched_at": time.time(), "task_id": str(task.get("id", ""))}
    return payload


def poll_status(slug):
    """Check if a dispatched CI task is still in flight. Returns status string."""
    entry = _in_flight.get(slug)
    if not entry:
        return "unknown"
    age = time.time() - entry.get("dispatched_at", 0)
    if age > 1800:  # 30 min timeout
        _in_flight.pop(slug, None)
        return "timeout"
    return "in_progress"


def complete(slug, success=True):
    """Mark a CI dispatch as completed and update the task state in the database."""
    entry = _in_flight.pop(slug, None)
    if entry:
        task_id = entry["task_id"]
        new_state = "done" if success else "testfail"
        # An empty task_id is not a task id. dispatch() records
        # str(task.get("id", "")), so any task dispatched without an "id" -- which
        # includes every unit-test fixture -- landed here with "", and this line
        # issued PATCH /rest/v1/tasks?id=eq. against the live control plane with
        # {"state": "done"} and no meaningful filter. Postgres rejects '' for a
        # uuid column, which is the only reason that was survivable; on a text
        # id it is a whole-table update. Nothing to identify means nothing to
        # write, so the in-flight slot is still released and the write is not
        # attempted.
        if not task_id:
            print(f"ci_dispatch: {slug} completed with no task id — "
                  f"released the slot, no state write")
            return new_state
        # Assuming 'tasks' is the table name for QueuedTask
        db.update("tasks", {"id": task_id}, {"state": new_state})
        return new_state
    return "unknown"


if __name__ == "__main__":
    print(json.dumps({"eligible_kinds": sorted(CI_ELIGIBLE_KINDS),
                      "max_concurrent": MAX_CONCURRENT}))
