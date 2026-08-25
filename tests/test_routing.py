"""Preflight triage routing must be enforced, not just written into prompt headers.

Every pipeline contract for a legal- or security-class task declares a hosted
preflight route, but nothing in the codebase resolved that route -- the header
was hand-written prose. `preflight_triage_model` makes the mapping executable;
these tests pin the escalated path and the default fallback.

These tests pin the *routing decision* -- escalated class goes to the escalated
model, everything else takes the configured default -- not the model id strings
themselves. Model ids get repinned when a vendor retires one (see 45afe205,
which moved the escalated default 2.0-flash -> 2.5-flash and left eight tests
here red because they hardcoded the old string). Asserting against
`opc.PREFLIGHT_ESCALATED_MODEL` keeps the routing contract enforced without
re-breaking on the next repin; `test_escalated_model_default_is_pinned` below
is the single place a repin has to be acknowledged deliberately.
"""
import os
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


def test_escalated_route_is_distinct_from_the_default():
    """The whole point of escalation: legal must NOT land on the cheap default."""
    assert opc.PREFLIGHT_ESCALATED_MODEL != opc.ENV_OVERRIDES["ORCH_PREFLIGHT_MODEL"]
    assert opc.preflight_triage_model("legal") != opc.preflight_triage_model("build")


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
    """ORCH_-prefixed so it is fleet-pushable via fleet_control.py."""
    import importlib

    monkeypatch.setenv("ORCH_PREFLIGHT_ESCALATED_MODEL", "google:gemini-3.5-flash")
    reloaded = importlib.reload(opc)
    try:
        assert reloaded.PREFLIGHT_ESCALATED_MODEL == "google:gemini-3.5-flash"
        assert reloaded.preflight_triage_model("legal") == "google:gemini-3.5-flash"
    finally:
        monkeypatch.delenv("ORCH_PREFLIGHT_ESCALATED_MODEL", raising=False)
        importlib.reload(opc)


def test_escalated_model_default_is_pinned():
    """The one place a vendor repin has to be acknowledged on purpose.

    If this fails and the id above it is live, update the string here -- do not
    weaken it away. Every other test in this file routes off the constant so
    that a repin costs exactly one line, here.
    """
    if "ORCH_PREFLIGHT_ESCALATED_MODEL" in os.environ:
        pytest.skip("escalated model is overridden in the environment")
    assert opc.PREFLIGHT_ESCALATED_MODEL == "google:gemini-2.5-flash"
