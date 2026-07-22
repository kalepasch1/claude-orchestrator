#!/usr/bin/env python3
from __future__ import annotations
"""
merge_invariant_firewall.py - global pre-merge invariant checks that run BEFORE merge
and block (route to human) any diff that:
  1. Weakens an RLS policy (DROP POLICY, ALTER...DISABLE, permissive->none)
  2. Flips a money-movement/settlement default (e.g. SETTLEMENT_SWEEP_ENABLED)
  3. Removes a money-movement token gate (auth/token checks around transfers)

Implemented as a list of pure predicate checks over the diff so each is unit-testable.
Composes WITH (does not replace) the existing build gate.

Gated behind ORCH_MERGE_FIREWALL_ENABLED (default OFF); when off, behavior is unchanged.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_MERGE_FIREWALL_ENABLED", "false").lower() in ("true", "1", "yes")

# ── Predicate checks: each returns (blocked: bool, reason: str) ──

_RLS_WEAKEN_PATTERNS = [
    re.compile(r"\bDROP\s+POLICY\b", re.I),
    re.compile(r"\bALTER\s+TABLE\b.*\bDISABLE\s+ROW\s+LEVEL\s+SECURITY\b", re.I | re.S),
    re.compile(r"\bALTER\s+POLICY\b.*\bUSING\s*\(\s*true\s*\)", re.I | re.S),
]

_MONEY_DEFAULTS = [
    re.compile(r"""(?:^[-+].*(?:SETTLEMENT_SWEEP_ENABLED|MONEY_MOVEMENT_ENABLED|AUTO_TRANSFER_ENABLED|SWEEP_ENABLED)\s*[=:]\s*(?:true|True|1))""", re.M),
    re.compile(r"""(?:^[-+].*(?:settlement|sweep|transfer|payout).*(?:enabled|active|on)\s*[=:]\s*(?:true|True|1))""", re.I | re.M),
]

_TOKEN_GATE_REMOVAL = [
    re.compile(r"""^-.*(?:require_auth|verify_token|check_token|auth_required|token_gate)""", re.I | re.M),
    re.compile(r"""^-.*(?:if\s+.*(?:token|auth|session).*(?:raise|abort|return|403|401))""", re.I | re.M),
]


def check_rls_weakening(diff_text):
    """Return (blocked, reason) if diff weakens an RLS policy."""
    for rx in _RLS_WEAKEN_PATTERNS:
        m = rx.search(diff_text or "")
        if m:
            return True, f"RLS policy weakened: {m.group(0).strip()[:80]}"
    return False, ""


def check_money_movement_default(diff_text):
    """Return (blocked, reason) if diff flips a money-movement default to enabled."""
    for rx in _MONEY_DEFAULTS:
        m = rx.search(diff_text or "")
        if m:
            return True, f"Money-movement default flipped: {m.group(0).strip()[:80]}"
    return False, ""


def check_token_gate_removal(diff_text):
    """Return (blocked, reason) if diff removes a money-movement token gate."""
    for rx in _TOKEN_GATE_REMOVAL:
        m = rx.search(diff_text or "")
        if m:
            return True, f"Token gate removed: {m.group(0).strip()[:80]}"
    return False, ""


# Registry of all predicate checks — add new checks here
ALL_CHECKS = [
    check_rls_weakening,
    check_money_movement_default,
    check_token_gate_removal,
]


def check_diff(diff_text):
    """Run all invariant checks against a diff. Returns list of (check_name, reason)
    for every violated invariant. Empty list => diff is clean."""
    if not ENABLED:
        return []
    violations = []
    for check_fn in ALL_CHECKS:
        blocked, reason = check_fn(diff_text or "")
        if blocked:
            violations.append((check_fn.__name__, reason))
    return violations


def should_block(diff_text):
    """Convenience: returns True if any invariant is violated (and firewall is enabled)."""
    return len(check_diff(diff_text)) > 0


def gate(diff_text, task=None):
    """Pre-merge gate entry point. Returns (allow: bool, violations: list).
    Composes with existing build gate — callers AND this result with build_gate."""
    violations = check_diff(diff_text)
    if violations:
        names = [v[0] for v in violations]
        reasons = [v[1] for v in violations]
        return False, violations
    return True, []
