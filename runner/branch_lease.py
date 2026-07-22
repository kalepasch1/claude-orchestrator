"""Cross-machine, cross-executor one-writer leases for mutable task branches."""

from __future__ import annotations


import os
import socket
import subprocess
import threading
import uuid

import db


DEFAULT_TTL = int(os.environ.get("ORCH_BRANCH_LEASE_TTL_SECONDS", "3600") or 3600)
_active: dict[tuple[str, str], dict] = {}
_lock = threading.RLock()


def _sha(repo: str, ref: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", ref], cwd=repo,
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def acquire(task: dict, repo: str, branch: str, base: str, *, owner: str | None = None,
            ttl: int = DEFAULT_TTL) -> dict | None:
    """Acquire and register the sole writer lease, or return ``None`` on contention."""
    token = str(uuid.uuid4())
    owner = owner or f"native:{socket.gethostname()}:{os.getpid()}"
    args = {
        "p_project_id": task["project_id"],
        "p_branch": branch,
        "p_task_id": task["id"],
        "p_owner": owner,
        "p_token": token,
        "p_base_sha": _sha(repo, base),
        "p_remote_sha": _sha(repo, f"origin/{branch}"),
        "p_ttl_seconds": max(60, int(ttl)),
    }
    if db.rpc("acquire_branch_execution_lease", args) is not True:
        return None
    lease = {**args, "branch": branch, "token": token, "ttl": max(60, int(ttl))}
    with _lock:
        _active[(str(task["id"]), branch)] = lease
    return lease


def heartbeat(task_id: str, branch: str | None = None) -> bool:
    with _lock:
        leases = [lease for (tid, b), lease in _active.items()
                  if tid == str(task_id) and (branch is None or b == branch)]
    if not leases:
        return False
    return all(db.rpc("heartbeat_branch_execution_lease", {
        "p_project_id": lease["p_project_id"],
        "p_branch": lease["branch"],
        "p_task_id": lease["p_task_id"],
        "p_token": lease["token"],
        "p_ttl_seconds": lease["ttl"],
    }) is True for lease in leases)


def release(task_id: str, branch: str | None = None) -> bool:
    with _lock:
        keys = [key for key in list(_active)
                if key[0] == str(task_id) and (branch is None or key[1] == branch)]
        leases = [_active.pop(key) for key in keys]
    if not leases:
        return False
    released = True
    for lease in leases:
        try:
            released = (db.rpc("release_branch_execution_lease", {
                "p_project_id": lease["p_project_id"],
                "p_branch": lease["branch"],
                "p_task_id": lease["p_task_id"],
                "p_token": lease["token"],
            }) is True) and released
        except Exception:
            # The finite TTL remains the fail-safe if the control plane is unavailable.
            released = False
    return released


def active(task_id: str, branch: str | None = None) -> dict | None:
    with _lock:
        for (tid, b), lease in _active.items():
            if tid == str(task_id) and (branch is None or b == branch):
                return lease
    return None
