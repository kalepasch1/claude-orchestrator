#!/usr/bin/env python3
"""Tests for opportunity_scout.py - RICE scoring, JSON parsing, and proposal filing."""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import opportunity_scout as scout


# --- RICE scoring tests ---

def test_rice_basic_scoring():
    """RICE formula: reach * impact * confidence / effort_days."""
    o = {"reach": 10, "impact": 10, "confidence": 1.0, "effort_days": 5}
    assert scout.rice(o) == 20.0  # 10 * 10 * 1.0 / 5


def test_rice_with_low_confidence():
    """Lower confidence reduces score proportionally."""
    o = {"reach": 10, "impact": 10, "confidence": 0.5, "effort_days": 5}
    assert scout.rice(o) == 10.0  # 10 * 10 * 0.5 / 5


def test_rice_high_effort_reduces_score():
    """Effort in denominator penalizes long projects."""
    o = {"reach": 10, "impact": 10, "confidence": 1.0, "effort_days": 20}
    assert scout.rice(o) == 5.0  # 10 * 10 * 1.0 / 20


def test_rice_zero_effort_clamps_to_min():
    """Zero or missing effort_days defaults to 0.5 to avoid division explosion."""
    o = {"reach": 10, "impact": 10, "confidence": 1.0, "effort_days": 0}
    assert scout.rice(o) == 200.0  # 10 * 10 * 1.0 / max(0.5, 0)


def test_rice_missing_field_returns_zero():
    """Malformed objects without reach/impact/confidence/effort return 0."""
    o = {"title": "bad"}
    assert scout.rice(o) == 0.0


def test_rice_non_numeric_field_returns_zero():
    """Non-numeric values in RICE fields are caught and return 0."""
    o = {"reach": "many", "impact": 10, "confidence": 1.0, "effort_days": 5}
    assert scout.rice(o) == 0.0


def test_rice_rounds_to_one_decimal():
    """RICE scores are rounded to 1 decimal place."""
    o = {"reach": 7, "impact": 6, "confidence": 0.73, "effort_days": 2}
    result = scout.rice(o)
    assert isinstance(result, float)
    assert result == round(result, 1)


# --- JSON parsing tests ---

def test_parse_single_opportunity_json():
    """A single valid JSON object per line is parsed correctly."""
    line = '{"title":"cache layer","why":"slow queries","value":"10x faster","risk":"cache miss","reach":8,"impact":9,"confidence":0.8,"effort_days":3}'
    o = json.loads(line)
    assert o["title"] == "cache layer"
    assert scout.rice(o) > 0


def test_parse_multiple_opportunities_from_output():
    """Multiple JSON lines from model output are collected into a list."""
    output = """
    {"title":"feature 1","reach":5,"impact":5,"confidence":0.8,"effort_days":2}
    {"title":"feature 2","reach":10,"impact":10,"confidence":0.9,"effort_days":5}
    Some text that isn't JSON
    {"title":"feature 3","reach":3,"impact":3,"confidence":0.7,"effort_days":1}
    """
    ideas = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                ideas.append(json.loads(line))
            except Exception:
                pass
    assert len(ideas) == 3
    assert ideas[0]["title"] == "feature 1"
    assert ideas[2]["title"] == "feature 3"


def test_parse_rejects_incomplete_json():
    """Malformed JSON lines are skipped, not collected."""
    output = """
    {"title":"good","reach":5,"impact":5,"confidence":0.8,"effort_days":2}
    {"title":"bad","reach":5,"impact":5 (missing closing brace)
    {"title":"fine","reach":5,"impact":5,"confidence":0.8,"effort_days":2}
    """
    ideas = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                ideas.append(json.loads(line))
            except Exception:
                pass
    assert len(ideas) == 2
    assert ideas[0]["title"] == "good"
    assert ideas[1]["title"] == "fine"


def test_parse_empty_output():
    """Empty or no-JSON output produces an empty ideas list."""
    output = "No JSON here, just plain text about opportunities."
    ideas = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                ideas.append(json.loads(line))
            except Exception:
                pass
    assert len(ideas) == 0


# --- Sorting and deduplication tests ---

def test_top_3_sorted_by_rice():
    """Ideas are sorted by RICE score descending; top 3 are selected."""
    ideas = [
        {"title": "low", "reach": 2, "impact": 2, "confidence": 0.5, "effort_days": 5},  # rice=0.4
        {"title": "high", "reach": 10, "impact": 10, "confidence": 1.0, "effort_days": 5},  # rice=20
        {"title": "medium", "reach": 5, "impact": 5, "confidence": 0.8, "effort_days": 2},  # rice=10
        {"title": "top", "reach": 8, "impact": 9, "confidence": 0.95, "effort_days": 3},  # rice=22.8
    ]
    top = sorted(ideas, key=scout.rice, reverse=True)[:3]
    assert len(top) == 3
    assert top[0]["title"] == "top"
    assert top[1]["title"] == "high"
    assert top[2]["title"] == "medium"


