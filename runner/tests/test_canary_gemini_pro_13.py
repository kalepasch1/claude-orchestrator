"""Canary test: approval_policy.is_auto_approvable smoke tests (gemini-pro-13)."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_is_auto_approvable_normal_card():
    """Normal cards without legal/secret/alarm flags are auto-approvable."""
    from approval_policy import is_auto_approvable
    card = {"kind": "build", "title": "Add feature X"}
    assert is_auto_approvable(card) is True


def test_is_auto_approvable_secret_card():
    """Secret cards are never auto-approvable."""
    from approval_policy import is_auto_approvable
    card = {"kind": "secret", "title": "Add API key"}
    assert is_auto_approvable(card) is False


def test_is_auto_approvable_alarm_title():
    """Cards with alarm keywords in title are not auto-approvable."""
    from approval_policy import is_auto_approvable
    card = {"kind": "build", "title": "key leak detected in prod"}
    assert is_auto_approvable(card) is False
