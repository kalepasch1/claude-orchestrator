"""Cross-machine, cross-executor one-writer leases for mutable task branches."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import uuid

import db
from typing import Optional


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """ORCH_-prefixed integer knob. Fail-soft: junk falls back to `default`.

    Never raises at import — a malformed fleet_config push must not stop a runner from
    starting, which is the one failure that cannot be fixed by another fleet_config push.
    """
    try:
        value = int(str(os.environ.get(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


DEFAULT_TTL = int(os.environ.get("ORCH_BRANCH_LEASE_TTL_SECONDS", "3600") or 3600)

# NAMED, FLEET-PUSHABLE CONSTANTS (CLAUDE.md, lease-RPC night follow-up).
#
# These were bare literals inline — `timeout=15` on the git call and `max(60, ttl)`
# repeated at two call sites. CLAUDE.md records the rule this violates: name magic
# numbers and give them ORCH_ prefixes so they are fleet-pushable via fleet_control,
# rather than requiring a code change and a redeploy to every machine to retune.
#
# The floor matters for correctness, not just tidiness: a TTL below it would let a lease
# expire while its task is still running, which is precisely the cross-machine
# single-writer guarantee this module exists to provide. It is a floor, never a cap.
GIT_TIMEOUT_SECONDS = _env_int("ORCH_BRANCH_LEASE_GIT_TIMEOUT_SECONDS", 15)
MIN_TTL_SECONDS = _env_int("ORCH_BRANCH_LEASE_MIN_TTL_SECONDS", 60)


def effective_ttl(ttl) -> int:
    """The TTL actually requested, never below MIN_TTL_SECONDS. Never raises."""
    try:
        return max(MIN_TTL_SECONDS, int(ttl))
    except (TypeError, ValueError):
        return max(MIN_TTL_SECONDS, int(DEFAULT_TTL))


_active: dict[tuple[str, str], dict] = {}
_lock = threading.RLock()


def _sha(repo: str, ref: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", ref], cwd=repo,
            capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def _lease_token(lease: dict) -> str:
    """Normalize token access across current ("token") and legacy ("p_token")
    lease shapes, so a legacy record can never present an empty token to the
    lease RPCs (which would mask genuine lease loss behind the fail-soft
    heartbeat path)."""
    return str(lease.get("token") or lease.get("p_token") or "")


def acquire(task: dict, repo: str, branch: str, base: str, *, owner: Optional[str] = None,
            ttl: int = DEFAULT_TTL) -> Optional[dict]:
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
        "p_ttl_seconds": effective_ttl(ttl),
    }
    try:
        acquired = db.rpc("acquire_branch_execution_lease", args)
    except Exception as e:
        # An unavailable lease control plane is not proof of contention. Fail closed
        # and let the runner requeue instead of turning an RPC outage into a task error.
        import sys
        sys.stderr.write(
            f"[branch_lease] acquire RPC infra error ({e}); fail-soft NOT ACQUIRED\n"
        )
        return None
    if acquired is not True:
        return None
    lease = {**args, "branch": branch, "token": token, "ttl": effective_ttl(ttl)}
    with _lock:
        _active[(str(task["id"]), branch)] = lease
    return lease


def heartbeat(task_id: str, branch: Optional[str] = None) -> bool:
    with _lock:
        leases = [lease for (tid, b), lease in _active.items()
                  if tid == str(task_id) and (branch is None or b == branch)]
    if not leases:
        return False
    # FAIL-SOFT (2026-07-28): if the lease RPC infrastructure itself errors (missing/drifted
    # RPC on prod -> HTTPError), treat the heartbeat as ALIVE and log — a lease-infra outage
    # must never mass-kill running tasks (this exact failure quarantined 91 tasks in one
    # evening). Mirrors repo_lock's documented fail-soft philosophy; local per-repo flocks
    # still serialize mutations on this machine. A genuine `False` from the RPC (lease lost
    # to another holder) is still honored and returns False.
    try:
        return all(db.rpc("heartbeat_branch_execution_lease", {
            "p_project_id": lease["p_project_id"],
            "p_branch": lease["branch"],
            "p_task_id": lease["p_task_id"],
            "p_token": _lease_token(lease),
            "p_ttl_seconds": lease["ttl"],
        }) is True for lease in leases)
    except Exception as e:
        import sys
        sys.stderr.write(f"[branch_lease] heartbeat RPC infra error ({e}); fail-soft ALIVE\n")
        return True


def release(task_id: str, branch: Optional[str] = None) -> bool:
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
                "p_token": _lease_token(lease),
            }) is True) and released
        except Exception:
            # The finite TTL remains the fail-safe if the control plane is unavailable.
            released = False
    return released


def active(task_id: str, branch: Optional[str] = None) -> Optional[dict]:
    with _lock:
        for (tid, b), lease in _active.items():
            if tid == str(task_id) and (branch is None or b == branch):
                return lease
    return None
