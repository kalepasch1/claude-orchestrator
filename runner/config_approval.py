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

# Credential material in fleet_config.
#
# This gate reviews every fleet_config push for "outsized blast radius" and, until now,
# rated GITHUB_PAT=ghp_... as "routine change within safe operating envelope" — the one
# class of change that has actually cost this fleet something. On 2026-08-02 plaintext
# credentials sat in fleet_config until they were found and purged; a DB guard now rejects
# those rows, but a guard that rejects is a wall you learn about by hitting it, and the
# assessor in front of it was still waving the push through. A key with no numeric bound,
# no shell metacharacter, no path and no URL fell straight to the "low" default. Nothing
# here is clever: it is the check that should have existed before the incident.
#
# Two independent signals, either one gates:
#   - the KEY names a credential (GITHUB_PAT, *_TOKEN, *_SECRET, *_PASSWORD, ...)
#   - the VALUE carries a well-known credential shape, whatever the key is called
# The second matters because the naming convention is the thing most likely to be skipped
# by whoever is in a hurry.
_SECRETISH_KEY_RX = re.compile(
    r"(^|_)(PAT|TOKEN|SECRET|SECRETS|PASSWORD|PASSWD|PASS|CREDENTIAL|CREDENTIALS|"
    r"APIKEY|API_KEY|ACCESS_KEY|SECRET_KEY|PRIVATE_KEY|SIGNING_KEY|CLIENT_SECRET|"
    r"AUTH_TOKEN|BEARER|SESSION_KEY|COOKIE_SECRET)(_|$)"
)
_SECRET_VALUE_RX = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{16,}|"
    r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|"
    r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|"
    r"npm_[A-Za-z0-9]{30,}|hf_[A-Za-z0-9]{30,}|dop_v1_[a-f0-9]{60,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
# Storing a *reference* to a secret is the correct pattern and must stay frictionless;
# only the material itself is gated. Empty/off values clear a key and are equally fine.
_SECRET_INDIRECTION_RX = re.compile(
    r"^(env:|\$\{[A-Z0-9_]+\}$|\$[A-Z0-9_]+$|keychain:|vault:|op://|aws-sm:|gcp-sm:)", re.I
)
_SECRET_EMPTYISH = {"", "-", "none", "null", "unset", "false", "0", "disabled", "redacted"}


def _redacted(value: str) -> str:
    """Describe a secret without repeating it.

    _assess() embeds the offending value in its reason, and that reason is written to the
    approvals table. Echoing a credential there would answer a plaintext credential in one
    table with a plaintext credential in another — with a human reading it in a UI. The
    digest is enough to tell two pushes apart and to match against a rotation record.
    """
    v = value or ""
    digest = hashlib.sha1(v.encode()).hexdigest()[:8]
    return f"<redacted {len(v)} chars, sha1:{digest}>"


def _looks_secret(key: str, value: str) -> bool:
    v = (value or "").strip()
    if _SECRET_VALUE_RX.search(v):
        return True
    if not _SECRETISH_KEY_RX.search(key.strip().upper()):
        return False
    if v.lower() in _SECRET_EMPTYISH or _SECRET_INDIRECTION_RX.match(v):
        return False
    return True


def _assess(key: str, value: str) -> tuple:
    """Return (risk, reason): risk is 'high' (gate) or 'low' (auto-approve)."""
    k = key.strip().upper()
    v = (value or "").strip()

    # First, so that no later rule can echo credential material into the card's reason.
    if _looks_secret(key, v):
        return "high", (
            f"{k} looks like credential material {_redacted(v)}; fleet_config is plaintext "
            "and is not a secret store — keep the secret in the keychain/env and push a "
            "reference (env:NAME) if the fleet needs to find it"
        )

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


SEEN_LOOKUP_CHUNK = int(os.environ.get("ORCH_CONFIG_APPROVAL_SEEN_CHUNK", "80"))


def _seen_fingerprints(fingerprints) -> set:
    """Which of `fingerprints` have already been assessed (any decision status).

    Asks about EXACTLY the entries in this pass. The previous version asked the opposite
    question — "give me 2000 config approvals, any 2000" — and built the seen-set from
    whatever came back, unordered. That is a truncated scan of the kind db.py's own
    TRUNCATED-SCAN DETECTOR was written for, and it had gone catastrophic: 77,206 config
    approval rows for 205 distinct fingerprints, 7,386 of them written in the last 24 hours.

    The loop is self-amplifying, which is why it ran away rather than plateauing. Every row
    the sweep re-files makes the table bigger; a bigger table makes the fixed 2000-row window
    a smaller fraction of it; a smaller fraction means more keys look unseen next pass. It
    ends with essentially every key re-filed every cycle, forever.

    It was also a direct multiplier on the 2026-08-19 outage: ~200 pointless writes per
    cycle, each paying a full request timeout while the plane was 522ing. The "60 skipped
    lines per cycle and nothing else" symptom was this.

    Bounded by the size of THIS pass (<= `limit` fleet_config rows), not by the table.
    The durable guarantee is the partial unique index on approvals(detail) WHERE
    kind='config' — this query is the cheap path that avoids provoking it.
    """
    wanted = sorted({fp for fp in fingerprints if fp})
    if not wanted:
        return set()
    seen = set()
    for start in range(0, len(wanted), SEEN_LOOKUP_CHUNK):
        chunk = wanted[start:start + SEEN_LOOKUP_CHUNK]
        try:
            rows = db.select("approvals", {
                "select": "detail", "kind": "eq.config",
                "detail": "in.({})".format(",".join(f"fp:{fp}" for fp in chunk)),
            }) or []
        except Exception:
            # Fail toward NOT re-filing. An unreadable dedup index is a reason to skip this
            # chunk for one cycle, never a reason to re-file every key in it — that is the
            # runaway the fix above exists to end, and it would fire hardest during exactly
            # the control-plane trouble that caused the read to fail.
            seen.update(chunk)
            continue
        for r in rows:
            d = str(r.get("detail") or "")
            if d.startswith("fp:"):
                seen.add(d[3:])
    return seen


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

    try:
        rows = db.select("fleet_config", {
            "select": "key,value,note,updated_by",
            "order": "updated_at.asc", "limit": str(limit),
        }) or []
    except Exception:
        return 0, 0

    # Fingerprint first, THEN ask which of these are already assessed. The order matters:
    # the lookup is now scoped to this pass's entries, so it cannot be outgrown by the
    # approvals table the way an unordered "any 2000 rows" window was.
    fingerprints = {_fingerprint(str(r.get("key") or ""), str(r.get("value") or ""))
                    for r in rows if r.get("key")}
    seen = _seen_fingerprints(fingerprints)

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
