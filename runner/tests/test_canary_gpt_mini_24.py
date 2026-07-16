"""Canary test: anomaly._rate helper smoke tests (gpt-mini-24)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anomaly import _rate


def test_rate_all_match():
    rows = [{"x": True}] * 5
    assert _rate(rows, lambda r: r.get("x")) == 1.0


def test_rate_none_match():
    rows = [{"x": False}] * 5
    assert _rate(rows, lambda r: r.get("x")) == 0.0


def test_rate_partial():
    rows = [{"x": True}, {"x": False}, {"x": True}, {"x": False}]
    assert _rate(rows, lambda r: r.get("x")) == 0.5


def test_rate_empty():
    assert _rate([], lambda r: True) == 0.0
