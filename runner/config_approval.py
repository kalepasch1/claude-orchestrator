#!/usr/bin/env python3
"""
config_approval.py - automated quality/safety gate for fleet_config pushes.

Every new or changed fleet_config entry is assessed before load_config() applies it:

  AUTO-APPROVE: routine numeric/boolean changes within known-safe envelopes → audited,
    never blocks the fleet.

  GATE (approval card): values with outsized blast-radius (MAX_PARALLEL=0, out-of-range
    TASK_TIMEOUT), shell metacharacters, unexpected paths/URLs, or disabling critical flags.
    load_config() skips gated keys until the card is cleared by the owner.

Assessment is rule-based (no LLM calls); same fail-soft, audit-trail approach as
approval_policy.py. Dedup by fingerprint so re-pushing the same value never creates a
duplicate card.
"""
import os, re, sys, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

POLICY_MARK = "auto-config-policy"
ENABLED = os.environ.get("CONFIG_APPROVAL_ENABLED", "true").lower() in ("true", "1", "yes")

# Circuit breaker for the per-entry insert loop.
#
# The sweep does ONE network write per unreviewed fleet_config entry, and swallows each
# failure individually. That is fail-soft per key but not per PASS: during a control-plane
# outage every one of ~60 keys still pays a full request timeout, the pass takes minutes
# instead of milliseconds, and the scheduler runs it again on the next tick. Observed on
# mac-lan 2026-08-19 during a Supabase 522: the runner's main loop stopped emitting
# scheduler lines entirely and did nothing but print 60 "skipped ... 522" lines per cycle,
# so self-deploy stopped firing and the fleet stalled behind an outage it was supposed to
# ride out. Once N writes fail consecutively the plane is down, not the key — abandon the
# rest of the pass and retry on the next cycle. delivery_lease.available() states the same
# principle: a control-plane hiccup must never manufacture a fleet-wide halt.
CONSECUTIVE_ERROR_LIMIT = int(os.environ.get("ORCH_CONFIG_APPROVAL_ERROR_LIMIT", "5"))

# Numeric bounds for high-blast-radius config keys. Values outside range → approval card.
_NUMERIC_BOUNDS = {
    "MAX_PARALLEL": (1, 20),
    "ORCH_EXTRA_CODERS": (0, 10),
    "ORCH_AUTO_PULL_MIN": (1, 60),
    "ORCH_FLEET_TICK_S": (10, 300),
    "TASK_TIMEOUT": (60, 7200),
    "PER_TASK_GB": (0.5, 32.0),
    "RAM_FLOOR_GB": (0.5, 64.0),
}

# Shell metacharacters / injection patterns
_INJECTION_RX = re.compile(r"[;|&`]|\$\(|>\s*/|<\s*/", re.I)
# Absolute path patterns
_PATH_RX = re.compile(r"^(?:/[^/]|~[/\\]|\.{1,2}[/\\]|[A-Za-z]:\\)", )
# Unexpected URLs in config values
_URL_RX = re.compile(r"https?://|ftp://", re.I)


def _assess(key: str, value: str) -> tuple:
    """Return (risk, reason): risk is 'high' (gate) or 'low' (auto-approve)."""
    k = key.strip().upper()
    v = (value or "").strip()

    if _INJECTION_RX.search(v):
        return "high", f"value contains shell metacharacter(s): {v[:80]!r}"
    if _PATH_RX.match(v):
        return "high", f"value looks like a filesystem path: {v[:80]!r}"
    if _URL_RX.search(v):
        return "high", f"value contains a URL (unexpected in fleet config): {v[:80]!r}"

    if k in _NUMERIC_BOUNDS:
        lo, hi = _NUMERIC_BOUNDS[k]
        try:
            n = float(v)
            if not lo <= n <= hi:
                return "high", f"{k}={v} outside safe range [{lo}, {hi}]"
        except ValueError:
            return "high", f"{k} expects a number, got {v[:40]!r}"

    if k == "ORCH_AUTO_PULL" and v.lower() in ("false", "0", "no"):
        return "high", "disabling ORCH_AUTO_PULL stops automated code propagation to all fleet machines"

    return "low", "routine change within safe operating envelope"


