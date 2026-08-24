#!/usr/bin/env python3
"""Invariants for the one predicate that decides whether a key may go fleet-wide.

`fleet_contracts.is_safe_config_key` is the single declaration of the credential
policy. CLAUDE.md records what its drift cost: the 2026-08-02 plaintext-credential
incident, after which fleet_config rows holding secrets were purged and a DB guard
added. `fleet_control._safe_key` delegates here precisely so there is no second copy
to drift.

test_fleet_contracts.py covers the predicate's headline cases. This file covers the
edges that a substring-based deny-list actually has, in both directions, because a
security predicate needs its FALSE POSITIVES pinned as deliberately as its true ones:

  * Deny wins over allow. A credential must not smuggle itself in behind a permitted
    prefix, and the deny check runs first so it cannot.
  * Deny markers are SUBSTRINGS, so several innocent keys are denied as collateral —
    ORCH_PATH and ORCH_PATCH_TEMPLATE (via "PAT"), ORCH_MONKEY (via "KEY"),
    ORCH_TOKENIZER (via "TOKEN").

That collateral is recorded here rather than fixed. It fails CLOSED, which is the
correct direction for this predicate, and narrowing the markers to word boundaries to
recover a handful of key names would weaken the guard that exists because this repo
already leaked credentials once. The cost is that pushing ORCH_PATCH_TEMPLATE
fleet-wide silently does nothing — so these tests exist to make that answerable from
the test suite instead of from a debugging session.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fleet_contracts import (  # noqa: E402
    DENY_MARKERS,
    SAFE_PREFIXES,
    is_safe_config_key,
)


# ── credentials are always refused ──────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "ORCH_OPENAI_API_KEY",
    "ORCH_ANTHROPIC_KEY",
    "ORCH_SESSION_TOKEN",
    "ORCH_GITHUB_PAT",
    "ORCH_DB_PASSWORD",
    "ORCH_DB_PWD",
    "ORCH_SERVICE_CREDENTIAL",
    "ORCH_PRIVATE_KEY",
    "ORCH_AUTH_HEADER",
    "ORCH_COOKIE",
    "ORCH_BEARER",
    "ORCH_SESSION_ID",
    "MERGE_SECRET",
    "QUEUE_ACCESS_TOKEN",
])
def test_a_credential_shaped_key_is_never_safe(key):
    assert is_safe_config_key(key) is False, key


def test_deny_beats_a_permitted_prefix():
    """The ordering invariant: a credential cannot hide behind ORCH_."""
    assert is_safe_config_key("ORCH_MAX_PARALLEL") is True
    assert is_safe_config_key("ORCH_MAX_PARALLEL_TOKEN") is False


def test_case_cannot_be_used_to_evade_the_deny_list():
    for key in ("orch_openai_api_key", "Orch_Session_Token", "oRcH_dB_pAsSwOrD"):
        assert is_safe_config_key(key) is False, key


def test_surrounding_whitespace_cannot_be_used_to_evade():
    assert is_safe_config_key("  ORCH_API_KEY  ") is False


def test_every_deny_marker_actually_denies():
    """A marker that stopped working would be invisible without this."""
    for marker in DENY_MARKERS:
        assert is_safe_config_key(f"ORCH_{marker}") is False, marker


# ── it fails closed ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", [None, "", "   ", 42, [], {}, object()])
def test_bad_input_is_never_safe(key):
    assert is_safe_config_key(key) is False


def test_an_unrecognised_prefix_is_refused():
    """Allowlist, not blocklist: unknown families do not go fleet-wide."""
    assert is_safe_config_key("SOMETHING_NEW") is False
    assert is_safe_config_key("AWS_REGION") is False


def test_the_deny_list_is_not_empty():
    """A guard reduced to nothing would silently permit everything credential-shaped."""
    assert DENY_MARKERS
    for essential in ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL"):
        assert essential in DENY_MARKERS, essential


def test_the_allowlist_is_not_a_wildcard():
    assert SAFE_PREFIXES
    assert "" not in SAFE_PREFIXES


# ── genuine tuning knobs still pass ─────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "ORCH_MAX_PARALLEL",
    "ORCH_QV_INTEGRAL_SHELVE",
    "MAX_PARALLEL_CEILING",
    "RAM_FLOOR_GB",
    "PER_TASK_GB",
    "QUEUE_DEPTH_LIMIT",
    "MERGE_CONFLICT_REDO_CAP",
    "TASK_TIMEOUT",
    "SESSION_TTL",
    "COST_CAP_USD",
])
def test_a_secret_free_knob_is_safe(key):
    """If this over-tightens, fleet-wide config stops working and nothing says why."""
    assert is_safe_config_key(key) is True, key


# ── known collateral of substring matching ──────────────────────────────────

@pytest.mark.parametrize("key,marker", [
    ("ORCH_PATH", "PAT"),
    ("ORCH_PATCH_TEMPLATE", "PAT"),
    ("ORCH_PATTERN", "PAT"),
    ("ORCH_COMPATIBILITY", "PAT"),
    ("ORCH_MONKEY", "KEY"),
    ("ORCH_TOKENIZER", "TOKEN"),
])
def test_innocent_keys_denied_as_collateral_are_a_recorded_decision(key, marker):
    """Deny markers are substrings, so these innocent names are refused too.

    Recorded, not fixed. It fails CLOSED, which is the right direction here, and
    narrowing the markers to word boundaries to recover a few names would weaken the
    guard that exists because this repo already leaked credentials once.

    The practical cost: pushing one of these fleet-wide silently does nothing. If that
    ever needs to change, change it deliberately — and this test will be what tells you
    the security trade-off you are making.
    """
    assert marker in key.upper()
    assert is_safe_config_key(key) is False


def test_the_collateral_is_narrow_enough_to_live_with():
    """Sanity bound: the deny-list must not be refusing ordinary knobs wholesale."""
    ordinary = ["ORCH_MAX_PARALLEL", "ORCH_TIMEOUT_SEC", "ORCH_RETRY_LIMIT",
                "ORCH_BATCH_SIZE", "ORCH_POLL_INTERVAL", "ORCH_CACHE_TTL",
                "ORCH_LOG_LEVEL", "ORCH_WORKER_COUNT"]
    denied = [k for k in ordinary if not is_safe_config_key(k)]
    assert denied == [], f"deny-list is over-firing on ordinary knobs: {denied}"


# ── fleet_control delegates rather than keeping a second copy ───────────────

def test_fleet_control_agrees_with_the_contract():
    """Two copies of a security predicate drift; that drift is what 2026-08-02 cost."""
    import fleet_control

    for key in ("ORCH_MAX_PARALLEL", "ORCH_OPENAI_API_KEY", "SOMETHING_NEW",
                "ORCH_SESSION_TOKEN", "RAM_FLOOR_GB", "ORCH_PATH"):
        assert bool(fleet_control._safe_key(key)) is is_safe_config_key(key), key
