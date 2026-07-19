"""Canary test: approval_policy.FALLBACK_ALTERNATIVES structure (deepseek-9)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from approval_policy import FALLBACK_ALTERNATIVES


def test_fallback_has_three_options():
    assert len(FALLBACK_ALTERNATIVES) == 3


def test_each_fallback_has_required_keys():
    for alt in FALLBACK_ALTERNATIVES:
        assert "label" in alt
        assert "description" in alt
        assert "risk" in alt
        assert "reversible" in alt


def test_exactly_one_recommended():
    recs = [a for a in FALLBACK_ALTERNATIVES if a.get("recommended")]
    assert len(recs) == 1


def test_recommended_is_guardrails():
    rec = [a for a in FALLBACK_ALTERNATIVES if a.get("recommended")][0]
    assert "guardrails" in rec["label"].lower()
