"""receipt_builder: a receipt is what makes an autonomous action reversible."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "runner"))

from receipt_builder import (  # noqa: E402
    IRREVERSIBLE_ACTIONS,
    build_receipt,
    build_receipt_dict,
    build_undo_plan,
)


def test_a_normal_action_is_undoable_when_a_method_is_given():
    receipt = build_receipt("config_changed", "raised MAX_PARALLEL",
                            cost_usd=0.10, counterfactual_cost_usd=5.0,
                            undo_method="restore prior fleet_config value")

    assert receipt.undo.available is True
    assert receipt.undo.method == "restore prior fleet_config value"


def test_an_irreversible_action_can_never_be_marked_undoable():
    """The allowlist wins over the caller: the cost of wrongly promising
    reversibility is borne by the operator who trusted it."""
    for action in sorted(IRREVERSIBLE_ACTIONS):
        plan = build_undo_plan(action, method="pretend rollback", available=True)
        assert plan.available is False
        assert action in plan.reason


def test_undo_fails_closed_without_a_method():
    assert build_undo_plan("config_changed").available is False
    assert build_undo_plan("config_changed", available=True).available is False
    assert build_undo_plan("config_changed", method="  ").available is False


def test_undo_unavailable_always_carries_a_reason():
    for plan in (build_undo_plan("money_moved"),
                 build_undo_plan("config_changed"),
                 build_undo_plan("config_changed", available=False)):
        assert plan.available is False
        assert plan.reason, "an operator must be told WHY it cannot be undone"


def test_a_missing_counterfactual_is_stated_not_silently_zero():
    """An unstated counterfactual reads as 'acting saved nothing' — a claim,
    not an absence."""
    receipt = build_receipt("config_changed", "raised a limit", cost_usd=1.0)

    assert receipt.counterfactual_cost_usd == 0.0
    assert "counterfactual cost not supplied" in receipt.explanation


def test_net_benefit_is_the_counterfactual_minus_the_cost():
    receipt = build_receipt("config_changed", "x", cost_usd=2.5,
                            counterfactual_cost_usd=10.0, undo_method="revert")

    assert receipt.net_benefit_usd == 7.5


def test_net_benefit_is_negative_when_acting_cost_more():
    receipt = build_receipt("config_changed", "x", cost_usd=10.0,
                            counterfactual_cost_usd=2.0, undo_method="revert")

    assert receipt.net_benefit_usd == -8.0


@pytest.mark.parametrize("bad", [None, "lots", float("nan"), object()])
def test_malformed_costs_become_zero_rather_than_raising(bad):
    receipt = build_receipt("config_changed", "x", cost_usd=bad,
                            counterfactual_cost_usd=bad, undo_method="revert")

    assert receipt.cost_usd == 0.0
    assert receipt.counterfactual_cost_usd == 0.0


def test_negative_costs_are_clamped_to_zero():
    receipt = build_receipt("config_changed", "x", cost_usd=-5,
                            counterfactual_cost_usd=-9, undo_method="revert")

    assert receipt.cost_usd == 0.0
    assert receipt.counterfactual_cost_usd == 0.0


def test_a_receipt_always_has_an_action_and_an_explanation():
    """A receipt that fails to render is an action with no audit trail."""
    receipt = build_receipt(None)

    assert receipt.action == "unknown"
    assert receipt.explanation
    assert receipt.actor == "unknown"


def test_build_receipt_never_raises_on_anything():
    for bad in (None, "", 0, [], {}, object()):
        assert build_receipt(bad) is not None


def test_dict_form_carries_every_field_the_card_renders():
    data = build_receipt_dict("config_changed", "raised a limit", cost_usd=1.0,
                              counterfactual_cost_usd=4.0,
                              undo_method="revert", actor="governor",
                              now="2026-08-06T00:00:00Z")

    for key in ("action", "explanation", "cost_usd", "counterfactual_cost_usd",
                "undo", "net_benefit_usd", "actor", "at"):
        assert key in data
    assert data["undo"] == {"available": True, "method": "revert", "reason": ""}
    assert data["net_benefit_usd"] == 3.0


def test_metadata_is_copied_not_aliased():
    source = {"k": "v"}
    receipt = build_receipt("config_changed", "x", metadata=source)
    source["k"] = "mutated"

    assert receipt.metadata["k"] == "v"
