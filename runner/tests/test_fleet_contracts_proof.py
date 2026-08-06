"""The narrowest check that proves the fleet_config contract holds in PRODUCTION.

Slice 1 declared the contract (runner/fleet_contracts.py) and unit-tested it
against invented keys. That proves the predicate is internally consistent; it
does not prove the predicate is TRUE of the fleet it governs. Those are different
claims, and on 2026-08-06 the second one was false: 50 of the 68 keys then live
in fleet_config were refused by the allowlist, among them
COWORK_EXECUTOR_*_LAST_RUN — the executors' own heartbeat.

That matters because FLEET_CONFIG_SCHEMA declares fail_closed. A fail-closed
allowlist that has never been reconciled with reality is not a stricter policy,
it is an outage waiting for the day someone wires it into the write path. This
file is the reconciliation, kept as a test so it cannot silently rot.

Two directions, both required:
  - every key the fleet actually uses is ACCEPTED (no self-inflicted outage)
  - every credential from the 2026-08-02 incident is REFUSED (the policy still bites)
"""
import os
import subprocess
import sys

import pytest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import fleet_contracts  # noqa: E402

LIVE_KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "fleet_config_live_keys.txt")


def _live_keys():
    with open(LIVE_KEYS_FILE, encoding="utf-8") as handle:
        return [line.strip() for line in handle
                if line.strip() and not line.lstrip().startswith("#")]


LIVE_KEYS = _live_keys()

# The four credentials found in plaintext by the 2026-08-02 scan, plus the
# service-role key that slipped past an earlier API_?KEY-only pattern.
INCIDENT_KEYS = (
    "VERCEL_TOKEN", "GITHUB_PAT", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "SUPABASE_SERVICE_KEY",
)


# ── The task's stated acceptance criterion, executed verbatim ─────────────────

def test_stated_proof_command_exits_zero():
    """`python -c "import runner.fleet_contracts as c; assert ..."` exits 0.

    Run as a subprocess from the repo root, exactly as an operator would, so the
    check covers importability from a cold interpreter and not just the symbols
    being present in this already-warm process.
    """
    repo_root = os.path.dirname(RUNNER_DIR)
    program = (
        "import runner.fleet_contracts as c; "
        "assert c.FLEET_CONFIG_SCHEMA and hasattr(c,'is_safe_config_key') "
        "and hasattr(c,'fail_soft')"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=repo_root, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"proof command failed (exit {result.returncode}):\n{result.stderr}")


# ── Direction 1: the allowlist must not refuse the fleet's own keys ──────────

def test_the_live_key_corpus_is_not_empty():
    """A corpus that silently emptied would make the next test pass vacuously."""
    assert len(LIVE_KEYS) >= 50, f"only {len(LIVE_KEYS)} keys loaded from {LIVE_KEYS_FILE}"


@pytest.mark.parametrize("key", LIVE_KEYS)
def test_every_live_fleet_config_key_is_accepted(key):
    assert fleet_contracts.is_safe_config_key(key), (
        f"{key!r} is live in fleet_config but the fail-closed allowlist refuses it. "
        f"Enforcing is_safe_config_key() at the write path would break whatever "
        f"writes this key. Add its FAMILY to SAFE_PREFIXES — or, if it really is a "
        f"credential, remove it from the table and rotate it."
    )


def test_the_executor_heartbeat_specifically_survives():
    """Called out by name because it is the one whose refusal wedges the fleet."""
    for key in ("COWORK_EXECUTOR_V6_LAST_RUN", "heartbeat:cowork-executor",
                "EXEC_1_LAST", "AUTOPILOT_SWEEP_LIMIT"):
        assert fleet_contracts.is_safe_config_key(key), key


# ── Direction 2: the policy must still bite ──────────────────────────────────

@pytest.mark.parametrize("key", INCIDENT_KEYS)
def test_incident_credentials_are_still_refused(key):
    assert not fleet_contracts.is_safe_config_key(key)


@pytest.mark.parametrize("key", [
    "OPENAI_API_KEY",       # the OPENAI_ prefix is now allowed — the marker must win
    "GEMINI_API_KEY",
    "COWORK_SESSION_TOKEN",
    "AUTOPILOT_SECRET",
    "EXEC_PRIVATE_KEY",
    "HEARTBEAT_BEARER",
    "PREVIEW_CREDENTIAL",
])
def test_a_deny_marker_beats_every_newly_added_prefix(key):
    """Widening the allowlist must not open a door for a credential.

    Deny markers are evaluated before the prefix allowlist; this pins that
    ordering against each prefix added in this slice, since that is precisely
    the regression a wider allowlist invites.
    """
    assert not fleet_contracts.is_safe_config_key(key)


def test_the_new_prefixes_did_not_make_the_allowlist_accept_everything():
    """The fail-closed property is the whole point; prove it still holds."""
    for key in ("RANDOM_THING", "FOO", "postgres_url", "x", "aws_config"):
        assert not fleet_contracts.is_safe_config_key(key), key


def test_no_prefix_is_short_enough_to_be_a_wildcard():
    """A one- or two-character prefix would accept most of the keyspace."""
    for prefix in fleet_contracts.SAFE_PREFIXES:
        assert len(prefix) >= 4, f"SAFE_PREFIXES entry {prefix!r} is too broad"


# ── The two enforcement points must agree with the contract ──────────────────

def test_fleet_control_agrees_with_the_contract_on_the_live_corpus():
    """fleet_control._safe_key delegates here; prove the delegation is real.

    Slice 1 pointed _safe_key at this module but kept a local fallback list. If
    the delegation ever breaks, the fallback silently answers instead — and the
    fallback still refuses 50 live keys.
    """
    import fleet_control
    disagreements = [
        key for key in LIVE_KEYS
        if fleet_control._safe_key(key) != fleet_contracts.is_safe_config_key(key)
    ]
    assert not disagreements, (
        f"fleet_control._safe_key disagrees with the contract on: {disagreements}")