def _fingerprint(key: str, value: str) -> str:
    return hashlib.sha1(f"{key}\x00{value}".encode()).hexdigest()[:16]


def _seen_fingerprints() -> set:
    """Fingerprints of config entries already assessed (any decision status)."""
    try:
        rows = db.select("approvals", {
            "select": "detail", "kind": "eq.config", "limit": "2000",
        }) or []
        fps = set()
        for r in rows:
            d = str(r.get("detail") or "")
            if d.startswith("fp:"):
                fps.add(d[3:])
        return fps
    except Exception:
        return set()


def blocked_keys() -> set:
    """Keys whose latest config assessment is still pending — load_config() must skip these."""
    try:
        rows = db.select("approvals", {
            "select": "title", "kind": "eq.config",
            "status": "eq.pending", "limit": "500",
        }) or []
        keys = set()
        for r in rows:
            title = str(r.get("title") or "")
            # title shape: "fleet_config: KEY=..."
            if title.startswith("fleet_config: "):
                rest = title[len("fleet_config: "):]
                k = rest.split("=", 1)[0].strip()
                if k:
                    keys.add(k)
        return keys
    except Exception:
        return set()


def sweep(limit: int = 200) -> tuple:
    """
    Assess every fleet_config entry not yet reviewed. Returns (auto_approved, gated).
    Fail-soft: any DB error is swallowed so this never wedges the runner.
    """
    if not ENABLED:
        return 0, 0

    seen = _seen_fingerprints()
    try:
        rows = db.select("fleet_config", {
            "select": "key,value,note,updated_by",
            "order": "updated_at.asc", "limit": str(limit),
        }) or []
    except Exception:
        return 0, 0

    approved = gated = consecutive_errors = 0
    abandoned_at = None
    for index, row in enumerate(rows):
        key = str(row.get("key") or "")
        value = str(row.get("value") or "")
        note = str(row.get("note") or "")
        if not key:
            continue
        fp = _fingerprint(key, value)
        if fp in seen:
            continue

        risk, reason = _assess(key, value)
        title = f"fleet_config: {key}={value[:60]!r}"
        why = (f"fleet_config push: {key}={value!r}\n\n"
               f"Note: {note}\n\nAssessment: [{risk.upper()}] {reason}")

        base = {
            "kind": "config",
            "project": "fleet",
            "title": title[:200],
            "why": why[:2000],
            "detail": f"fp:{fp}",
            "radar_tag": "config-safety",
        }
        try:
            if risk == "high":
                db.insert("approvals", {**base, "status": "pending"})
                gated += 1
            else:
                db.insert("approvals", {
                    **base,
                    "status": "approved",
                    "decided_by": POLICY_MARK,
                    "decision_type": "approve",
                    "decision_text": f"auto-approved: {reason}",
                })
                approved += 1
            consecutive_errors = 0
        except Exception as e:
            consecutive_errors += 1
            print(f"config_approval: skipped {key}: {e}")
            if consecutive_errors >= CONSECUTIVE_ERROR_LIMIT:
                abandoned_at = index
                print(f"config_approval: {consecutive_errors} consecutive write failures — "
                      f"the control plane is down, not these keys. Abandoning this pass with "
                      f"{len(rows) - index - 1} entr{'y' if len(rows) - index - 1 == 1 else 'ies'} "
                      f"unassessed; the next cycle retries. Last error: {e}")
                break

    if approved or gated:
        print(f"config_approval: auto-approved {approved}, gated {gated} of {len(rows)} fleet_config entries")
    if abandoned_at is not None and not (approved or gated):
        print(f"config_approval: no entries assessed of {len(rows)} — control plane unreachable")
    return approved, gated


if __name__ == "__main__":
    a, g = sweep()
    print(f"swept: {a} approved, {g} gated; blocked_keys={blocked_keys()}")
