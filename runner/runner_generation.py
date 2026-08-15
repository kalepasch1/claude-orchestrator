#!/usr/bin/env python3
"""runner_generation.py — runner identity, monotonic generation, and write fencing.

THE GAP
-------
`runtime_contract.check()` proves a process holds a compatible *module signature*.
It says nothing about *which incarnation* of a runner is speaking. A long-lived
runner that was restarted, rolled back, or is running on a second Mac from an
older checkout can still hold a valid contract hash for ITS code and go on
claiming tasks, integrating branches and mutating canonical proof rows. The
2026-08 two-Mac incident is exactly that: two processes, same host identity,
different code, both writing canonical state, last writer wins.

THE MODEL
---------
Three identifiers, in increasing volatility:

  * ``runner_id``   — immutable per install. Persisted at ``.runtime/runner_id``.
                      Survives restarts; identifies the *seat*, not the process.
  * ``generation``  — monotonic per seat. Bumped once per process start and
                      persisted at ``.runtime/runner_generation``. Identifies the
                      *incarnation*.
  * ``code_sha`` / ``contract_hash`` — what that incarnation is actually running.

The control plane publishes an ADMISSION: the generation it has admitted for a
seat plus the contract digest it expects. A fence token carrying all five fields
accompanies every claim and every canonical mutation. Anything stale or
unadmitted is refused.

THE ONE RULE THAT MAKES THIS SAFE
---------------------------------
Block STARTING, never block FINISHING — the same contract `paused_host_guard`
and `stale_host_guard` already use. A superseded generation may finish the work
it already holds and write a *recoverable artifact* (a patch, a branch, a log).
It may not claim, integrate, release, or mutate canonical proof. Stranding
in-flight work is worse than the drift being fenced.

ROLLOUT COMPATIBILITY
---------------------
During a rollout, older runners send fences with no ``generation`` and no
``contract_hash``. Those are classified LEGACY and admitted **only while the
control plane has published no admission for that seat**. The moment an
admission exists, a legacy fence is unadmitted — so the rollout is: deploy the
new module everywhere, then publish admissions, and old writers stop.

FAIL-SOFT
---------
Every public function returns a sensible default rather than raising: unreadable
state files yield a fresh id, a bad admission mapping yields "no admission",
and `record_drain_alert` swallows insert failures after logging. A fencing layer
that wedges the fleet when `.runtime` is briefly unwritable is a worse outage
than the drift it prevents.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import time
import uuid

log = logging.getLogger(__name__)

HOST = socket.gethostname()

RUNTIME_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime")
RUNNER_ID_FILE = os.path.join(RUNTIME_DIR, "runner_id")
GENERATION_FILE = os.path.join(RUNTIME_DIR, "runner_generation")

# Emitted into runner_alerts when a contract-mismatched host is drained. Silence
# is how the two-Mac race stayed invisible for weeks.
ALERT_KIND = "runner_generation_drained"

# Operations that mutate canonical, shared state. A stale generation may do none
# of these; it may still produce a recoverable artifact.
CANONICAL_OPERATIONS = ("claim", "integrate", "release", "proof")
SAFE_FINISH_OPERATIONS = ("artifact", "log", "heartbeat", "finish")

# Classifications returned by classify().
ADMITTED = "admitted"
LEGACY_PRE_ROLLOUT = "legacy_pre_rollout"
STALE_GENERATION = "stale_generation"
UNADMITTED_RUNNER = "unadmitted_runner"
CONTRACT_MISMATCH = "contract_mismatch"
MALFORMED_FENCE = "malformed_fence"

_lock = threading.Lock()
_runner_id = None
_generation = None


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #
def _read(path):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _write(path, value):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(str(value))
        return True
    except OSError as exc:  # fail-soft: an unwritable .runtime must not wedge a runner
        log.debug("runner_generation: could not persist %s (%s)", path, exc)
        return False


def runner_id():
    """Immutable per-install seat id. Stable across restarts; fail-soft on I/O."""
    global _runner_id
    with _lock:
        if _runner_id:
            return _runner_id
        existing = _read(RUNNER_ID_FILE)
        if existing:
            _runner_id = existing
            return _runner_id
        _runner_id = f"{HOST}-{uuid.uuid4().hex[:12]}"
        _write(RUNNER_ID_FILE, _runner_id)
        return _runner_id


def next_generation():
    """Bump and persist the monotonic generation. Call ONCE per process start."""
    global _generation
    with _lock:
        try:
            current = int(_read(GENERATION_FILE) or 0)
        except ValueError:
            current = 0
        _generation = max(current, 0) + 1
        _write(GENERATION_FILE, _generation)
        return _generation


def generation():
    """This process's generation, allocating one on first use."""
    global _generation
    if _generation is None:
        return next_generation()
    return _generation


