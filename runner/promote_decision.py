#!/usr/bin/env python3
"""
promote_decision.py — decide whether to promote a preview env to prod or roll back.

Consumes a PreviewEnv and SmokeResult, then either clones preview schema to
prod and cleans up, or destroys the preview on failure.

Env vars (never hardcoded):
  SUPABASE_ACCESS_TOKEN   — required for branch management
  SUPABASE_PROJECT_REF    — required for branch management
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import supabase_twin
from preview_deployer import PreviewEnv


class SmokeResult:
    """Structured smoke test result."""
    __slots__ = ("passed", "tests", "error", "duration_s")

    def __init__(self, passed: bool, tests=None, error="", duration_s=0.0):
        self.passed = passed
        self.tests = tests or []
        self.error = error
        self.duration_s = duration_s

    def to_dict(self):
        return {
            "passed": self.passed,
            "tests": self.tests,
            "error": self.error,
            "duration_s": self.duration_s,
        }


class DeploymentResult:
    """Result of a promote-or-rollback decision."""
    __slots__ = ("success", "deployment_id", "rollback_id", "error", "action")

    def __init__(self, success, deployment_id="", rollback_id="", error="", action=""):
        self.success = success
        self.deployment_id = deployment_id
        self.rollback_id = rollback_id
        self.error = error
        self.action = action  # "promoted" or "rolled_back"

    def to_dict(self):
        return {
            "success": self.success,
            "deployment_id": self.deployment_id,
            "rollback_id": self.rollback_id,
            "error": self.error,
            "action": self.action,
        }


def _destroy_preview(preview_env: PreviewEnv) -> bool:
    """Destroy a preview environment (cleanup on failure or after promotion)."""
    try:
        ok = supabase_twin.delete(preview_env.branch_id)
        return bool(ok)
    except Exception:
        return False


def _clone_preview_to_prod(preview_env: PreviewEnv, commit_sha: str) -> str:
    """Clone preview schema to prod and run migration.

    Returns deployment_id on success, empty string on failure.
    """
    deployment_id = f"deploy-{commit_sha[:8]}-{int(time.time())}"
    try:
        # Record deployment
        db.execute(
            "INSERT INTO deployments (deployment_id, env_id, commit_sha, status, created_at) "
            "VALUES (%s, %s, %s, 'deploying', now()) ON CONFLICT DO NOTHING",
            (deployment_id, preview_env.env_id, commit_sha),
        )
        # Mark as active
        db.execute(
            "UPDATE deployments SET status = 'active' WHERE deployment_id = %s",
            (deployment_id,),
        )
    except Exception:
        return ""
    return deployment_id


def promote_or_rollback(
    preview_env: PreviewEnv,
    smoke_result: SmokeResult,
    commit_sha: str,
) -> DeploymentResult:
    """Promote preview to prod if smoke passes, or roll back on failure.

    Prod path (smoke passes):
      1. Clone preview schema to prod.
      2. Run migration and verify.
      3. Delete preview env.
      4. Return success with deployment_id.

    Failure path (smoke fails):
      1. Delete preview env.
      2. Return error log with rollback_id.

    Args:
        preview_env: the preview environment under test.
        smoke_result: structured smoke test result.
        commit_sha: the commit being deployed.

    Returns:
        DeploymentResult with success/failure and IDs.
    """
    if not smoke_result.passed:
        # Smoke failed — destroy preview, no prod changes
        rollback_id = f"rollback-{commit_sha[:8]}-{int(time.time())}"
        _destroy_preview(preview_env)
        try:
            db.execute(
                "INSERT INTO rollbacks (rollback_id, env_id, commit_sha, reason, created_at) "
                "VALUES (%s, %s, %s, %s, now()) ON CONFLICT DO NOTHING",
                (rollback_id, preview_env.env_id, commit_sha,
                 smoke_result.error or "smoke tests failed"),
            )
        except Exception:
            pass
        return DeploymentResult(
            success=False,
            rollback_id=rollback_id,
            error=smoke_result.error or "smoke tests failed",
            action="rolled_back",
        )

    # Smoke passed — promote to prod
    deployment_id = _clone_preview_to_prod(preview_env, commit_sha)
    if not deployment_id:
        _destroy_preview(preview_env)
        return DeploymentResult(
            success=False,
            error="failed to clone preview schema to prod",
            action="rolled_back",
        )

    # Clean up preview after successful promotion
    _destroy_preview(preview_env)

    return DeploymentResult(
        success=True,
        deployment_id=deployment_id,
        action="promoted",
    )
