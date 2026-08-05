#!/usr/bin/env python3
"""Tests for pipeline_contract security/legal task gating.

Covers the allowlist envelope: LEGAL_RX / SECURITY_RX classification,
ORCH_{SECURITY,LEGAL}_TASK_ALLOWLIST env gating, RESTRICTED_OPERATIONS and
_operation_authorized. Allowlists must resolve at call time so a fleet-wide
config push applies without restarting the runner.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline_contract as pc  # noqa: E402


ALLOWLIST_KEYS = (
    "ORCH_SECURITY_TASK_ALLOWLIST",
    "ORCH_LEGAL_TASK_ALLOWLIST",
    "ORCH_LEGAL_ALLOWED_OPERATIONS",
    "ORCH_SECURITY_ALLOWED_OPERATIONS",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ALLOWLIST_KEYS:
        monkeypatch.delenv(k, raising=False)
    yield


# --- _parse_allowlist -------------------------------------------------------

def test_parse_allowlist_unset_is_none():
    assert pc._parse_allowlist(None) is None


def test_parse_allowlist_empty_string_allows_nothing():
    assert pc._parse_allowlist("") == set()
    assert pc._parse_allowlist("  , ,") == set()


def test_parse_allowlist_normalizes_case_and_whitespace():
    assert pc._parse_allowlist(" BugFix , build ") == {"bugfix", "build"}


# --- task_allowlist ---------------------------------------------------------

def test_task_allowlist_none_when_unset():
    assert pc.task_allowlist("legal") is None
    assert pc.task_allowlist("security") is None


def test_task_allowlist_unknown_class_is_none():
    assert pc.task_allowlist("build") is None
    assert pc.task_allowlist("") is None
    assert pc.task_allowlist(None) is None


def test_task_allowlist_reads_env_at_call_time(monkeypatch):
    """Import-time snapshot must not freeze the value."""
    assert pc.task_allowlist("legal") is None
    monkeypatch.setenv("ORCH_LEGAL_TASK_ALLOWLIST", "bugfix")
    assert pc.task_allowlist("legal") == {"bugfix"}
    monkeypatch.setenv("ORCH_LEGAL_TASK_ALLOWLIST", "bugfix,build")
    assert pc.task_allowlist("legal") == {"bugfix", "build"}


# --- _credential_allows -----------------------------------------------------

def test_credential_allows_when_no_allowlist_configured():
    assert pc._credential_allows("legal", "build", "licensing change") is True
    assert pc._credential_allows("security", "build", "oauth change") is True


def test_credential_allows_only_listed_kinds(monkeypatch):
    monkeypatch.setenv("ORCH_LEGAL_TASK_ALLOWLIST", "bugfix")
    assert pc._credential_allows("legal", "bugfix", "licensing") is True
    assert pc._credential_allows("legal", "build", "licensing") is False


def test_credential_allows_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("ORCH_SECURITY_TASK_ALLOWLIST", "BugFix")
    assert pc._credential_allows("security", "bugfix", "oauth") is True
    assert pc._credential_allows("security", "BUGFIX", "oauth") is True


def test_credential_allows_empty_allowlist_denies_everything(monkeypatch):
    monkeypatch.setenv("ORCH_LEGAL_TASK_ALLOWLIST", "")
    assert pc._credential_allows("legal", "build", "licensing") is False


def test_credential_allows_tolerates_none_kind(monkeypatch):
    monkeypatch.setenv("ORCH_LEGAL_TASK_ALLOWLIST", "bugfix")
    assert pc._credential_allows("legal", None, "licensing") is False


def test_credential_allows_classes_are_independent(monkeypatch):
    monkeypatch.setenv("ORCH_LEGAL_TASK_ALLOWLIST", "bugfix")
    # security has no allowlist -> still permitted
    assert pc._credential_allows("security", "build", "oauth") is True


# --- classify ---------------------------------------------------------------

def test_classify_legal_prompt_without_allowlist():
    out = pc.classify("update the licensing registration flow", kind="build")
    assert out["task_class"] == "legal"
    assert out["need"] == 9
    assert out["risk"] == "legal_posture"


def test_classify_legal_downgrades_when_kind_not_allowlisted(monkeypatch):
    monkeypatch.setenv("ORCH_LEGAL_TASK_ALLOWLIST", "bugfix")
    out = pc.classify("update the licensing registration flow", kind="build")
    assert out["task_class"] == "build"
    assert out["security_gated"] is True
    assert out["risk"] == "standard"


def test_classify_legal_kept_when_kind_allowlisted(monkeypatch):
    monkeypatch.setenv("ORCH_LEGAL_TASK_ALLOWLIST", "bugfix")
    out = pc.classify("update the licensing registration flow", kind="bugfix")
    assert out["task_class"] == "legal"


def test_classify_security_downgrades_when_not_allowlisted(monkeypatch):
    monkeypatch.setenv("ORCH_SECURITY_TASK_ALLOWLIST", "bugfix")
    out = pc.classify("rotate the oauth token handling", kind="build")
    assert out["task_class"] == "build"
    assert out["security_gated"] is True


def test_classify_plain_build_unaffected_by_allowlists(monkeypatch):
    monkeypatch.setenv("ORCH_LEGAL_TASK_ALLOWLIST", "")
    monkeypatch.setenv("ORCH_SECURITY_TASK_ALLOWLIST", "")
    out = pc.classify("add a button to the dashboard", kind="build")
    assert out["task_class"] == "build"
    assert "security_gated" not in out


def test_classify_material_flag_forces_legal_path(monkeypatch):
    monkeypatch.setenv("ORCH_LEGAL_TASK_ALLOWLIST", "")
    out = pc.classify("harmless copy tweak", kind="build", material=True)
    assert out["security_gated"] is True


def test_classify_handles_empty_prompt():
    out = pc.classify("", kind="build")
    assert out["task_class"] == "build"


# --- RESTRICTED_OPERATIONS / _operation_authorized --------------------------

def test_restricted_operations_membership():
    assert "task_security_gate" in pc.RESTRICTED_OPERATIONS
    assert "task_legal_gate" in pc.RESTRICTED_OPERATIONS
    assert "permission_audit" in pc.RESTRICTED_OPERATIONS
    assert "credential_validation" in pc.RESTRICTED_OPERATIONS
    assert "plan" not in pc.RESTRICTED_OPERATIONS


def test_operation_authorized_defaults_open():
    assert pc._operation_authorized("task_legal_gate", "legal") is True


def test_operation_authorized_respects_allowlist(monkeypatch):
    monkeypatch.setenv("ORCH_LEGAL_ALLOWED_OPERATIONS", "task_legal_gate")
    assert pc._operation_authorized("task_legal_gate", "legal") is True
    assert pc._operation_authorized("permission_audit", "legal") is False


def test_operation_authorized_empty_allowlist_denies(monkeypatch):
    monkeypatch.setenv("ORCH_LEGAL_ALLOWED_OPERATIONS", "  ")
    assert pc._operation_authorized("task_legal_gate", "legal") is False


def test_operation_authorized_fail_soft_on_bad_operation_name(monkeypatch):
    monkeypatch.setenv("ORCH_SECURITY_ALLOWED_OPERATIONS", "Bad-Name!")
    # invalid names raise internally; fail-soft allows rather than wedging
    assert pc._operation_authorized("task_security_gate", "security") is True


def test_operation_authorized_fail_soft_on_bad_task_class():
    assert pc._operation_authorized("task_legal_gate", None) is True


def test_no_allowlist_key_contains_a_secret():
    """Guard: gating keys must never look like credential carriers."""
    for key in ALLOWLIST_KEYS:
        assert not any(w in key for w in ("PASSWORD", "TOKEN", "SECRET", "KEY"))
