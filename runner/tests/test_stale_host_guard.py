"""Tests for the server-side stale-host claim guard.

Two layers, because the authority and the testable surface are different things:

  1. BEHAVIOUR — runner/stale_host_guard.py, the rule expressed in Python. Fully exercised here.
  2. STRUCTURE — the migration SQL is the actual enforcement point but needs a live Postgres to
     run, which CI does not have. So the structural tests assert the trigger cannot have been
     rewritten into a shape that reintroduces the bug: that it fires only on an account change,
     that host resolution goes through a controls lookup rather than a hostname-shaped regex,
     and that staleness alone can never raise.

Regressions this suite exists to catch:
  * a paused host claiming anyway (the original bug — Mac 2 claimed 3 tasks after being paused)
  * the guard widening to match cowork-executor accounts and halting the productive fleet
  * the guard firing on progress updates and stranding in-flight work
  * an old paused row outvoting a newer resume, leaving a host permanently unable to claim
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stale_host_guard as guard  # noqa: E402

MIGRATION = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "supabase", "migrations", "20260806120000_stale_host_claim_guard.sql",
)

PAUSED_MAC2 = {
    "scope": "host",
    "project": "Mandys-MacBook-Pro.local",
    "paused": True,
    "reason": "on 10d9e408, 32 commits stale",
    "updated_at": "2026-08-06T15:53:00Z",
    "updated_by": "fleet_control",
}
ACTIVE_MAC1 = {
    "scope": "host",
    "project": "Mac.lan",
    "paused": False,
    "reason": "resumed",
    "updated_at": "2026-08-05T10:00:00Z",
    "updated_by": "fleet_control",
}
CONTROLS = [PAUSED_MAC2, ACTIVE_MAC1]


# ---------------------------------------------------------------------------
# A paused host cannot claim.
# ---------------------------------------------------------------------------

def test_paused_host_claim_is_rejected():
    assert guard.may_claim("Mandys-MacBook-Pro.local-7146", CONTROLS) is False


def test_rejection_names_the_host_and_the_reason():
    msg = guard.claim_rejection("Mandys-MacBook-Pro.local-7146", CONTROLS)
    assert "Mandys-MacBook-Pro.local" in msg
    assert "32 commits stale" in msg


def test_paused_host_matched_without_the_local_suffix():
    """A pause may be recorded as 'Mac-2' or 'Mac-2.local'; both forms must bind."""
    assert guard.may_claim("Mandys-MacBook-Pro-7146", CONTROLS) is False


def test_paused_host_matched_with_no_pid_suffix():
    assert guard.may_claim("Mandys-MacBook-Pro.local", CONTROLS) is False


# ---------------------------------------------------------------------------
# An unpaused host claims normally.
# ---------------------------------------------------------------------------

def test_unpaused_host_claim_succeeds():
    assert guard.may_claim("Mac.lan-9931", CONTROLS) is True


def test_newer_resume_beats_an_older_pause():
    """controls is not append-only. A stale paused row must not permanently strand a host."""
    controls = CONTROLS + [{
        "scope": "host", "project": "Mandys-MacBook-Pro.local", "paused": False,
        "reason": "resumed after update", "updated_at": "2026-08-06T18:00:00Z",
        "updated_by": "fleet_control",
    }]
    assert guard.may_claim("Mandys-MacBook-Pro.local-7146", controls) is True


def test_older_resume_does_not_beat_a_newer_pause():
    controls = [
        {"scope": "host", "project": "Mac.lan", "paused": False,
         "updated_at": "2026-08-01T00:00:00Z", "updated_by": "fleet_control"},
        {"scope": "host", "project": "Mac.lan", "paused": True, "reason": "stale",
         "updated_at": "2026-08-06T00:00:00Z", "updated_by": "fleet_control"},
    ]
    assert guard.may_claim("Mac.lan-1", controls) is False


def test_remote_quarantine_rows_are_ignored():
    controls = [dict(PAUSED_MAC2, updated_by="remote-quarantine")]
    assert guard.may_claim("Mandys-MacBook-Pro.local-7146", controls) is True


def test_host_with_no_control_row_is_not_guarded():
    assert guard.may_claim("Some-Other-Mac.local-4", CONTROLS) is True


# ---------------------------------------------------------------------------
# Non-host accounts are NEVER matched. This is the dangerous direction.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("account", [
    "cowork-executor-v6-1786031596",
    "cowork-executor-12",
    "cowork-executor-v6-b2-1786032696",
    "agentic:claude",
    "agentic:swarm:openai",
    "merge-train",
    "",
])
def test_non_host_accounts_are_never_matched(account):
    assert guard.account_hostname(account, CONTROLS) is None
    assert guard.may_claim(account, CONTROLS) is True


def test_cowork_executor_unaffected_even_when_every_host_is_paused():
    controls = [dict(ACTIVE_MAC1, paused=True), PAUSED_MAC2]
    assert guard.may_claim("cowork-executor-v6-1786031596", controls) is True


def test_a_cowork_executor_shaped_host_row_does_not_leak_into_other_accounts():
    """Even if someone registered a host literally named 'cowork-executor-v6', only that exact
    account prefix binds — 'cowork-executor-12' must stay free."""
    controls = CONTROLS + [{
        "scope": "host", "project": "cowork-executor-v6", "paused": True,
        "updated_at": "2026-08-06T00:00:00Z", "updated_by": "op",
    }]
    assert guard.may_claim("cowork-executor-12", controls) is True
    assert guard.may_claim("cowork-executor-v6-1786031596", controls) is False


def test_longest_hostname_wins_resolution():
    controls = [
        {"scope": "host", "project": "Mac", "paused": False,
         "updated_at": "2026-08-01T00:00:00Z"},
        {"scope": "host", "project": "Mac-Studio", "paused": True, "reason": "stale",
         "updated_at": "2026-08-02T00:00:00Z"},
    ]
    assert guard.account_hostname("Mac-Studio-77", controls) == "Mac-Studio"


# ---------------------------------------------------------------------------
# Only a CLAIM is guarded — progress updates must pass.
# ---------------------------------------------------------------------------

def test_progress_update_that_does_not_change_account_is_not_a_claim():
    assert guard.is_claim("Mandys-MacBook-Pro.local-7146",
                          "Mandys-MacBook-Pro.local-7146") is False


def test_releasing_a_task_is_not_a_claim():
    assert guard.is_claim("Mandys-MacBook-Pro.local-7146", None) is False


def test_taking_an_unheld_task_is_a_claim():
    assert guard.is_claim(None, "Mandys-MacBook-Pro.local-7146") is True


def test_stealing_a_task_from_another_account_is_a_claim():
    assert guard.is_claim("Mac.lan-1", "Mandys-MacBook-Pro.local-7146") is True


# ---------------------------------------------------------------------------
# Staleness corroborates; it never decides.
# ---------------------------------------------------------------------------

def test_stale_sha_alone_does_not_reject_an_unpaused_host():
    """Every host is briefly stale during a rollout. Rejecting on sha alone stops the fleet."""
    assert guard.may_claim(
        "Mac.lan-9931", CONTROLS,
        host_code_sha="deadbeefcafe", fleet_code_sha="0123456789ab",
    ) is True


def test_stale_sha_sharpens_the_message_on_an_already_paused_host():
    msg = guard.claim_rejection(
        "Mandys-MacBook-Pro.local-7146", CONTROLS,
        host_code_sha="10d9e408aaaa", fleet_code_sha="ffffffffbbbb",
    )
    assert "10d9e408" in msg and "ffffffff" in msg


def test_matching_sha_adds_no_noise():
    msg = guard.claim_rejection(
        "Mandys-MacBook-Pro.local-7146", CONTROLS,
        host_code_sha="same", fleet_code_sha="same",
    )
    assert "differs from fleet" not in msg


def test_missing_sha_data_is_not_an_error():
    assert guard.claim_rejection("Mac.lan-9931", CONTROLS, host_code_sha=None) is None


# ---------------------------------------------------------------------------
# STRUCTURE — the migration is the enforcement point; pin its shape.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sql():
    with open(MIGRATION, "r", errors="replace") as fh:
        return fh.read()


def test_migration_exists(sql):
    assert len(sql) > 0


def test_trigger_is_before_update_on_tasks(sql):
    assert re.search(r"before\s+update\s+of\s+account\s+on\s+public\.tasks", sql, re.I)


def test_trigger_fires_only_when_account_changes(sql):
    """Without this WHEN clause the guard would block ordinary progress updates and strand
    every task a paused host already holds."""
    assert re.search(
        r"when\s*\(\s*NEW\.account\s+is\s+not\s+null\s+and\s+NEW\.account\s+is\s+distinct\s+from\s+OLD\.account\s*\)",
        sql, re.I,
    )


def test_guard_function_returns_early_on_a_non_claim(sql):
    assert re.search(r"NEW\.account\s+is\s+not\s+distinct\s+from\s+OLD\.account", sql, re.I)


def test_host_resolution_is_a_controls_lookup_not_a_regex(sql):
    """A shape-based guess would parse 'cowork-executor-v6-1786031596' as a host and start
    rejecting the fleet's most productive accounts."""
    assert "public.controls" in sql
    assert re.search(r"scope\s*=\s*'host'", sql, re.I)