def _contract():
    try:
        import runtime_contract
        proof = runtime_contract.check()
        return str(proof.get("contract_hash") or ""), str(proof.get("code_sha") or "")
    except Exception as exc:  # fail-soft: contract inspection is best-effort here
        log.debug("runner_generation: contract inspection failed (%s)", exc)
        return "", ""


def fence_token(runner=None, gen=None, code_sha=None, contract_hash=None):
    """Build the fence carried by every claim and canonical mutation.

    ``token`` is a digest of the identity tuple, so a row's fence cannot be
    partially forged by editing one column.
    """
    ch, sha = _contract()
    fence = {
        "runner_id": runner or runner_id(),
        "generation": int(gen if gen is not None else generation()),
        "code_sha": code_sha or sha,
        "contract_hash": contract_hash or ch,
        "host": HOST,
        "pid": os.getpid(),
        "issued_at": time.time(),
    }
    fence["token"] = fence_digest(fence)
    return fence


def fence_digest(fence):
    """Stable digest over the identity tuple only (never over volatile fields)."""
    f = fence or {}
    parts = "|".join(str(f.get(k) or "") for k in
                     ("runner_id", "generation", "code_sha", "contract_hash", "host"))
    return hashlib.sha256(parts.encode()).hexdigest()[:16]


def normalize_fence(fence):
    """Coerce any mapping into the fence shape. Missing fields stay missing.

    Missing is meaningful: it is what distinguishes a pre-rollout writer from a
    superseded one, so absent keys are NOT defaulted to zero here.
    """
    f = dict(fence or {}) if isinstance(fence, dict) else {}
    out = {}
    rid = str(f.get("runner_id") or "").strip()
    if rid:
        out["runner_id"] = rid
    if f.get("generation") is not None:
        try:
            out["generation"] = int(f["generation"])
        except (TypeError, ValueError):
            pass
    for key in ("code_sha", "contract_hash", "host", "token"):
        value = str(f.get(key) or "").strip()
        if value:
            out[key] = value
    if f.get("pid") is not None:
        try:
            out["pid"] = int(f["pid"])
        except (TypeError, ValueError):
            pass
    return out


# --------------------------------------------------------------------------- #
# admission
# --------------------------------------------------------------------------- #
def normalize_admission(admission):
    """Coerce a control-plane admission row. Returns {} when there is none."""
    a = dict(admission or {}) if isinstance(admission, dict) else {}
    out = {}
    rid = str(a.get("runner_id") or "").strip()
    if rid:
        out["runner_id"] = rid
    if a.get("generation") is not None:
        try:
            out["generation"] = int(a["generation"])
        except (TypeError, ValueError):
            return {}
    expected = str(a.get("contract_hash") or "").strip()
    if expected:
        out["contract_hash"] = expected
    return out if out.get("runner_id") and "generation" in out else {}


def classify(fence, admission=None):
    """Classify a fence against the published admission for its seat.

    Returns one of ADMITTED / LEGACY_PRE_ROLLOUT / STALE_GENERATION /
    UNADMITTED_RUNNER / CONTRACT_MISMATCH / MALFORMED_FENCE.
    """
    f = normalize_fence(fence)
    a = normalize_admission(admission)
    if not f.get("runner_id"):
        return MALFORMED_FENCE
    if not a:
        # No admission published for this seat yet — pre-rollout. A fence that
        # already carries a generation is fine; one that does not is legacy.
        return ADMITTED if "generation" in f else LEGACY_PRE_ROLLOUT
    if a["runner_id"] != f["runner_id"]:
        return UNADMITTED_RUNNER
    if "generation" not in f:
        # An admission exists, so this writer predates the rollout: refuse.
        return UNADMITTED_RUNNER
    if f["generation"] < a["generation"]:
        return STALE_GENERATION
    if f["generation"] > a["generation"]:
        # Ahead of admission: the control plane has not admitted it yet.
        return UNADMITTED_RUNNER
    expected = a.get("contract_hash")
    if expected and f.get("contract_hash") and f["contract_hash"] != expected:
        return CONTRACT_MISMATCH
    return ADMITTED


