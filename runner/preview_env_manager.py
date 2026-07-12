#!/usr/bin/env python3
"""
preview_env_manager.py — isolated PREVIEW environment management using supabase_twin.

Provides create/teardown/get for preview environments that isolate DB and env vars
per task_id, enabling safe canary deployments before promotion to prod.

Uses the existing supabase_twin pattern for Supabase branch isolation.

Env vars (never hardcoded):
  SUPABASE_ACCESS_TOKEN  — required; Supabase management API token
  SUPABASE_PROJECT_REF   — required; project reference
  PREVIEW_BASE_URL       — optional; base URL for preview envs (default: http://localhost:3001)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
PREVIEW_REGISTRY = os.path.join(HOME, "preview-envs.json")
PREVIEW_BASE_URL = os.environ.get("PREVIEW_BASE_URL", "http://localhost:3001")
os.makedirs(HOME, exist_ok=True)


def _load_registry():
    try:
        with open(PREVIEW_REGISTRY) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_registry(reg):
    with open(PREVIEW_REGISTRY, "w") as f:
        json.dump(reg, f, indent=2)


def create_preview_env(task_id):
    """Create an isolated preview environment for a task.

    Returns dict with url, env_vars, db_ref keys.
    Uses supabase_twin to create an isolated DB branch when available,
    otherwise creates a logical env entry for local testing.
    """
    if not task_id:
        return {"error": "task_id required"}

    reg = _load_registry()
    tid = str(task_id)

    # Already exists — return it
    if tid in reg and reg[tid].get("status") == "active":
        return reg[tid]

    db_ref = None
    db_url = None

    # Try supabase_twin for real DB isolation
    try:
        import supabase_twin
        branch = supabase_twin.create(pr_number=tid, branch_name=f"preview-{tid}")
        db_ref = branch.get("branch_id", f"preview-{tid}")
        db_url = branch.get("db_url", "")
    except Exception:
        # Fall back to logical isolation (schema prefix)
        db_ref = f"preview_{tid}"
        db_url = ""

    env_vars = {
        "PREVIEW_TASK_ID": tid,
        "PREVIEW_DB_REF": db_ref,
        "PREVIEW_DB_URL": db_url,
        "PREVIEW_ISOLATED": "true",
        "NODE_ENV": "preview",
    }

    entry = {
        "task_id": tid,
        "url": f"{PREVIEW_BASE_URL}/preview/{tid}",
        "env_vars": env_vars,
        "db_ref": db_ref,
        "status": "active",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    reg[tid] = entry
    _save_registry(reg)
    return entry


def teardown_preview_env(task_id):
    """Tear down a preview environment, cleaning up DB branch and registry."""
    if not task_id:
        return False

    tid = str(task_id)
    reg = _load_registry()

    if tid not in reg:
        return True  # already gone

    entry = reg[tid]

    # Try supabase_twin cleanup
    try:
        import supabase_twin
        supabase_twin.delete(tid)
    except Exception:
        pass  # best-effort

    entry["status"] = "torn_down"
    entry["torn_down_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    reg[tid] = entry
    _save_registry(reg)
    return True


def get_preview_env(task_id):
    """Return preview env metadata for a task, or None if not found/active."""
    if not task_id:
        return None

    tid = str(task_id)
    reg = _load_registry()
    entry = reg.get(tid)

    if entry and entry.get("status") == "active":
        return entry
    return None


def list_active_envs():
    """Return all active preview environments."""
    reg = _load_registry()
    return [v for v in reg.values() if v.get("status") == "active"]
