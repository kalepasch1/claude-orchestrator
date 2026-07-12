#!/usr/bin/env python3
"""Tests for premerge_redteam.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import premerge_redteam as rt

def test_empty_diff():
    result = rt.redteam("")
    assert result["verdict"] == "pass"
    assert result["summary"] == "empty diff"

def test_none_diff():
    result = rt.redteam(None)
    assert result["verdict"] == "pass"

def test_gate_empty():
    result = rt.gate("")
    assert result["allowed"] is True

def test_module_structure():
    assert hasattr(rt, 'redteam')
    assert hasattr(rt, 'gate')
    assert hasattr(rt, 'REDTEAM_PROMPT')
    assert "injection" in rt.REDTEAM_PROMPT.lower()

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as e:
                print(f"  FAIL {name}: {e}")
    print("done")
