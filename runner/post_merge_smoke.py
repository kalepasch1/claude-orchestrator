#!/usr/bin/env python3
"""
post_merge_smoke.py — automated smoke tests triggered post-merge.

After a task branch merges into the target branch, this module runs the
smoke test suite (from tests/smoke_tests.py) against the resulting state
to ensure deployments remain stable.  Integrates with ci_dispatch to
optionally offload smoke runs to CI when available.

Fail-soft: errors return a degraded result, never raise.
"""
import os
import sys
import time
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("post_merge_smoke")

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
RESULTS_DIR = os.path.join(HOME, "post-merge-smoke")
SMOKE_TIMEOUT_S = int(os.environ.get("ORCH_SMOKE_TIMEOUT_S", "120"))
ENABLED = os.environ.get("ORCH_POST_MERGE_SMOKE", "true").lower() == "true"

_stats = {"runs": 0, "passed": 0, "failed": 0, "skipped": 0}


def stats():
    """Return a copy of runtime stats."""
    return dict(_stats)


def run_post_merge_smoke(task, repo_path="", base_url=""):
    """Run smoke tests after a merge completes.

    Args:
        task: dict with at least 'slug', 'project_id'
        repo_path: path to the repo where merge happened
        base_url: optional preview URL to smoke-test against

    Returns:
        dict with 'passed': bool, 'results': list, 'duration_s': float
    """
    if not ENABLED:
        _stats["skipped"] += 1
        return {"passed": True, "results": [], "duration_s": 0, "skipped": True}

    slug = (task or {}).get("slug", "unknown")
    _stats["runs"] += 1
    start = time.time()

    results = []
    try:
        from tests.smoke_tests import health_check, db_connectivity_check, workflow_smoke_test

        env_vars = {
            "PREVIEW_TASK_ID": slug,
            "PREVIEW_DB_REF": os.environ.get("SUPABASE_PROJECT_REF", ""),
        }

        if base_url:
            results.append(health_check(base_url).to_dict())
        results.append(db_connectivity_check(env_vars).to_dict())
        if base_url:
            results.append(workflow_smoke_test(base_url, env_vars).to_dict())
    except Exception as e:
        log.warning("post_merge_smoke error for %s: %s", slug, e)
        results.append({"name": "smoke_import", "passed": False, "detail": str(e)})

    duration = time.time() - start
    all_passed = all(r.get("passed", False) for r in results) if results else True

    if all_passed:
        _stats["passed"] += 1
    else:
        _stats["failed"] += 1

    outcome = {
        "passed": all_passed,
        "results": results,
        "duration_s": round(duration, 2),
        "slug": slug,
        "ts": time.time(),
    }

    _persist_result(outcome)
    return outcome


def _persist_result(outcome):
    """Save smoke result to disk for audit trail."""
    try:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        slug = outcome.get("slug", "unknown")
        path = os.path.join(RESULTS_DIR, f"{slug}-{int(time.time())}.json")
        with open(path, "w") as f:
            json.dump(outcome, f, indent=2)
    except Exception:
        pass


def should_block_deploy(outcome):
    """Return True if a failed smoke test should block further deployment."""
    if not outcome:
        return False
    if outcome.get("skipped"):
        return False
    return not outcome.get("passed", True)


def run_via_ci(task, repo=""):
    """Dispatch smoke tests to CI instead of running locally.

    Falls back to local execution if CI dispatch is unavailable.
    """
    try:
        import ci_dispatch
        ci_task = dict(task or {})
        ci_task["kind"] = "test"
        ci_task["prompt"] = f"Run post-merge smoke tests for {ci_task.get('slug', 'unknown')}"
        payload = ci_dispatch.dispatch(ci_task, repo=repo)
        if payload:
            return {"dispatched": True, "payload": payload}
    except Exception as e:
        log.debug("CI dispatch unavailable, falling back to local: %s", e)

    return run_post_merge_smoke(task)


def run():
    """Periodic entry point — check for recently merged tasks and smoke-test them."""
    if not ENABLED:
        return
    try:
        import db
        recent = db.select("tasks", {
            "select": "id,slug,project_id,base_branch",
            "state": "eq.MERGED",
            "order": "updated_at.desc",
            "limit": "5",
        }) or []

        for task in recent:
            marker_key = f"smoke_done_{task.get('slug')}"
            existing = db.select("fleet_config", {"key": f"eq.{marker_key}", "limit": "1"})
            if existing:
                continue
            outcome = run_post_merge_smoke(task)
            try:
                db.upsert("fleet_config", {"key": marker_key, "value": json.dumps(outcome)})
            except Exception:
                pass
    except Exception as e:
        log.warning("post_merge_smoke periodic run error: %s", e)
