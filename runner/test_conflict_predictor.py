#!/usr/bin/env python3
"""Tests for conflict_predictor.py — merge conflict detection and prediction."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
import conflict_predictor


def test_extract_files_finds_py():
    files = conflict_predictor._extract_files("Edit runner/db.py and runner/log.py")
    assert "runner/db.py" in files
    assert "runner/log.py" in files

def test_extract_files_finds_ts():
    files = conflict_predictor._extract_files("Fix server/api/index.ts")
    assert "server/api/index.ts" in files

def test_extract_files_empty_input():
    assert conflict_predictor._extract_files("") == set()

def test_extract_files_none_input():
    assert conflict_predictor._extract_files(None) == set()

def test_jaccard_identical():
    assert conflict_predictor._jaccard({"a", "b"}, {"a", "b"}) == 1.0

def test_jaccard_disjoint():
    assert conflict_predictor._jaccard({"a"}, {"b"}) == 0.0

def test_jaccard_partial():
    score = conflict_predictor._jaccard({"a", "b", "c"}, {"b", "c", "d"})
    assert 0.4 < score < 0.6  # 2/4 = 0.5

def test_jaccard_empty():
    assert conflict_predictor._jaccard(set(), set()) == 0.0
    assert conflict_predictor._jaccard({"a"}, set()) == 0.0

def test_get_prompt_dict():
    assert conflict_predictor._get_prompt({"prompt": "hello"}) == "hello"

def test_get_prompt_none():
    assert conflict_predictor._get_prompt(None) == ""

def test_get_prompt_empty_dict():
    assert conflict_predictor._get_prompt({}) == ""

def test_check_conflicts_disabled():
    orig = conflict_predictor._ENABLED
    conflict_predictor._ENABLED = False
    result = conflict_predictor.check_conflicts({"prompt": "test"})
    conflict_predictor._ENABLED = orig
    assert result["action"] == "proceed"
    assert "disabled" in result["reason"]

def test_check_conflicts_no_files():
    result = conflict_predictor.check_conflicts({"prompt": "no file paths here"})
    assert result["action"] == "proceed"

def test_stats_returns_dict():
    s = conflict_predictor.stats()
    assert isinstance(s, dict)
    assert "conflicts_detected" in s


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
    print("conflict_predictor tests complete.")
