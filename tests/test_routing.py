"""Preflight triage routing must be enforced, not just written into prompt headers.

Every pipeline contract for a legal- or security-class task declares a hosted
preflight route, but nothing in the codebase resolved that route -- the header
was hand-written prose. `preflight_triage_model` makes the mapping executable;
these tests pin the escalated path and the default fallback.
"""
import importlib
import os
import pathlib
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
)
import orchestration_pipeline_config as opc


# --- escalated classes ----------------------------------------------------

def test_legal_class_routes_to_gemini():
    assert opc.preflight_triage_model("legal") == opc.PREFLIGHT_ESCALATED_MODEL


def test_decorated_legal_class_routes_to_gemini():
    """The contract emits the class with its need/risk annotation attached."""
    assert (
        opc.preflight_triage_model("legal (need 9, risk legal_posture)")
        == opc.PREFLIGHT_ESCALATED_MODEL
    )


@pytest.mark.parametrize("task_class", ["security", "compliance", "privacy"])
def test_other_escalated_classes_route_to_gemini(task_class):
    assert opc.preflight_triage_model(task_class) == opc.PREFLIGHT_ESCALATED_MODEL


def test_class_matching_is_case_insensitive():
    assert opc.preflight_triage_model("LEGAL") == opc.PREFLIGHT_ESCALATED_MODEL
    assert opc.preflight_triage_model("  Legal (need 9)  ") == opc.PREFLIGHT_ESCALATED_MODEL


# --- default fallback -----------------------------------------------------

def test_generic_class_takes_the_configured_default():
    default = opc.ENV_OVERRIDES["ORCH_PREFLIGHT_MODEL"]
    assert opc.preflight_triage_model("general") == default
    assert default == "local:llama3.2:3b"


@pytest.mark.parametrize("task_class", ["build", "plan", "bugfix", "unknown-class"])
def test_non_escalated_classes_take_the_default(task_class):
    assert opc.preflight_triage_model(task_class) == opc.ENV_OVERRIDES["ORCH_PREFLIGHT_MODEL"]


def test_default_is_env_overridable(monkeypatch):
    monkeypatch.setitem(opc.ENV_OVERRIDES, "ORCH_PREFLIGHT_MODEL", "local:qwen3-coder:30b")
    assert opc.preflight_triage_model("plan") == "local:qwen3-coder:30b"
    assert opc.preflight_triage_model("legal") == opc.PREFLIGHT_ESCALATED_MODEL


# --- fail-soft ------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, "", "   ", 0, [], {}])
def test_bad_input_returns_the_default_instead_of_raising(bad):
    assert opc.preflight_triage_model(bad) == opc.ENV_OVERRIDES["ORCH_PREFLIGHT_MODEL"]


def test_no_argument_returns_the_default():
    assert opc.preflight_triage_model() == opc.ENV_OVERRIDES["ORCH_PREFLIGHT_MODEL"]


def test_escalated_model_is_overridable_without_a_code_change(monkeypatch):
    """ORCH_-prefixed so it is fleet-pushable via fleet_control.py.

    Asserted by re-importing under a set env var rather than by comparing the
    constant to `os.environ.get(..., <the constant>)`, which is true no matter
    what the code does.
    """
    monkeypatch.setenv("ORCH_PREFLIGHT_ESCALATED_MODEL", "google:pinned-by-this-test")
    reloaded = importlib.reload(opc)
    try:
        assert reloaded.PREFLIGHT_ESCALATED_MODEL == "google:pinned-by-this-test"
        assert reloaded.preflight_triage_model("legal") == "google:pinned-by-this-test"
    finally:
        monkeypatch.delenv("ORCH_PREFLIGHT_ESCALATED_MODEL", raising=False)
        importlib.reload(opc)


def test_escalated_model_is_not_pinned_to_a_literal_in_this_file():
    """Regression guard for the drift that broke eight tests in this file.

    The escalated default was bumped one minor version in the source and every
    assertion here still named the old string, so a routine model bump read as
    eight routing failures. Assertions compare against the module's own constant
    now; this test fails if a hardcoded model string comes back.
    """
    import re

    source = pathlib.Path(__file__).read_text()
    hardcoded = re.findall(r'"google:[a-z0-9.\-]*flash"', source)
    assert hardcoded == [], (
        f"hardcoded escalated-model literal(s) in this file: {hardcoded}. "
        "Compare against opc.PREFLIGHT_ESCALATED_MODEL instead."
    )