def may(operation, fence, admission=None):
    """(allowed, reason) for a named operation.

    Canonical operations require an admitted fence. Safe-finish operations —
    writing a recoverable artifact, a log line, a heartbeat — are always
    permitted, because block-start/allow-safe-finish is the whole contract.
    """
    op = str(operation or "").strip().lower()
    verdict = classify(fence, admission)
    if op in SAFE_FINISH_OPERATIONS:
        return True, f"{op} permitted (safe-finish) under {verdict}"
    if op not in CANONICAL_OPERATIONS:
        # Unknown operations are treated as canonical: fail closed on the
        # write path, which is the side where a mistake is unrecoverable.
        pass
    if verdict in (ADMITTED, LEGACY_PRE_ROLLOUT):
        return True, f"{op} permitted ({verdict})"
    return False, f"{op} refused ({verdict})"


def may_claim(fence, admission=None):
    return may("claim", fence, admission)


def may_integrate(fence, admission=None):
    return may("integrate", fence, admission)


def may_release(fence, admission=None):
    return may("release", fence, admission)


def may_mutate_canonical(fence, admission=None):
    return may("proof", fence, admission)


def may_finish(fence, admission=None):
    """Always True. A superseded generation must be able to land its artifact."""
    return may("finish", fence, admission)


# --------------------------------------------------------------------------- #
# drain
# --------------------------------------------------------------------------- #
def drain_plan(fence, admission=None):
    """Alert payload for a fence that must be drained, or None when admitted.

    Drain means: stop giving this seat new work. It does not mean kill — the
    in-flight pass still finishes and still writes its artifact.
    """
    verdict = classify(fence, admission)
    if verdict in (ADMITTED, LEGACY_PRE_ROLLOUT):
        return None
    f = normalize_fence(fence)
    a = normalize_admission(admission)
    return {
        "kind": ALERT_KIND,
        "verdict": verdict,
        "runner_id": f.get("runner_id") or "unknown",
        "host": f.get("host") or HOST,
        "generation": f.get("generation"),
        "admitted_generation": a.get("generation"),
        "code_sha": f.get("code_sha"),
        "contract_hash": f.get("contract_hash"),
        "expected_contract_hash": a.get("contract_hash"),
        "detail": (f"runner {f.get('runner_id') or 'unknown'} on {f.get('host') or HOST} "
                   f"drained: {verdict}"),
    }


def record_drain_alert(payload, insert=None):
    """Write the drain alert in its OWN successful transaction. Fail-soft.

    Deliberately separate from whatever refusal triggered it: if the refusal
    path rolls back, the operator must still be able to see that a host was
    drained. Returns True when the alert was durably recorded.
    """
    if not payload:
        return False
    writer = insert
    if writer is None:
        try:
            import db
            writer = db.insert
        except Exception as exc:  # fail-soft: no DB is not a reason to raise
            log.debug("runner_generation: alert writer unavailable (%s)", exc)
            return False
    row = dict(payload)
    row.setdefault("created_at", "now()")
    try:
        writer("runner_alerts", row)
        return True
    except Exception as exc:  # fail-soft, but never silent
        log.warning("runner_generation: drain alert not recorded (%s); payload=%s",
                    exc, json.dumps(payload, default=str)[:400])
        return False


def enforce(operation, fence, admission=None, insert=None):
    """(allowed, reason). Refusals emit a durable drain alert as a side effect."""
    allowed, reason = may(operation, fence, admission)
    if not allowed:
        record_drain_alert(drain_plan(fence, admission), insert=insert)
    return allowed, reason


def proof():
    """Serializable snapshot for heartbeats and `runtime_contract.check()`."""
    fence = fence_token()
    return {"runner_id": fence["runner_id"], "generation": fence["generation"],
            "code_sha": fence["code_sha"], "contract_hash": fence["contract_hash"],
            "host": fence["host"], "pid": fence["pid"], "fence_token": fence["token"]}


if __name__ == "__main__":  # pragma: no cover - operator convenience
    print(json.dumps(proof(), indent=2, default=str))