def test_null_host_short_circuits_before_any_rejection(sql):
    assert re.search(r"if\s+v_host\s+is\s+null\s+then\s+return\s+NEW\s*;", sql, re.I | re.S)


def test_latest_control_decision_wins(sql):
    assert re.search(r"order\s+by\s+c\.updated_at\s+desc", sql, re.I)


def test_remote_quarantine_rows_are_excluded_in_sql(sql):
    assert "remote-quarantine" in sql


def test_staleness_never_raises_on_its_own(sql):
    """The only `raise exception` must sit after the paused check, never in a sha-only branch."""
    paused_gate = sql.lower().index("if coalesce(v_paused, false) is not true then")
    raise_at = sql.lower().index("raise exception")
    assert raise_at > paused_gate


def test_trigger_is_installed_idempotently(sql):
    assert re.search(r"drop\s+trigger\s+if\s+exists\s+trg_stale_host_claim_guard", sql, re.I)
    assert re.search(r"create\s+trigger\s+trg_stale_host_claim_guard", sql, re.I)


def test_local_suffix_is_stripped_as_a_suffix_not_a_character_set(sql):
    """`rtrim(x, '.local')` is a CHARACTER-SET trim in Postgres, not a suffix trim.

    It strips any trailing run of {., l, o, c, a} — so a host named 'Mac.local' collapses to
    'M', and alias matching silently binds the wrong host (or none). Suffix stripping must go
    through an anchored regexp.
    """
    assert "rtrim(" not in sql.lower()
    assert re.search(r"regexp_replace\([^,]+,\s*'\\\.local\$'", sql)


def test_helper_functions_are_replaceable(sql):
    for fn in ("stale_host_account_hostname",
               "stale_host_is_paused",
               "enforce_stale_host_claim_guard"):
        assert re.search(rf"create\s+or\s+replace\s+function\s+public\.{fn}", sql, re.I)