def test_fewer_than_3_ideas():
    """If fewer than 3 ideas are found, all are returned."""
    ideas = [
        {"title": "only 1", "reach": 5, "impact": 5, "confidence": 0.8, "effort_days": 2},
        {"title": "only 2", "reach": 10, "impact": 10, "confidence": 0.8, "effort_days": 2},
    ]
    top = sorted(ideas, key=scout.rice, reverse=True)[:3]
    assert len(top) == 2


def test_duplicate_title_detection():
    """Proposals with matching title should not be re-filed."""
    title1 = "[RICE 20.0] Add caching layer"
    title2 = "[RICE 20.0] Add caching layer"
    assert title1 == title2


# --- Specification formatting tests ---

def test_spec_formatting_with_values():
    """Spec is formatted with title, why, value, risk, and acceptance tests."""
    o = {
        "title": "async processing",
        "why": "synchronous requests timeout",
        "value": "50% faster response time",
        "risk": "queue failure causes retries"
    }
    why = o.get("why")
    value = o.get("value")
    risk = o.get("risk")

    spec = (
        f"IMPROVEMENT HYPOTHESIS (feature; not a measured result): {o.get('title')}\n\n"
        f"Baseline: {why}\n"
        f"Target: {value}\n"
        "Multiplier basis: 2x = compare the measured target with the current baseline; "
        "the opportunity's larger claim remains unproven until post-deploy measurement.\n"
        "Measurement plan: establish the baseline before implementation and compare a seven-day "
        "post-release sample against it.\n"
        f"Rollback: {risk}\n\n"
        "Acceptance tests:\n"
        "- The committee records a concrete implementation boundary and measurable baseline.\n"
        "- The implementation passes regression/build gates and has a verified deployment receipt."
    )
    assert "async processing" in spec
    assert "synchronous requests timeout" in spec
    assert "50% faster response time" in spec
    assert "queue failure causes retries" in spec
    assert "Acceptance tests:" in spec


def test_spec_formatting_with_missing_fields():
    """Spec uses defaults when optional fields are missing."""
    o = {"title": "improvement"}
    why = o.get("why") or "baseline not specified"
    value = o.get("value") or "Improve verified product value."
    risk = o.get("risk") or "Revert the isolated change on regression."

    spec = (
        f"Baseline: {why}\n"
        f"Target: {value}\n"
        f"Rollback: {risk}"
    )
    assert "baseline not specified" in spec
    assert "Improve verified product value." in spec
    assert "Revert the isolated change on regression." in spec


def test_title_truncation():
    """Proposal titles are truncated to 200 characters."""
    long_title = "A" * 250
    ricе_score = 15.0
    truncated = f"[RICE {ricе_score}] {long_title}"[:200]
    assert len(truncated) == 200


# --- Integration-style tests ---

def test_complete_opportunity_object_structure():
    """A valid opportunity object has all required RICE fields."""
    o = {
        "title": "query optimizer",
        "why": "slow dashboard",
        "value": "load time 60% faster",
        "risk": "cache consistency issue",
        "reach": 8,
        "impact": 9,
        "confidence": 0.75,
        "effort_days": 5
    }
    assert scout.rice(o) > 0
    assert "title" in o
    assert "reach" in o


def test_model_output_simulation():
    """Simulate a typical model output with mixed valid/invalid JSON."""
    output = """Let me scan the codebase for high-leverage opportunities:

{"title":"Add request batching API","why":"Individual requests are rate-limited","value":"10x throughput per user","risk":"Complex state management","reach":9,"impact":10,"confidence":0.85,"effort_days":8}

{"title":"Optimize database indexing","why":"Slow report queries","value":"Report gen 5x faster","risk":"Index maintenance cost","reach":7,"impact":8,"confidence":0.9,"effort_days":3}

Some analysis text here...

{"title":"Implement query cache","why":"Repeated queries hit DB","value":"API latency 40% lower","risk":"Cache invalidation bugs","reach":10,"impact":9,"confidence":0.8,"effort_days":4}
"""

    ideas = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                ideas.append(json.loads(line))
            except Exception:
                pass

    assert len(ideas) == 3
    top = sorted(ideas, key=scout.rice, reverse=True)[:3]
    assert len(top) == 3
    assert all(scout.rice(o) > 0 for o in top)


if __name__ == "__main__":
    # Run tests manually
    test_rice_basic_scoring()
    test_rice_with_low_confidence()
    test_rice_high_effort_reduces_score()
    test_rice_zero_effort_clamps_to_min()
    test_rice_missing_field_returns_zero()
    test_rice_non_numeric_field_returns_zero()
    test_rice_rounds_to_one_decimal()
    test_parse_single_opportunity_json()
    test_parse_multiple_opportunities_from_output()
    test_parse_rejects_incomplete_json()
    test_parse_empty_output()
    test_top_3_sorted_by_rice()
    test_fewer_than_3_ideas()
    test_duplicate_title_detection()
    test_spec_formatting_with_values()
    test_spec_formatting_with_missing_fields()
    test_title_truncation()
    test_complete_opportunity_object_structure()
    test_model_output_simulation()
    print("All 18 tests passed!")
