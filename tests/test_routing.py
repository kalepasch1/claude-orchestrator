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


def test_escalated_model_is_overridable_without_a_code_change():
    """ORCH_-prefixed so it is fleet-pushable via fleet_control.py.

    Asserted by RE-READING the module with the env var set, because the constant is
    resolved at import time — checking `PREFLIGHT_ESCALATED_MODEL == os.environ.get(
    "ORCH_PREFLIGHT_ESCALATED_MODEL", <the same constant>)` would pass no matter what
    the code did.
    """
    import importlib

    sentinel = "google:gemini-test-sentinel"
    original = os.environ.get("ORCH_PREFLIGHT_ESCALATED_MODEL")
    os.environ["ORCH_PREFLIGHT_ESCALATED_MODEL"] = sentinel
    try:
        reloaded = importlib.reload(opc)
        assert reloaded.PREFLIGHT_ESCALATED_MODEL == sentinel
        assert reloaded.preflight_triage_model("legal") == sentinel
    finally:
        if original is None:
            os.environ.pop("ORCH_PREFLIGHT_ESCALATED_MODEL", None)
        else:
            os.environ["ORCH_PREFLIGHT_ESCALATED_MODEL"] = original
        importlib.reload(opc)


def test_the_escalated_route_is_a_hosted_model_and_not_the_local_default():
    """The point of the escalation is a stronger safety posture than the free local
    default. Pinned as a PROPERTY rather than as a literal model string: the default
    was bumped google:gemini-2.0-flash -> 2.5-flash in the config and eight tests in
    this file went red because they hard-coded 2.0, which is what this task was
    dispatched to fix. A version bump must not be a test failure; dropping the
    escalation, or pointing it at the local model, still must be.
    """
    escalated = opc.preflight_triage_model("legal")
    assert escalated != opc.ENV_OVERRIDES["ORCH_PREFLIGHT_MODEL"]
    assert not escalated.startswith("local:"), escalated
    assert ":" in escalated, "route must be provider:model"


@pytest.mark.parametrize("task_class", opc.PREFLIGHT_ESCALATED_CLASSES)
def test_every_declared_escalated_class_actually_escalates(task_class):
    """Reads the class list from the module, so adding a class to it without wiring
    the route cannot pass silently."""
    assert opc.preflight_triage_model(task_class) == opc.PREFLIGHT_ESCALATED_MODEL
