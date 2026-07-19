"""Tests for scoreboard_metrics.py - pure logic, no db."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scoreboard_metrics import compute_metrics

_ROWS = [
    {"model": "claude", "project": "alpha", "tests_passed": True,
     "integrated": True, "usd": 0.10, "input_tokens": 100,
     "output_tokens": 50, "wall_ms": 60000, "review_failures": 0},
    {"model": "claude", "project": "alpha", "tests_passed": True,
     "integrated": False, "usd": 0.05, "input_tokens": 80,
     "output_tokens": 40, "wall_ms": 45000, "review_failures": 1},
    {"model": "gemini", "project": "beta", "tests_passed": False,
     "integrated": False, "usd": 0.02, "input_tokens": 50,
     "output_tokens": 20, "wall_ms": 30000, "review_failures": 0},
]

def test_overall_attempts():
    m = compute_metrics(_ROWS)
    assert m["overall"]["attempts"] == 3

def test_overall_tests_passed():
    m = compute_metrics(_ROWS)
    assert m["overall"]["tests_passed"] == 2

def test_overall_merged():
    m = compute_metrics(_ROWS)
    assert m["overall"]["merged"] == 1

def test_by_model_keys():
    m = compute_metrics(_ROWS)
    assert "claude" in m["by_model"]
    assert "gemini" in m["by_model"]

def test_by_project_keys():
    m = compute_metrics(_ROWS)
    assert "alpha" in m["by_project"]
    assert "beta" in m["by_project"]

def test_lead_times_empty():
    m = compute_metrics(_ROWS)
    assert m["lead_times"]["median_hours"] is None

def test_lead_times_with_data():
    rows = [
        {"integrated": True, "created_at": "2025-01-01T00:00:00Z",
         "merged_at": "2025-01-01T02:00:00Z", "tests_passed": True,
         "usd": 0, "input_tokens": 0, "output_tokens": 0, "wall_ms": 0, "review_failures": 0},
    ]
    m = compute_metrics(rows)
    assert m["lead_times"]["median_hours"] == 2.0

def test_deploy_rate():
    m = compute_metrics(_ROWS)
    assert m["deploy_rate"] is not None
    assert m["deploy_rate"] >= 0

def test_knowledge_reuse_none():
    m = compute_metrics(_ROWS)
    assert m["knowledge_reuse"] == 0.0

def test_knowledge_reuse_present():
    rows = [{"reused_patch": True, "tests_passed": True, "integrated": True,
             "usd": 0, "input_tokens": 0, "output_tokens": 0, "wall_ms": 0, "review_failures": 0}]
    m = compute_metrics(rows)
    assert m["knowledge_reuse"] == 1.0

def test_empty_input():
    m = compute_metrics([])
    assert m["overall"]["attempts"] == 0
    assert m["deploy_rate"] is None
