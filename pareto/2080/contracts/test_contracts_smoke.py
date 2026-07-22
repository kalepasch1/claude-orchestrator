"""Smoke test: all autonomy contracts import without error."""
import sys, os, importlib

# 2080 is not a valid Python identifier, so use importlib
_contracts_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _contracts_dir)

import autonomy as a


def test_authority_budget():
    assert a.AuthorityBudget is not None
    b = a.AuthorityBudget(tier=a.AuthorityTier.CAPPED, cap_usd=500.0)
    assert b.cap_usd == 500.0


def test_receipt():
    assert a.Receipt is not None
    r = a.Receipt(explanation="test", action="buy")
    assert r.explanation == "test"


def test_life_state_machine():
    assert a.LifeStateMachine is not None
    lsm = a.LifeStateMachine(goal_id="g1")
    assert lsm.current_state == "idle"


def test_all_types_importable():
    """Verify all key types are accessible."""
    for name in ['AuthorityBudget', 'Receipt', 'LifeStateMachine',
                 'GoalCompileResult', 'ConfidenceBand', 'RegimeEvent',
                 'HouseholdPassport', 'NegotiationOutcome', 'AuditBundle',
                 'ComplianceBinder', 'DeviationInterrupt', 'ReplanReceipt']:
        assert hasattr(a, name), f"Missing: {name}"
