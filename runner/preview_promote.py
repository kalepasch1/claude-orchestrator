#!/usr/bin/env python3
"""
preview_promote.py — wire preview→smoke→promote flow into the merge path.

Called after a successful merge+push in merge_train._integrate_card.
Creates a preview env, runs smoke tests against the preview URL,
and promotes to prod if smokes pass. If smokes fail, the preview is
destroyed and the task is NOT promoted (but the merge itself is not rolled back;
the merge-train already confirmed tests pass locally).

This is an OPTIONAL post-merge step. If preview env creation fails or smokes
fail, the merge is still valid — the task just doesn't get instant-promoted
to the production Vercel deployment.

Env vars (never hardcoded):
  ORCH_PREVIEW_PROMOTE_ENABLED  — set to "true" to enable (default: false)
  VERCEL_TOKEN                  — required for promotion
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Lazy imports to avoid import errors when these modules aren't needed
_preview_deployer = None
_smoke_test_runner = None
_promotion_pipeline = None


def _load_modules():
    global _preview_deployer, _smoke_test_runner, _promotion_pipeline
    if _preview_deployer is None:
        import preview_deployer
        import smoke_test_runner
        import promotion_pipeline
        _preview_deployer = preview_deployer
        _smoke_test_runner = smoke_test_runner
        _promotion_pipeline = promotion_pipeline


def is_enabled():
    """Check if preview-promote flow is enabled."""
    return os.environ.get("ORCH_PREVIEW_PROMOTE_ENABLED", "false").lower() in ("true", "1", "yes")


def run_preview_promote(slug, task, proj):
    """Run the full preview→smoke→promote pipeline for a merged task.

    Args:
        slug: task slug (used for env naming).
        task: task dict from DB.
        proj: project dict from DB.

    Returns:
        {"promoted": bool, "smoke_passed": bool|None, "error"?: str,
         "preview_url"?: str, "tests"?: list}
    """
    if not is_enabled():
        return {"promoted": False, "smoke_passed": None, "error": "preview-promote disabled"}

    _load_modules()

    vercel_project = proj.get("vercel_project", "")
    if not vercel_project:
        return {"promoted": False, "smoke_passed": None,
                "error": "project has no vercel_project configured"}

    result = {"promoted": False, "smoke_passed": None}
    env = None

    try:
        # Step 1: create preview env
        env = _preview_deployer.create_preview_env(slug)
        if not env:
            result["error"] = "failed to create preview environment"
            return result

        # Step 2: get preview URL from Vercel (wait for deployment)
        preview_url = _wait_for_preview(vercel_project, slug, timeout=120)
        if not preview_url:
            result["error"] = "preview deployment not ready in time"
            return result
        result["preview_url"] = preview_url

        # Step 3: run smoke tests
        smoke_result = _smoke_test_runner.run_smoke_tests(preview_url)
        result["smoke_passed"] = smoke_result.get("passed", False)
        result["tests"] = smoke_result.get("tests", [])

        if not smoke_result.get("passed"):
            result["error"] = "smoke tests failed"
            return result

        # Step 4: promote to prod
        promote_result = _promotion_pipeline.promote_to_prod(preview_url)
        result["promoted"] = promote_result.get("success", False)
        if not result["promoted"]:
            result["error"] = promote_result.get("error", "promotion failed")

        return result

    except Exception as e:
        result["error"] = f"preview-promote exception: {e}"
        return result

    finally:
        # Always clean up the preview env
        if env:
            try:
                _preview_deployer.destroy_preview_env(env)
            except Exception:
                pass  # fail-soft cleanup


def _wait_for_preview(vercel_project, slug, timeout=120):
    """Wait for a Vercel preview deployment to become ready. Returns URL or None."""
    try:
        import preview_canary
    except ImportError:
        return None

    deadline = time.time() + timeout
    poll_interval = 5

    while time.time() < deadline:
        dep = preview_canary.query_preview(vercel_project, f"agent/{slug}")
        if dep:
            state = dep.get("state") or dep.get("readyState") or ""
            if state.upper() in ("READY",):
                url = dep.get("url") or ""
                if url and not url.startswith("http"):
                    url = f"https://{url}"
                return url
            if state.upper() in ("ERROR", "CANCELED", "FAILED"):
                return None
        time.sleep(poll_interval)

    return None


def record_outcome(slug, task, result):
    """Record preview-promote outcome to DB for observability."""
    try:
        db.insert("task_outcomes", {
            "task_id": task.get("id"),
            "slug": slug,
            "category": "preview-promote",
            "outcome": "promoted" if result.get("promoted") else "not-promoted",
            "detail": {
                "smoke_passed": result.get("smoke_passed"),
                "error": result.get("error"),
                "preview_url": result.get("preview_url"),
            },
        })
    except Exception:
        pass  # fail-soft: observability should never block the pipeline
