"""Credentials must never be storable in the fleet_config table.

Guards incident 2026-08-02: a scan of fleet_config found FIVE rows carrying credential
material in plaintext — VERCEL_TOKEN, GITHUB_PAT, OPENAI_API_KEY, GEMINI_API_KEY and a
status blob (COWORK_EXECUTOR_6_LAST_RUN) whose value matched a token shape. GITHUB_PAT
is push access to every repo. fleet_config is replicated fleet-wide, echoed into drift
reports and config diffs, and has no row-level protection.

A deny list already existed in config_applier and config_sync, but both are opt-in
helpers on one write path while a dozen other writers never consulted them. This suite
pins the enforcement at the DB choke point, where every writer must pass.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_config_guard as g


# --- detection by key name -------------------------------------------------

@pytest.mark.parametrize("key", [
    "VERCEL_TOKEN", "GITHUB_PAT", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY", "SUPABASE_SERVICE_KEY", "STRIPE_SECRET_KEY",
    "DATABASE_URL", "SLACK_BOT_TOKEN", "SOME_PASSWORD", "svc_credential",
    "session_key", "PRIVATE_KEY", "AUTH_KEY",
])
def test_credential_named_keys_are_refused(key):
    assert g.is_secret(key, "whatever")


# --- detection by value shape (an innocuous name proves nothing) -----------

@pytest.mark.parametrize("value", [
    "vcp_" + "a" * 40,                       # Vercel
    "ghp_" + "b" * 36,                       # GitHub PAT
    "github_pat_" + "c" * 30,
    "sk-" + "d" * 40,                        # OpenAI / Anthropic
    "sk_live_" + "e" * 30,                   # Stripe
    "whsec_" + "f" * 30,                     # Stripe webhook signing
    "xoxb-" + "1" * 30,                      # Slack
    "re_" + "g" * 30,                        # Resend
    "AIza" + "h" * 35,                       # Google / Gemini
    "AKIA" + "IOSFODNN7EXAMPLE",             # AWS access key id (canonical 20-char form)
    "eyJhbGciOiJIUzI1NiJ9." + "i" * 30,      # JWT
    "-----BEGIN RSA PRIVATE KEY-----",
    "postgres://user:hunter2@db.host/app",   # DSN with inline password
])
def test_credential_shaped_values_are_refused_under_any_key_name(value):
    # The live table literally contained a row keyed `key`; names are not evidence.
    assert g.is_secret("perfectly_innocent_name", value)


# --- legitimate config must still be writable ------------------------------

@pytest.mark.parametrize("key,value", [
    ("MAX_PARALLEL", "20"),
    ("MAX_PARALLEL_CEILING", "24"),
    ("ORCH_PER_PROJECT_CODE_LANES", "5"),
    ("RELEASE_INTERVAL_HOURS", "2"),
    ("PROMOTION_STATE", '{"status":"ok","at":1785725497}'),
    ("ORCH_LAST_TEST_RESULT_abc12345", "unit=PASS, browser=PASS"),
    ("OLLAMA_KEEP_ALIVE", "30m"),
])
def test_operational_config_is_allowed(key, value):
    assert not g.is_secret(key, value), f"{key} is ordinary config and must remain writable"


# --- the refusal must not become a second leak ----------------------------

def test_reason_never_echoes_the_secret():
    secret = "vcp_" + "S3CR3T" * 8
    _, reason = g.classify("VERCEL_TOKEN", secret)
    assert secret not in reason
    assert "S3CR3T" not in reason


def test_assert_writable_raises_with_actionable_guidance():
    with pytest.raises(ValueError) as e:
        g.assert_writable("GITHUB_PAT", "ghp_" + "x" * 36)
    msg = str(e.value)
    assert "os.environ" in msg, "the error must say where secrets belong instead"


# --- the choke point itself ------------------------------------------------

def test_db_guards_every_write_verb():
    """insert / upsert / update must all route through the guard.

    Enforcing at some doors is not enforcing. This asserts the wiring stays in db.py
    rather than drifting back into an opt-in helper.
    """
    import db
    src = open(db.__file__, encoding="utf-8").read()
    assert "_guard_fleet_config" in src
    # insert() covers upsert() (upsert delegates to insert), plus an explicit update() hook
    assert src.count("_guard_fleet_config(") >= 3, "a write verb lost its guard"


def test_guard_fails_closed_when_the_module_is_missing():
    """If fleet_config_guard cannot import, db.py must still block the obvious cases."""
    import db
    src = open(db.__file__, encoding="utf-8").read()
    assert "fallback" in src.lower() and "SECRET|TOKEN" in src, \
        "the fallback path is gone — a broken import would silently allow secrets"


def test_scan_rows_reports_keys_not_values():
    rows = [{"key": "VERCEL_TOKEN", "value": "vcp_" + "z" * 40},
            {"key": "MAX_PARALLEL", "value": "20"}]
    found = g.scan_rows(rows)
    assert [f["key"] for f in found] == ["VERCEL_TOKEN"]
    assert "value" not in found[0], "the audit must report length, never material"
    assert found[0]["value_len"] == 44
