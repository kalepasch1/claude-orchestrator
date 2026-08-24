"""Cross-machine, cross-executor one-writer leases for mutable task branches."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import uuid

import db
from typing import Optional


DEFAULT_TTL = int(os.environ.get("ORCH_BRANCH_LEASE_TTL_SECONDS", "3600") or 3600)

#: Floor applied to every requested TTL. A lease shorter than this expires while the
#: holder is still mid-rebase, which is indistinguishable from lease loss. Named (and
#: ORCH_-prefixed, so it is fleet-pushable via fleet_control.py) because CLAUDE.md's
#: lease-RPC postmortem calls out the bare literals in this module by name.
MIN_TTL = int(os.environ.get("ORCH_BRANCH_LEASE_MIN_TTL_SECONDS", "60") or 60)

#: Wall-clock budget for the `git rev-parse` probes below. These run against a possibly
#: NFS-backed or lock-contended checkout, so the bound has to exist; it just has to be
#: adjustable without a code change when a repo is slow.
GIT_PROBE_TIMEOUT = int(os.environ.get("ORCH_BRANCH_LEASE_GIT_TIMEOUT_SECONDS", "15") or 15)

#: Module-level singleton registry of leases this process currently holds, keyed by
#: (task_id, branch). Initialised empty at import and mutated only under ``_lock``;
#: the module functions (``acquire``/``heartbeat``/``release``/``active``) delegate to
#: it rather than threading lease state through call chains. Documented here because
#: CLAUDE.md's rule is not "no module state" but "no *undocumented* module state".
_active: dict[tuple[str, str], dict] = {}

#: Reentrant guard for ``_active``. Reentrant because release() pops under the lock while
#: iterating a snapshot taken under the same lock.
_lock = threading.RLock()


def _sha(repo: str, ref: str) -> Optional[str]:
    """Resolve *ref* in *repo*, or ``None`` when it cannot be resolved.

    Fail-soft by design — an unresolvable ref is normal (origin/<branch> does not exist
    yet on a first push). The broad catch writes a diagnostic first: CLAUDE.md's
    corrected rule is that a *logged* broad catch is the convention here and a silent
    one is the defect, because a lease acquired with a silently-empty base SHA looks
    identical to one acquired with a correct base SHA.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", ref], cwd=repo,
            capture_output=True, text=True, timeout=GIT_PROBE_TIMEOUT,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception as e:
        import sys
        sys.stderr.write(
            f"[branch_lease] rev-parse {ref!r} in {repo!r} failed "
            f"({type(e).__name__}: {e}); fail-soft None\n"
        )
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
        "p_ttl_seconds": max(MIN_TTL, int(ttl)),
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
    lease = {**args, "branch": branch, "token": token, "ttl": max(MIN_TTL, int(ttl))}
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
        except Exception as e:
            # The finite TTL remains the fail-safe if the control plane is unavailable.
            # Logged, not silent: an unreleased lease blocks the next writer for up to a
            # full TTL, and without this line that stall has no attributable cause.
            import sys
            sys.stderr.write(
                f"[branch_lease] release RPC infra error for {lease.get('branch')!r} "
                f"({type(e).__name__}: {e}); lease will expire on its TTL\n"
            )
            released = False
    return released


def active(task_id: str, branch: Optional[str] = None) -> Optional[dict]:
    with _lock:
        for (tid, b), lease in _active.items():
            if tid == str(task_id) and (branch is None or b == branch):
                return lease
    return None
