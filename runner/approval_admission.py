"""Admission control for `approvals` inserts — dedupe + per-kind rate limit.

WHY THIS EXISTS (measured 2026-08-07): `approvals` had 170,468 rows with a NULL
`decided_at`. Grouped by kind, `self` alone was 100,851 of them (59%). Nobody is
ever going to hand-decide 100k rows, so every one of those inserts was pure noise
that buried the cards a human actually needs to see.

The flood has no single author — ~30 modules call `db.insert("approvals", ...)`
directly. Rate-limiting each call site would be ~30 edits that drift apart, so the
gate lives at the one choke point every caller already passes through: `db.insert`.

Two independent brakes, both fail-soft:

  * DEDUPE   — an identical still-undecided card (project, kind, title) is not
               inserted twice inside the dedupe TTL. Self-review cards repeat
               verbatim every loop; the second one carries no information.
  * RATE CAP — a rolling 24h ceiling per gated kind, counted in-process. Even
               a novel-title flood cannot exceed the cap.

Only kinds listed in ORCH_APPROVAL_GATED_KINDS are gated (default: `self`).
Operator-facing kinds — material, legal, ops — are deliberately NOT gated: losing
one of those is far worse than reading a duplicate.

Configuration (all fleet-pushable via fleet_control.py, all with defaults):
    ORCH_APPROVAL_ADMISSION       "0" disables the gate entirely (default on)
    ORCH_APPROVAL_GATED_KINDS     comma-separated kinds to gate (default "self")
    ORCH_APPROVAL_DAILY_CAP       max gated inserts per kind per 24h (default 200)
    ORCH_APPROVAL_DEDUPE_TTL_SEC  dedupe window in seconds (default 86400)

Module-level singleton: the public functions delegate to `_gate`, one
thread-safe `_ApprovalGate` created at import time. Callers never construct one.
"""

import os
import threading
import time

GATE = "approval_admission"

_DEFAULT_GATED_KINDS = "self"
_DEFAULT_DAILY_CAP = 200
_DEFAULT_DEDUPE_TTL_SEC = 86400
_WINDOW_SEC = 86400


def _env_int(name, default):
    """Read an int env var, falling back to *default* on anything unparseable."""
    try:
        return int(str(os.getenv(name, "")).strip() or default)
    except Exception:
        return default


def enabled():
    """True unless ORCH_APPROVAL_ADMISSION is explicitly falsey."""
    return str(os.getenv("ORCH_APPROVAL_ADMISSION", "1")).strip().lower() not in (
        "0", "false", "no", "off")


def gated_kinds():
    """Set of approval kinds the gate applies to."""
    raw = os.getenv("ORCH_APPROVAL_GATED_KINDS", _DEFAULT_GATED_KINDS)
    return {k.strip().lower() for k in str(raw).split(",") if k.strip()}


def daily_cap():
    """Max admitted inserts per gated kind per rolling 24h."""
    return max(0, _env_int("ORCH_APPROVAL_DAILY_CAP", _DEFAULT_DAILY_CAP))


def dedupe_ttl():
    """Seconds an admitted (project, kind, title) blocks an identical repeat."""
    return max(0, _env_int("ORCH_APPROVAL_DEDUPE_TTL_SEC", _DEFAULT_DEDUPE_TTL_SEC))


def fingerprint(row):
    """Stable dedupe key for an approvals row. Empty string if unusable."""
    if not isinstance(row, dict):
        return ""
    try:
        project = str(row.get("project") or row.get("project_id") or "").strip().lower()
        kind = str(row.get("kind") or "").strip().lower()
        title = " ".join(str(row.get("title") or "").split()).strip().lower()
        if not kind:
            return ""
        return f"{project}|{kind}|{title}"
    except Exception:
        return ""


class _ApprovalGate:
    """Thread-safe rolling-window counter + recent-fingerprint memory."""

    def __init__(self):
        self._lock = threading.Lock()
        self._seen = {}        # fingerprint -> admitted-at epoch
        self._admitted = {}    # kind -> [epoch, ...] within the rolling window

    def _prune(self, now):
        """Drop expired fingerprints and out-of-window admissions. Lock held."""
        ttl = dedupe_ttl()
        if ttl:
            for fp in [f for f, at in self._seen.items() if now - at > ttl]:
                self._seen.pop(fp, None)
        for kind, stamps in list(self._admitted.items()):
            fresh = [s for s in stamps if now - s <= _WINDOW_SEC]
            if fresh:
                self._admitted[kind] = fresh
            else:
                self._admitted.pop(kind, None)

    def admit(self, row):
        """Return (allowed: bool, reason: str). Never raises."""
        try:
            if not enabled() or not isinstance(row, dict):
                return True, ""
            kind = str(row.get("kind") or "").strip().lower()
            if kind not in gated_kinds():
                return True, ""
            fp = fingerprint(row)
            now = time.time()
            with self._lock:
                self._prune(now)
                ttl = dedupe_ttl()
                if not ttl:
                    fp = ""    # TTL of 0 disables dedupe; the cap still applies
                if fp and fp in self._seen:
                    age = int(now - self._seen[fp])
                    return False, (f"duplicate undecided approval (kind={kind}) "
                                   f"already inserted {age}s ago")
                cap = daily_cap()
                count = len(self._admitted.get(kind, ()))
                if count >= cap:
                    return False, (f"kind={kind} rate cap reached "
                                   f"({count}/{cap} per 24h)")
                if fp:
                    self._seen[fp] = now
                self._admitted.setdefault(kind, []).append(now)
                return True, ""
        except Exception:
            return True, ""    # fail-open: the gate must never wedge an insert

    def stats(self):
        """Observability for operators and tests."""
        try:
            now = time.time()
            with self._lock:
                self._prune(now)
                return {
                    "enabled": enabled(),
                    "gated_kinds": sorted(gated_kinds()),
                    "daily_cap": daily_cap(),
                    "dedupe_ttl_sec": dedupe_ttl(),
                    "tracked_fingerprints": len(self._seen),
                    "admitted_last_24h": {k: len(v) for k, v in self._admitted.items()},
                }
        except Exception:
            return {}

    def reset(self):
        """Clear all state. Used by tests and by long-lived daemons on reconfig."""
        try:
            with self._lock:
                self._seen.clear()
                self._admitted.clear()
        except Exception:
            pass


_gate = _ApprovalGate()


def admit(row):
    """Should this approvals row be inserted? Returns (allowed, reason)."""
    return _gate.admit(row)


def stats():
    """Current gate state as a plain dict."""
    return _gate.stats()


def reset():
    """Forget all dedupe/rate state."""
    _gate.reset()
