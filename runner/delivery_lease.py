"""Repository- and role-scoped delivery leases with a monotonic fencing token.

WHY THIS EXISTS (2026-08-13)
----------------------------
`integration_owner.decide()` answers "may this host integrate?" as a pure function of
`runner_heartbeats`. It is cheap, needs no lock, and cannot wedge the fleet — but it is
*advisory*, and it is consulted exactly once, at the top of a train pass. Three gaps
follow, and all three were live:

  1. TOCTOU. merge_train and release_train call decide() and then spend minutes on
     rebase + full test run + production build before they push. The election can flip
     underneath a pass and nothing re-checks at write time.
  2. FAIL-OPEN IN THREE PLACES. No heartbeat rows -> True; an exception inside decide()
     -> True; an exception at the call site -> "proceeding". Individually defensible,
     collectively they let two hosts both believe they own integration during a
     control-plane hiccup.
  3. A PASS IN FLIGHT IS NEVER INTERRUPTED, by explicit design — so a host that has
     already lost the election keeps pushing to shared refs until its pass ends.

Those are the conditions behind the 54 PUSH-VERIFY-FAILED sha mismatches documented in
integration_owner.py.

A UUID token alone does not close this. A UUID proves *identity* but carries no
*ordering*, so a stalled predecessor that wakes after its lease expired still presents a
valid-looking token. This module adds the missing ingredient — a fencing token in the
Kleppmann sense: a counter, per (repo_key, role), that strictly increases on every
takeover. Writes carry their fence and the store rejects a stale one, so correctness no
longer depends on the loser noticing that it lost.

USE
---
    lease = delivery_lease.acquire("beethoven", delivery_lease.ROLE_RELEASER)
    if lease is None:
        return {"skipped": "another host holds the releaser lease"}
    try:
        ...
        delivery_lease.require(lease, "push staging -> prod")   # immediately before the write
        push()
    finally:
        delivery_lease.release(lease)

`require()` raises LeaseLost. Call it immediately before each shared-ref mutation — the
guarantee is only as tight as the gap between the check and the write.

COMPATIBILITY WINDOW
--------------------
Until 002_repository_delivery_leases.sql is applied everywhere, `available()` is False
and callers fall back to the legacy election. Set ORCH_DELIVERY_LEASE_REQUIRED=true to
end the window and refuse anonymous (unfenced) delivery writes outright.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import uuid
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ROLE_INTEGRATOR = "integrator"
ROLE_RELEASER = "releaser"
ROLES = (ROLE_INTEGRATOR, ROLE_RELEASER)

DEFAULT_TTL = int(os.environ.get("ORCH_DELIVERY_LEASE_TTL_SECONDS", "900") or 900)

HOST = socket.gethostname()

# One value per process incarnation. A restarted runner gets a new generation and so
# cannot renew or fence-verify a lease taken by the process it replaced — which is the
# point of binding the lease to a generation rather than to a hostname. Hostnames
# outlive crashes; that is exactly how a zombie keeps writing.
GENERATION = f"{HOST}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

_active: dict[tuple[str, str], "Lease"] = {}
_lock = threading.RLock()


class LeaseLost(RuntimeError):
    """Raised when a fenced write is attempted without the current lease.

    Always fatal to the pass in progress. Catching this to continue anyway
    reintroduces precisely the race the fencing token exists to prevent.
    """


@dataclass(frozen=True)
class Lease:
    repo_key: str
    role: str
    owner: str
    token: str
    fence: int
    generation: str = GENERATION
    ttl: int = DEFAULT_TTL

    def describe(self) -> str:
        return f"{self.repo_key}/{self.role} fence={self.fence} owner={self.owner}"


def _missing_schema(exc: Exception) -> bool:
    """True when the failure is 'migration not applied yet' rather than a real fault.

    Distinguished so an un-migrated fleet degrades to the legacy election instead of
    refusing to ship, while a genuine outage still fails closed.
    """
    text = str(exc).lower()
    return any(marker in text for marker in (
        "does not exist", "not found", "pgrst202", "undefined_function",
        "undefined_table", "42883", "42p01",
    ))


_available: Optional[bool] = None
_probed_at: float = 0.0
PROBE_RETRY_S = 60.0


def available() -> bool:
    """True only when the fencing RPCs are CONFIRMED deployed.

    Deliberately asymmetric, and the asymmetry is the whole safety property:

      * probe succeeds            -> True, memoised for the process. Fencing is enforced.
      * probe says "no such
        function/relation"        -> False. Migration not applied; legacy election governs.
      * probe fails any other way -> False, re-probed after PROBE_RETRY_S.

    That last line is the one that matters. An earlier draft returned `not
    _missing_schema(exc)`, i.e. True on any unrecognised error — so a credentials
    problem or a Supabase blip would report the fencing plane "available", every
    unfenced call site would raise LeaseLost, and merges and releases would stop
    fleet-wide. A control-plane hiccup must never manufacture a fleet-wide halt; this
    codebase has been bitten by that exact shape before (see the fail-soft note in
    branch_lease.heartbeat).

    Note this cannot be used to fabricate authority. `available()` only decides whether
    an UNFENCED write is tolerated during the compatibility window; a write that does
    carry a lease still goes through verify(), which fails CLOSED on the same outage.
    Operators close the window explicitly with ORCH_DELIVERY_LEASE_REQUIRED=true.
    """
    global _available, _probed_at
    import time
    if _available is True:
        return True
    if _available is False and (time.monotonic() - _probed_at) < PROBE_RETRY_S:
        return False
    _probed_at = time.monotonic()
    try:
        db.rpc("verify_delivery_fence", {
            "p_repo_key": "__probe__", "p_role": ROLE_INTEGRATOR,
            "p_owner": "__probe__",
            "p_token": "00000000-0000-0000-0000-000000000000", "p_fence": 0,
        })
        _available = True
    except Exception as exc:
        if not _missing_schema(exc):
            sys.stderr.write(
                f"[delivery_lease] fencing probe failed ({exc}); treating as UNAVAILABLE "
                "and deferring to the legacy election\n")
        _available = False
    return bool(_available)


def required() -> bool:
    """True once the compatibility window is closed and unfenced writes are refused."""
    return (os.environ.get("ORCH_DELIVERY_LEASE_REQUIRED", "").strip().lower()
            in ("1", "true", "yes", "on"))


def acquire(repo_key: str, role: str, *, owner: Optional[str] = None,
            ttl: int = DEFAULT_TTL) -> Optional[Lease]:
    """Take the (repo_key, role) lease, or return None when another live host holds it.

    Fails CLOSED on contention and on infrastructure error: not acquiring costs one
    delayed train pass, while wrongly acquiring costs a push race against another Mac.
    """
    if role not in ROLES:
        raise ValueError(f"unknown delivery role {role!r}; expected one of {ROLES}")
    token = str(uuid.uuid4())
    owner = owner or f"{HOST}:{os.getpid()}"
    try:
        row = db.rpc("acquire_delivery_lease", {
            "p_repo_key": repo_key,
            "p_role": role,
            "p_owner": owner,
            "p_token": token,
            "p_generation": GENERATION,
            "p_ttl_seconds": max(60, int(ttl)),
        })
    except Exception as exc:
        sys.stderr.write(
            f"[delivery_lease] acquire {repo_key}/{role} infra error ({exc}); NOT ACQUIRED\n")
        return None
    if isinstance(row, list):
        row = row[0] if row else None
    if not row or not row.get("lease_token"):
        return None
    lease = Lease(repo_key=repo_key, role=role, owner=owner,
                  token=str(row.get("lease_token") or token),
                  fence=int(row.get("fence") or 0),
                  generation=GENERATION, ttl=max(60, int(ttl)))
    with _lock:
        _active[(repo_key, role)] = lease
    return lease


def renew(lease: Lease) -> bool:
    """Extend the lease. False means it was genuinely taken over — stop writing.

    Unlike branch_lease.heartbeat, an RPC outage here reports the lease ALIVE. The
    reasoning is the same as there (a lease-infra outage must not mass-kill running
    work), and it is safe *because* it is not the enforcement point: `require()` runs
    immediately before every shared-ref write and fails closed on the same outage.
    """
    try:
        return bool(db.rpc("renew_delivery_lease", {
            "p_repo_key": lease.repo_key, "p_role": lease.role, "p_owner": lease.owner,
            "p_token": lease.token, "p_fence": lease.fence,
            "p_generation": lease.generation, "p_ttl_seconds": lease.ttl,
        }))
    except Exception as exc:
        sys.stderr.write(
            f"[delivery_lease] renew {lease.describe()} infra error ({exc}); assuming alive\n")
        return True


def verify(lease: Lease) -> bool:
    """True iff this exact fence is still the current holder. Fails CLOSED."""
    try:
        return bool(db.rpc("verify_delivery_fence", {
            "p_repo_key": lease.repo_key, "p_role": lease.role, "p_owner": lease.owner,
            "p_token": lease.token, "p_fence": lease.fence,
            "p_generation": lease.generation,
        }))
    except Exception as exc:
        sys.stderr.write(
            f"[delivery_lease] verify {lease.describe()} infra error ({exc}); refusing write\n")
        return False


def require(lease: Optional[Lease], action: str) -> None:
    """Gate a shared-ref mutation on the fence. Raises LeaseLost if not authorised.

    Call this immediately before the write, not at the top of the pass — the whole
    defect being fixed is a check that happened too early.
    """
    if lease is None:
        if required() or available():
            raise LeaseLost(f"refusing {action}: no delivery lease held")
        return                      # compatibility window: legacy election still governs
    if not verify(lease):
        raise LeaseLost(
            f"refusing {action}: delivery lease lost ({lease.describe()}) — "
            "another host has taken over at a higher fence")


def release(lease: Optional[Lease]) -> bool:
    """Release so the next acquirer takes over without waiting out the TTL."""
    if lease is None:
        return False
    with _lock:
        _active.pop((lease.repo_key, lease.role), None)
    try:
        return bool(db.rpc("release_delivery_lease", {
            "p_repo_key": lease.repo_key, "p_role": lease.role, "p_owner": lease.owner,
            "p_token": lease.token, "p_fence": lease.fence,
            "p_generation": lease.generation,
        }))
    except Exception:
        return False                # the TTL still reclaims it; nothing is stuck


def held(repo_key: str, role: str) -> Optional[Lease]:
    with _lock:
        return _active.get((repo_key, role))


def ensure(repo_key: str, role: str, **kwargs) -> Optional[Lease]:
    """Acquire only if this process is not already holding (repo_key, role).

    For passes that touch many repositories one card at a time: acquiring per card
    would be correct but chatty, and — more importantly — releasing per card would drop
    the lease between cards and invite a takeover mid-pass.
    """
    existing = held(repo_key, role)
    if existing is not None:
        return existing
    return acquire(repo_key, role, **kwargs)


def release_all(role: Optional[str] = None) -> int:
    """Release every lease this process holds, optionally limited to one role.

    Called at the end of a multi-repository pass so the next host takes over
    immediately instead of waiting out each TTL.
    """
    with _lock:
        leases = [l for (_, r), l in _active.items() if role is None or r == role]
    return sum(1 for lease in leases if release(lease))
