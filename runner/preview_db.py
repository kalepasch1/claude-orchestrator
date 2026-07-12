#!/usr/bin/env python3
"""
preview_db.py — provision isolated Supabase preview databases.

Thin wrapper around supabase_twin that provides a simplified interface
for creating, connecting to, and tearing down preview databases keyed
by commit hash.  Guarantees isolation: each preview gets its own branch
DB with 'preview' in the name, separate schema/data from prod.

Env vars (never hardcoded):
  SUPABASE_ACCESS_TOKEN   — required; Supabase Management API token
  SUPABASE_PROJECT_REF    — required; target project reference
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import supabase_twin


def create_preview_db(commit_hash):
    """Create an isolated preview database for a given commit hash.

    Args:
        commit_hash: Git commit SHA (or short hash) to associate with the preview.

    Returns:
        dict with keys: branch_id, db_url, name, commit_hash, created_at.
        None on failure.
    """
    if not commit_hash:
        return None
    short = commit_hash[:12]
    branch_name = f"preview-{short}"
    try:
        result = supabase_twin.create(pr_number=branch_name, branch_name=branch_name)
    except Exception as e:
        print(f"preview_db: failed to create DB for {short}: {e}")
        return None
    if not result or not result.get("branch_id"):
        return None
    return {
        "branch_id": result["branch_id"],
        "db_url": result.get("db_url", ""),
        "name": branch_name,
        "commit_hash": commit_hash,
        "created_at": time.time(),
    }


def get_connection_config(preview):
    """Return connection config dict for a preview database.

    Args:
        preview: dict returned by create_preview_db().

    Returns:
        dict with host, db_url, name; or None if preview is invalid.
    """
    if not preview:
        return None
    db_url = preview.get("db_url", "")
    name = preview.get("name", "")
    # Extract host from db_url (postgresql://user:pass@host:port/dbname)
    host = ""
    if db_url and "@" in db_url:
        try:
            host = db_url.split("@")[1].split(":")[0]
        except (IndexError, AttributeError):
            host = ""
    return {
        "host": host,
        "db_url": db_url,
        "name": name,
        "branch_id": preview.get("branch_id", ""),
    }


def teardown_preview_db(preview):
    """Tear down a preview database, deleting its Supabase branch.

    Idempotent: safe to call multiple times.

    Args:
        preview: dict returned by create_preview_db(), or branch_id string.

    Returns:
        True if successfully torn down, False otherwise.
    """
    if preview is None:
        return False
    branch_id = preview.get("branch_id", "") if isinstance(preview, dict) else str(preview)
    if not branch_id:
        return False
    try:
        return bool(supabase_twin.delete(branch_id))
    except Exception as e:
        print(f"preview_db: teardown failed for {branch_id}: {e}")
        return False


def is_isolated(preview):
    """Check that a preview DB has 'preview' in its name (isolation indicator)."""
    if not preview:
        return False
    name = preview.get("name", "")
    return "preview" in name.lower()
