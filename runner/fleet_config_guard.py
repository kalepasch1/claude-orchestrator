#!/usr/bin/env python3
"""fleet_config_guard.py - credentials must never be stored in the fleet_config table.

WHY THIS EXISTS (incident 2026-08-02): a scan of fleet_config found FOUR live
credentials sitting in plaintext — VERCEL_TOKEN, GITHUB_PAT, OPENAI_API_KEY and
GEMINI_API_KEY. GITHUB_PAT is push access to every repo. Any process, on any host,
that could read fleet config could read them; the table has no row-level protection
and its values are echoed into logs, drift reports and config diffs.

The ban already existed in TWO places — config_applier._is_safe_key and
config_sync._is_safe_key — but both are *opt-in* helpers on one write path, and there
are a dozen other writers (config_changelog, config_rollback, auto_tune_applicator,
continuous_test, decomposition_backpressure, and raw SQL INSERTs) that never consulted
them. A policy enforced at some of the doors is not enforced.

So the check moves to the only place every writer must pass through: db.insert /
db.upsert / db.update. Fail CLOSED — if this module cannot be imported, db.py falls
back to its own inline pattern rather than allowing the write.

Detection is by NAME *and* by VALUE SHAPE, because the observed table also contained a
row literally keyed `key` — an innocuous name is no evidence of innocuous content.
"""
import re

# Key names that always denote a credential.
_NAME_RE = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIAL|_PAT\b|^PAT$|"
    # Any *_KEY / KEY_* / bare KEY. Deliberately broad: SUPABASE_SERVICE_KEY slipped
    # past an earlier `API_?KEY`-only pattern, which is exactly how a service-role key
    # would have been stored. Ordinary config does not end in _KEY.
    r"(^|_)KEY(_|$)|_KEY\b|"
    r"COOKIE|DSN|CONNECTION_?STRING|DATABASE_URL)",
    re.IGNORECASE)

# Value shapes that denote a credential regardless of the key's name.
_VALUE_RE = re.compile(
    r"("
    r"vcp_[A-Za-z0-9]{20,}"              # Vercel
    r"|gh[pousr]_[A-Za-z0-9]{20,}"       # GitHub PAT / OAuth / server / refresh
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-[A-Za-z0-9_\-]{20,}"           # OpenAI / Anthropic
    r"|sk_(live|test)_[A-Za-z0-9]{20,}"  # Stripe
    r"|rk_(live|test)_[A-Za-z0-9]{20,}"
    r"|whsec_[A-Za-z0-9]{20,}"           # Stripe webhook signing
    r"|xox[baprs]-[A-Za-z0-9\-]{20,}"    # Slack
    r"|re_[A-Za-z0-9_]{20,}"             # Resend
    r"|AIza[A-Za-z0-9_\-]{30,}"          # Google / Gemini
    r"|AKIA[0-9A-Z]{16}"                 # AWS access key id
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{20,}"   # JWT (header is often ~20 chars)
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|postgres(ql)?://[^\s:]+:[^\s@]+@"  # DSN with an inline password
    r")")


def classify(key, value=None):
    """Return (is_secret, reason). Reason NEVER contains any part of the value."""
    k = str(key or "")
    if _NAME_RE.search(k):
        return True, f"key name '{k}' denotes a credential"
    v = "" if value is None else str(value)
    m = _VALUE_RE.search(v)
    if m:
        # Report the FORMAT, never the material.
        prefix = m.group(0)[:4]
        return True, f"value under key '{k}' has the shape of a credential ({prefix}…)"
    return False, ""


def is_secret(key, value=None):
    return classify(key, value)[0]


def assert_writable(key, value=None):
    """Raise ValueError if this key/value pair must not be persisted to fleet_config."""
    secret, reason = classify(key, value)
    if secret:
        raise ValueError(
            f"[fleet-config-guard] refusing to store a credential in fleet_config: {reason}. "
            f"Secrets belong in the host env / secret store and are read with "
            f"os.environ.get(); fleet_config is replicated, logged and diffed fleet-wide.")
    return True


def scan_rows(rows):
    """Audit helper: given [{key,value}], return the offending keys (never the values)."""
    out = []
    for r in rows or []:
        secret, reason = classify(r.get("key"), r.get("value"))
        if secret:
            out.append({"key": r.get("key"), "reason": reason,
                        "value_len": len(str(r.get("value") or ""))})
    return out
