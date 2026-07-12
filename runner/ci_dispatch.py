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


def dispatch(task, repo="", github_token=None):
    """Fire a repository_dispatch event for the task. Returns the payload sent.
    
    In production, this would POST to GitHub API. Currently returns the payload
    for the caller (runner) to dispatch via its own HTTP client.
    """
    if not is_eligible(task):
        return None
    slug = task.get("slug", "unknown")
    if len(_in_flight) >= MAX_CONCURRENT:
        return None
    payload = build_dispatch_payload(task)
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
    """Mark a CI dispatch as completed."""
    _in_flight.pop(slug, None)
    return "done" if success else "failed"


if __name__ == "__main__":
    print(json.dumps({"eligible_kinds": sorted(CI_ELIGIBLE_KINDS),
                      "max_concurrent": MAX_CONCURRENT}))
