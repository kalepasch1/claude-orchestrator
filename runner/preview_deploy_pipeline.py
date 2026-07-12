#!/usr/bin/env python3
"""
preview_deploy_pipeline.py — end-to-end preview→smoke→promote pipeline.

Wires preview_provisioner, smoke_test_runner, and promote_decision into
a single pipeline invoked after merge to master. On merge:
  1. Provision a preview environment (Supabase twin clone).
  2. Run smoke tests against the preview.
  3. If pass: promote to prod and clean up preview.
  4. If fail: destroy preview and fail task.

Supports a --preview-only CLI flag to stop after smoke (for testing).

Env vars (never hardcoded):
  ORCH_PREVIEW_DEPLOY_ENABLED  — "true" to enable (default: false)
  SUPABASE_ACCESS_TOKEN        — required for branch management
  SUPABASE_PROJECT_REF         — required for branch management
"""
import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Lazy imports to avoid import errors when modules aren't needed
_provisioner = None
_smoke_runner = None
_decision = None


def _load_modules():
    global _provisioner, _smoke_runner, _decision
    if _provisioner is None:
        import preview_provisioner
        import smoke_test_runner
        import promote_decision
        _provisioner = preview_provisioner
        _smoke_runner = smoke_test_runner
        _decision = promote_decision


def is_enabled():
    """Check if preview deploy pipeline is enabled."""
    return os.environ.get("ORCH_PREVIEW_DEPLOY_ENABLED", "false").lower() in ("true", "1", "yes")


def preview_deploy_pipeline(
    slug: str,
    commit_sha: str,
    branch: str,
    task: dict = None,
    proj: dict = None,
    preview_only: bool = False,
) -> dict:
    """Run the full preview→smoke→promote pipeline.

    Args:
        slug: task slug (used for naming).
        commit_sha: the merged commit SHA.
        branch: the git branch name.
        task: task dict from DB (optional).
        proj: project dict from DB (optional).
        preview_only: if True, stop after smoke tests (for testing).

    Returns:
        dict with keys: preview_created, smoke_passed, promoted, error.
    """
    result = {
        "preview_created": False,
        "smoke_passed": None,
        "promoted": False,
        "preview_only": preview_only,
        "error": "",
    }

    if not is_enabled():
        result["error"] = "preview deploy pipeline disabled"
        return result

    _load_modules()

    # Step 1: Provision preview environment
    try:
        preview_env = _provisioner.provision_preview(commit_sha, branch)
        result["preview_created"] = True
    except Exception as e:
        result["error"] = f"preview provisioning failed: {e}"
        return result

    # Step 2: Run smoke tests against preview
    preview_url = preview_env.db_url  # use db_url as base for smoke tests
    try:
        smoke_results = _smoke_runner.run_smoke_suite(preview_url)
        all_passed = all(r.get("status") == "pass" for r in smoke_results)
        result["smoke_passed"] = all_passed
        result["smoke_tests"] = smoke_results
    except Exception as e:
        result["smoke_passed"] = False
        result["error"] = f"smoke tests errored: {e}"
        # Destroy preview on smoke error
        try:
            _provisioner.destroy_preview(preview_env)
        except Exception:
            pass
        return result

    # Step 3: If preview_only, stop here (for testing)
    if preview_only:
        result["preview_env"] = preview_env.to_dict()
        return result

    # Step 4: Promote or rollback based on smoke results
    smoke_result = _decision.SmokeResult(
        passed=all_passed,
        tests=smoke_results,
        error="" if all_passed else "one or more smoke tests failed",
    )

    try:
        deploy_result = _decision.promote_or_rollback(
            preview_env=preview_env,
            smoke_result=smoke_result,
            commit_sha=commit_sha,
        )
        result["promoted"] = deploy_result.success
        result["action"] = deploy_result.action
        if deploy_result.deployment_id:
            result["deployment_id"] = deploy_result.deployment_id
        if deploy_result.rollback_id:
            result["rollback_id"] = deploy_result.rollback_id
        if deploy_result.error:
            result["error"] = deploy_result.error
    except Exception as e:
        result["error"] = f"promote/rollback failed: {e}"
        # Best-effort cleanup
        try:
            _provisioner.destroy_preview(preview_env)
        except Exception:
            pass

    return result


def hook_post_merge(slug, task, proj, commit_sha, branch):
    """Post-merge hook for merge_train integration.

    Called after a successful merge+push. Runs the preview deploy pipeline
    as an optional post-merge step. Failures here do NOT affect the merge.

    Args:
        slug: task slug.
        task: task dict.
        proj: project dict.
        commit_sha: the merged commit SHA.
        branch: the git branch.

    Returns:
        dict with pipeline results, or None if disabled.
    """
    if not is_enabled():
        return None
    try:
        return preview_deploy_pipeline(
            slug=slug,
            commit_sha=commit_sha,
            branch=branch,
            task=task,
            proj=proj,
        )
    except Exception as e:
        return {"error": f"preview deploy pipeline failed: {e}"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Preview deploy pipeline")
    parser.add_argument("--commit", required=True, help="Commit SHA")
    parser.add_argument("--branch", required=True, help="Branch name")
    parser.add_argument("--slug", default="manual", help="Task slug")
    parser.add_argument("--preview-only", action="store_true",
                        help="Stop after smoke tests (don't promote)")
    args = parser.parse_args()

    os.environ.setdefault("ORCH_PREVIEW_DEPLOY_ENABLED", "true")
    result = preview_deploy_pipeline(
        slug=args.slug,
        commit_sha=args.commit,
        branch=args.branch,
        preview_only=args.preview_only,
    )
    print(json.dumps(result, indent=2, default=str))
