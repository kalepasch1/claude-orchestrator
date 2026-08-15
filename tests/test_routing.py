"""Preflight triage routing must be enforced, not just written into prompt headers.

Every pipeline contract for a legal- or security-class task declares a hosted
preflight route, but nothing in the codebase resolved that route -- the header
was hand-written prose. `preflight_triage_model` makes the mapping executable;
these tests pin the escalated path and the default fallback.
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
    assert opc.preflight_triage_model("legal") == "google:gemini-2.0-flash"


def test_decorated_legal_class_routes_to_gemini():
    """The contract emits the class with its need/risk annotation attached."""
    assert (
        opc.preflight_triage_model("legal (need 9, risk legal_posture)")
        == "google:gemini-2.0-flash"
    )


@pytest.mark.parametrize("task_class", ["security", "compliance", "privacy"])
def test_other_escalated_classes_route_to_gemini(task_class):
    assert opc.preflight_triage_model(task_class) == "google:gemini-2.0-flash"


def test_class_matching_is_case_insensitive():
    assert opc.preflight_triage_model("LEGAL") == "google:gemini-2.0-flash"
    assert opc.preflight_triage_model("  Legal (need 9)  ") == "google:gemini-2.0-flash"


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
    assert opc.preflight_triage_model("legal") == "google:gemini-2.0-flash"


# --- fail-soft ------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, "", "   ", 0, [], {}])
def test_bad_input_returns_the_default_instead_of_raising(bad):
    assert opc.preflight_triage_model(bad) == opc.ENV_OVERRIDES["ORCH_PREFLIGHT_MODEL"]


def test_no_argument_returns_the_default():
    assert opc.preflight_triage_model() == opc.ENV_OVERRIDES["ORCH_PREFLIGHT_MODEL"]


def test_escalated_model_is_overridable_without_a_code_change():
    """ORCH_-prefixed so it is fleet-pushable via fleet_control.py."""
    assert opc.PREFLIGHT_ESCALATED_MODEL == os.environ.get(
        "ORCH_PREFLIGHT_ESCALATED_MODEL", "google:gemini-2.0-flash"
    )
