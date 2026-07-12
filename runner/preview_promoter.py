#!/usr/bin/env python3
"""
preview_promoter.py — promote a passing preview environment to production.

Validates smoke test results, snapshots prod state for rollback,
swaps traffic to the preview, and provides rollback capability.

Env vars (never hardcoded):
  SUPABASE_ACCESS_TOKEN   — required for branch management
  SUPABASE_PROJECT_REF    — required for branch management
"""
import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import supabase_twin
from preview_deployer import PreviewEnv


class PromoteResult:
    """Result of a promotion attempt."""
    __slots__ = ("success", "snapshot_id", "error", "promoted_at")

    def __init__(self, success, snapshot_id="", error="", promoted_at=None):
        self.success = success
        self.snapshot_id = snapshot_id
        self.error = error
        self.promoted_at = promoted_at or time.time()

    def to_dict(self):
        return {
            "success": self.success,
            "snapshot_id": self.snapshot_id,
            "error": self.error,
            "promoted_at": self.promoted_at,
        }


class RollbackError(Exception):
    """Raised when rollback fails."""
    pass


def _validate_smoke_results(smoke_results: list) -> bool:
    """Validate that all smoke tests passed.

    Args:
        smoke_results: list of dicts with 'status' key.

    Returns:
        True if all tests passed.
    """
    if not smoke_results:
        return False
    return all(r.get("status") == "pass" for r in smoke_results)


def _snapshot_prod_state(prod_env) -> str:
    """Snapshot production state for rollback.

    Creates a Supabase branch from current prod as a snapshot.

    Args:
        prod_env: prod environment identifier (project ref or name).

    Returns:
        snapshot_id string.
    """
    snapshot_id = f"snapshot-{int(time.time())}"
    try:
        result = supabase_twin.create(
            pr_number=snapshot_id,
            branch_name=f"prod-snapshot-{snapshot_id}",
        )
        if result and result.get("branch_id"):
            snapshot_id = result["branch_id"]
    except Exception:
        pass  # snapshot is best-effort; promotion can proceed
    try:
        db.execute(
            "INSERT INTO promotion_snapshots (snapshot_id, prod_env, created_at) "
            "VALUES (%s, %s, now()) ON CONFLICT DO NOTHING",
            (snapshot_id, str(prod_env)),
        )
    except Exception:
        pass
    return snapshot_id


def promote_preview_to_prod(preview_env: PreviewEnv, prod_env) -> PromoteResult:
    """Promote a passing preview environment to production.

    Steps:
      1. Validate smoke test results (via DB lookup).
      2. Snapshot prod state for rollback.
      3. Swap traffic to preview (mark preview as active prod).
      4. Record promotion in DB.

    Args:
        preview_env: the PreviewEnv that passed smokes.
        prod_env: the production environment identifier.

    Returns:
        PromoteResult with success/failure and snapshot_id.
    """
    # Step 1: validate smoke results for this preview
    smoke_results = []
    try:
        rows = db.execute(
            "SELECT results FROM smoke_test_runs WHERE env_id = %s ORDER BY created_at DESC LIMIT 1",
            (preview_env.env_id,),
        )
        if rows:
            smoke_results = json.loads(rows[0].get("results", "[]")) if isinstance(rows[0].get("results"), str) else rows[0].get("results", [])
    except Exception:
        pass

    if not _validate_smoke_results(smoke_results):
        return PromoteResult(success=False, error="smoke tests did not all pass")

    # Step 2: snapshot prod
    snapshot_id = _snapshot_prod_state(prod_env)

    # Step 3: swap — mark preview branch as the active prod branch
    try:
        db.execute(
            "UPDATE deployment_state SET active_branch = %s, active_env_id = %s, "
            "promoted_at = now() WHERE env_name = %s",
            (preview_env.branch_id, preview_env.env_id, str(prod_env)),
        )
    except Exception as e:
        return PromoteResult(success=False, snapshot_id=snapshot_id,
                             error=f"traffic swap failed: {e}")

    # Step 4: record
    try:
        db.execute(
            "INSERT INTO promotions (env_id, snapshot_id, prod_env, promoted_at) "
            "VALUES (%s, %s, %s, now())",
            (preview_env.env_id, snapshot_id, str(prod_env)),
        )
    except Exception:
        pass

    return PromoteResult(success=True, snapshot_id=snapshot_id)


def rollback_promotion(snapshot_id: str, prod_env=None):
    """Rollback a promotion by restoring from snapshot.

    Args:
        snapshot_id: the snapshot branch_id to restore from.
        prod_env: optional prod env identifier.

    Raises:
        RollbackError: if rollback fails.
    """
    # Restore prod to the snapshot branch
    try:
        db.execute(
            "UPDATE deployment_state SET active_branch = %s, "
            "rolled_back_at = now() WHERE env_name = %s",
            (snapshot_id, str(prod_env or "prod")),
        )
    except Exception as e:
        raise RollbackError(f"rollback DB update failed: {e}") from e

    # Clean up the snapshot branch after restore (best-effort)
    try:
        supabase_twin.delete(snapshot_id)
    except Exception:
        pass  # snapshot cleanup is best-effort
