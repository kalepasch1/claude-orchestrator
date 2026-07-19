#!/usr/bin/env python3
"""Tests for digital_twin.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import digital_twin as dt

def test_twin_decide_no_data():
    result = dt.twin_decide("nonexistent-app")
    assert result["decision"] == "pass-through"

def test_gate_no_data():
    result = dt.gate("nonexistent-app")
    # twin pass-through -> falls through to canary
    assert result["stage"] in ("twin", "canary")

def test_module_imports():
    assert hasattr(dt, 'twin_decide')
    assert hasattr(dt, 'gate')
    assert hasattr(dt, 'log_synthetic')

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as e:
                print(f"  FAIL {name}: {e}")
    print("done")
