#!/usr/bin/env python3
"""Tests for contract_drift.py pure functions."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from contract_drift import detect_divergence, build_plan


def test_detect_divergence_no_drift():
    golden = {"version": "1.0", "schema": "users", "fields": ["id", "name"]}
    observed = {"version": "1.0", "schema": "users", "fields": ["id", "name"]}
    assert detect_divergence(golden, observed) == []


def test_detect_divergence_with_drift():
    golden = {"version": "1.0", "schema": "users"}
    observed = {"version": "1.1", "schema": "users"}
    result = detect_divergence(golden, observed)
    assert len(result) == 1
    assert result[0]["field"] == "version"
    assert result[0]["expected"] == "1.0"
    assert result[0]["observed"] == "1.1"


def test_detect_divergence_missing_field():
    golden = {"version": "1.0", "schema": "users"}
    observed = {"version": "1.0"}
    result = detect_divergence(golden, observed)
    assert len(result) == 1
    assert result[0]["field"] == "schema"
    assert result[0]["observed"] is None


def test_detect_divergence_json_strings():
    golden = '{"a": 1}'
    observed = '{"a": 2}'
    result = detect_divergence(golden, observed)
    assert len(result) == 1
    assert result[0]["field"] == "a"


def test_detect_divergence_empty():
    assert detect_divergence({}, {}) == []
    assert detect_divergence(None, None) == []
    assert detect_divergence("bad", "bad") == []


def test_build_plan_with_golden():
    caps = [
        {"slug": "cap-a", "golden_ref": "/path/to/golden.json"},
        {"slug": "cap-b", "golden_ref": None},  # no golden -> skip
    ]
    consumers = {
        "cap-a": [
            {"project_id": "proj-1", "project_name": "Project One"},
            {"project_id": "proj-2", "project_name": "Project Two"},
        ],
    }
    plan = build_plan(caps, consumers)
    assert len(plan) == 2
    assert plan[0]["cap_slug"] == "cap-a"
    assert plan[0]["project_id"] == "proj-1"
    assert plan[1]["project_id"] == "proj-2"


def test_build_plan_no_consumers():
    caps = [{"slug": "cap-a", "golden_ref": "/path"}]
    plan = build_plan(caps, {})
    assert plan == []


def test_build_plan_no_golden():
    caps = [{"slug": "cap-a", "golden_ref": None}]
    plan = build_plan(caps, {"cap-a": [{"project_id": "p1", "project_name": "P1"}]})
    assert plan == []


if __name__ == "__main__":
    test_detect_divergence_no_drift()
    test_detect_divergence_with_drift()
    test_detect_divergence_missing_field()
    test_detect_divergence_json_strings()
    test_detect_divergence_empty()
    test_build_plan_with_golden()
    test_build_plan_no_consumers()
    test_build_plan_no_golden()
    print("All contract_drift tests passed")
