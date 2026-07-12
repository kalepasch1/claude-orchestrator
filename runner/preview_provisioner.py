#!/usr/bin/env python3
"""
preview_provisioner.py — provision isolated preview Supabase environments.

Uses supabase_twin to clone the production DB into an isolated branch,
returning a PreviewEnv with connection info suitable for injection into
runner agents.

Env vars (never hardcoded):
  SUPABASE_ACCESS_TOKEN   — required for branch management
  SUPABASE_PROJECT_REF    — required for branch management
"""
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import supabase_twin
from preview_deployer import PreviewEnv


class ProvisionError(Exception):
    """Raised when preview provisioning fails."""
    pass


def provision_preview(commit_sha: str, branch: str) -> PreviewEnv:
    """Provision an isolated preview Supabase environment via twin cloning.

    Creates a separate DB clone so preview apps run against their own data.
    The returned env vars are injectable into runner agents.

    Args:
        commit_sha: the commit SHA being previewed.
        branch: the git branch name (used for naming).

    Returns:
        PreviewEnv with env_id, db_url, and connection info.

    Raises:
        ProvisionError: if cloning or branch creation fails.
    """
    base_name = f"preview-{branch[:30]}-{commit_sha[:8]}"
    try:
        twin_result = supabase_twin.create(
            pr_number=commit_sha[:8],
            branch_name=base_name,
        )
    except Exception as e:
        raise ProvisionError(f"supabase_twin.create failed: {e}") from e

    if not twin_result or not twin_result.get("branch_id"):
        raise ProvisionError("supabase_twin.create returned empty result")

    env = PreviewEnv(
        env_id=str(uuid.uuid4()),
        branch_id=twin_result["branch_id"],
        db_url=twin_result.get("db_url", ""),
        name=base_name,
        created_at=time.time(),
    )

    # Record in DB for tracking/cleanup
    try:
        db.execute(
            "INSERT INTO preview_envs (env_id, branch_id, commit_sha, branch, name, created_at) "
            "VALUES (%s, %s, %s, %s, %s, now()) ON CONFLICT DO NOTHING",
            (env.env_id, env.branch_id, commit_sha, branch, base_name),
        )
    except Exception:
        pass  # fail-soft: env is usable even if tracking insert fails

    return env


def destroy_preview(env: PreviewEnv) -> bool:
    """Destroy a preview environment and its Supabase branch.

    Args:
        env: the PreviewEnv to tear down.

    Returns:
        True if destruction succeeded, False otherwise.
    """
    try:
        ok = supabase_twin.delete(env.branch_id)
    except Exception:
        ok = False
    try:
        db.execute(
            "DELETE FROM preview_envs WHERE env_id = %s", (env.env_id,)
        )
    except Exception:
        pass
    return bool(ok)


def get_env_vars(env: PreviewEnv) -> dict:
    """Return env vars suitable for injection into a runner agent.

    Args:
        env: the provisioned PreviewEnv.

    Returns:
        dict of env var name → value.
    """
    return {
        "PREVIEW_ENV_ID": env.env_id,
        "PREVIEW_BRANCH_ID": env.branch_id,
        "PREVIEW_DB_URL": env.db_url,
        "PREVIEW_ENV_NAME": env.name,
    }
