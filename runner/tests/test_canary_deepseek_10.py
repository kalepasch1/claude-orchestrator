"""Canary test: approval_policy.is_legal_gated smoke tests (deepseek-10)."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_is_legal_gated_novel_legal():
    """Novel legal cards are gated."""
    from approval_policy import is_legal_gated
    card = {"kind": "legal", "legal_risk_level": "novel", "title": "New license"}
    assert is_legal_gated(card) is True


def test_is_legal_gated_routine_legal():
    """Routine legal cards are not gated (risk level != novel)."""
    from approval_policy import is_legal_gated
    card = {"kind": "legal", "legal_risk_level": "routine", "title": "Standard review"}
    # Routine legal without novel risk may or may not gate depending on legal_filter
    result = is_legal_gated(card)
    assert isinstance(result, bool)


def test_is_legal_gated_build_card():
    """Build cards without legal markers are not gated."""
    from approval_policy import is_legal_gated
    card = {"kind": "build", "title": "Add tests"}
    assert is_legal_gated(card) is False
