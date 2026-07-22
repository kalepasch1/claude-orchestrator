"""Canary test: approval_policy._text helper + ALARM_RX smoke tests (gpt-mini-25)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from approval_policy import _text, ALARM_RX


def test_text_concatenates_fields():
    card = {"title": "A", "why": "B", "detail": "C", "prebrief": "D"}
    assert _text(card) == "A B C D"


def test_text_missing_fields():
    card = {"title": "Only title"}
    result = _text(card)
    assert "Only title" in result


def test_alarm_rx_key_leak():
    assert ALARM_RX.search("key leak in staging")


def test_alarm_rx_credential_compromise():
    assert ALARM_RX.search("credential compromised alert")


def test_alarm_rx_no_match():
    assert ALARM_RX.search("normal build task") is None
