#!/usr/bin/env python3
"""
preview_deployer.py — provision and destroy isolated preview environments.

Creates an isolated Supabase branch (via supabase_twin) so preview apps run
against their own copy of the DB.  Returns a PreviewEnv with connection info.

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


class PreviewEnv:
    """Lightweight container for a preview environment's connection info."""

    __slots__ = ("env_id", "branch_id", "db_url", "name", "created_at")

    def __init__(self, env_id, branch_id, db_url, name, created_at=None):
        self.env_id = env_id
        self.branch_id = branch_id
        self.db_url = db_url
        self.name = name
        self.created_at = created_at or time.time()

    def to_dict(self):
        return {
            "env_id": self.env_id,
            "branch_id": self.branch_id,
            "db_url": self.db_url,
            "name": self.name,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            env_id=d.get("env_id", ""),
            branch_id=d.get("branch_id", ""),
            db_url=d.get("db_url", ""),
            name=d.get("name", ""),
            created_at=d.get("created_at"),
        )


def create_preview_env(base_name):
    """Create an isolated preview environment by cloning from supabase_twin.

    Args:
        base_name: human-readable base name (e.g. slug or PR number).

    Returns:
        PreviewEnv with connection info, or None on failure.
    """
    env_id = f"preview-{base_name}-{uuid.uuid4().hex[:8]}"
    try:
        result = supabase_twin.create(pr_number=env_id, branch_name=env_id)
    except Exception as e:
        print(f"preview_deployer: failed to create env {env_id}: {e}")
        return None

    if not result or not result.get("branch_id"):
        print(f"preview_deployer: supabase_twin.create returned no branch_id for {env_id}")
        return None

    return PreviewEnv(
        env_id=env_id,
        branch_id=result["branch_id"],
        db_url=result.get("db_url", ""),
        name=env_id,
    )


def destroy_preview_env(env):
    """Destroy a preview environment, cleaning up the Supabase branch.

    Args:
        env: PreviewEnv instance or dict with branch_id/env_id.

    Returns:
        True if successfully destroyed, False otherwise.
    """
    if env is None:
        return False
    branch_id = env.branch_id if isinstance(env, PreviewEnv) else env.get("branch_id", "")
    env_id = env.env_id if isinstance(env, PreviewEnv) else env.get("env_id", "")
    if not branch_id and not env_id:
        return False
    try:
        ok = supabase_twin.delete(branch_id or env_id)
        return bool(ok)
    except Exception as e:
        print(f"preview_deployer: failed to destroy {env_id}: {e}")
        return False


def list_preview_envs():
    """Return all active preview branches."""
    try:
        return supabase_twin.list_pr_branches()
    except Exception:
        return []
