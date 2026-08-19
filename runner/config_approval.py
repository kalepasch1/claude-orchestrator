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

# Not every failure is an outage, and the breaker above only makes sense for the ones that
# are. A PostgREST rejection (oversized value, constraint, bad type) is per-key and
# permanent: feeding it to the breaker aborts the pass and prints "the control plane is
# down, not these keys" about keys that are, in fact, the problem — hiding a data bug behind
# outage noise while every remaining healthy key goes unassessed on every cycle forever.
#
# Classified by exception type, and deliberately as an ALLOWLIST of known-permanent types:
# anything unrecognised keeps the old environmental behaviour, which is the one already
# proven to keep the main loop alive during a real outage.
#
# Resolved defensively so an older db.py without these names cannot break the import — an
# empty tuple in an `except` clause simply never matches, which is exactly the right
# degradation.
def _exc(*names):
    found = tuple(getattr(db, n) for n in names if isinstance(getattr(db, n, None), type))
    return found or ()


_PERMANENT_ERRORS = _exc("RequestRejectedError")
_STRUCTURAL_ERRORS = _exc("MissingRelationError")

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
    permanent_failures = []
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
        except _STRUCTURAL_ERRORS as e:
            # The approvals relation is not deployed. Every remaining key will fail for the
            # same reason, and no number of cycles changes that — this is the one case where
            # abandoning immediately is right, and where "the control plane is down" would be
            # an actively misleading thing to print.
            abandoned_at = index
            print(f"config_approval: the approvals table is unavailable ({e}). "
                  f"Abandoning this pass at entry {index + 1} of {len(rows)}; this is a "
                  f"schema problem, not an outage, and retrying will not fix it.")
            break
        except _PERMANENT_ERRORS as e:
            # PostgREST rejected THIS row: an oversized value, a constraint, a bad type. It
            # is per-key and permanent, so it must not feed the outage breaker. It used to:
            # a handful of malformed fleet_config values in a row aborted the pass and
            # printed "the control plane is down, not these keys" — precisely inverted, and
            # it hid a real data bug behind outage noise while the remaining healthy keys
            # went unassessed on every single cycle, forever.
            permanent_failures.append((key, str(e)))
            print(f"config_approval: rejected {key}: {e}")
        except Exception as e:
            # Unknown failures stay on the environmental path. Fail toward the behaviour
            # that is already proven to keep the main loop alive during an outage.
            consecutive_errors += 1
            print(f"config_approval: skipped {key}: {e}")
            if consecutive_errors >= CONSECUTIVE_ERROR_LIMIT:
                abandoned_at = index
                # The entries in the error window were NOT assessed either. Counting only
                # the ones after `index` under-reported the gap by exactly the breaker
                # width, so the log claimed 55 of 60 when the true answer was 60 of 60 —
                # and 55 reads as "five got through".
                never_attempted = len(rows) - index - 1
                unassessed = consecutive_errors + never_attempted
                print(f"config_approval: {consecutive_errors} consecutive write failures — "
                      f"the control plane is down, not these keys. Abandoning this pass with "
                      f"{unassessed} entr{'y' if unassessed == 1 else 'ies'} "
                      f"unassessed ({consecutive_errors} failed, {never_attempted} never "
                      f"attempted); the next cycle retries. Last error: {e}")
                break

    if approved or gated:
        print(f"config_approval: auto-approved {approved}, gated {gated} of {len(rows)} fleet_config entries")
    if permanent_failures:
        # Surfaced separately on purpose. These never resolve on their own, so if they only
        # ever appeared as "skipped" lines among outage noise nobody would ever fix them.
        print(f"config_approval: {len(permanent_failures)} entr"
              f"{'y' if len(permanent_failures) == 1 else 'ies'} were REJECTED and will fail "
              f"identically every cycle until the value or schema is fixed: "
              f"{', '.join(k for k, _ in permanent_failures[:10])}")
    if abandoned_at is not None and not (approved or gated):
        print(f"config_approval: no entries assessed of {len(rows)} — control plane unreachable")
    return approved, gated


if __name__ == "__main__":
    a, g = sweep()
    print(f"swept: {a} approved, {g} gated; blocked_keys={blocked_keys()}")
