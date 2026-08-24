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

def test_legal_class_routes_to_the_escalated_model():
    assert opc.preflight_triage_model("legal") == opc.PREFLIGHT_ESCALATED_MODEL


def test_decorated_legal_class_routes_to_the_escalated_model():
    """The contract emits the class with its need/risk annotation attached."""
    assert (
        opc.preflight_triage_model("legal (need 9, risk legal_posture)")
        == opc.PREFLIGHT_ESCALATED_MODEL
    )


@pytest.mark.parametrize("task_class", ["security", "compliance", "privacy"])
def test_other_escalated_classes_route_to_the_escalated_model(task_class):
    assert opc.preflight_triage_model(task_class) == opc.PREFLIGHT_ESCALATED_MODEL


def test_class_matching_is_case_insensitive():
    assert opc.preflight_triage_model("LEGAL") == opc.PREFLIGHT_ESCALATED_MODEL
    assert opc.preflight_triage_model("  Legal (need 9)  ") == opc.PREFLIGHT_ESCALATED_MODEL


def test_the_escalated_route_is_a_hosted_frontier_vendor():
    """What actually matters for a legal/security class: not a local model.

    The literal id is deliberately NOT pinned here. It was, and when
    `fix(models): repin 12 model ids the vendors no longer serve` moved the
    route off a retired id, eight tests in this file failed on correct code —
    the suite was pinning a vendor's SKU name rather than the routing rule.
    """
    vendor = opc.PREFLIGHT_ESCALATED_MODEL.split(":", 1)[0]
    assert vendor in {"google", "openai", "anthropic", "claude", "deepseek", "xai"}
    assert not opc.PREFLIGHT_ESCALATED_MODEL.startswith("local:")


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

    Asserted by actually setting the env var and re-importing, rather than by
    restating the module's default literal — the restatement version passed for
    the wrong reason and then failed the moment the default legitimately moved.
    """
    import importlib

    monkeypatch.setenv("ORCH_PREFLIGHT_ESCALATED_MODEL", "openai:gpt-5.4-mini")
    reloaded = importlib.reload(opc)
    try:
        assert reloaded.PREFLIGHT_ESCALATED_MODEL == "openai:gpt-5.4-mini"
        assert reloaded.preflight_triage_model("legal") == "openai:gpt-5.4-mini"
    finally:
        monkeypatch.undo()
        importlib.reload(opc)


def test_the_env_var_is_orch_prefixed_so_fleet_control_can_push_it():
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "runner", "orchestration_pipeline_config.py"), encoding="utf-8").read()
    assert "ORCH_PREFLIGHT_ESCALATED_MODEL" in src
