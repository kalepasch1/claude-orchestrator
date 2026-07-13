#!/usr/bin/env python3
"""Tests for proactive_error_resolver.py — error pattern detection and auto-fix."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
import proactive_error_resolver as per


def test_fixable_patterns_match_stale_branch():
    for regex, name, _ in per._FIXABLE:
        if name == "stale_branch":
            assert regex.search("branch is missing or deleted")
            assert regex.search("ref no longer exists")
            break
    else:
        raise AssertionError("stale_branch pattern not found")

def test_fixable_patterns_match_conflict():
    for regex, name, _ in per._FIXABLE:
        if name == "conflict":
            assert regex.search("merge conflict in file.py")
            assert regex.search("cannot rebase onto main")
            break
    else:
        raise AssertionError("conflict pattern not found")

def test_fixable_patterns_match_rate_limit():
    for regex, name, _ in per._FIXABLE:
        if name == "rate_limit":
            assert regex.search("429 Too Many Requests")
            assert regex.search("rate limit exceeded")
            break
    else:
        raise AssertionError("rate_limit pattern not found")

def test_fixable_patterns_match_timeout():
    for regex, name, _ in per._FIXABLE:
        if name == "timeout":
            assert regex.search("operation timed out")
            assert regex.search("deadline exceeded")
            break
    else:
        raise AssertionError("timeout pattern not found")

def test_fixable_patterns_match_missing_tool():
    for regex, name, _ in per._FIXABLE:
        if name == "missing_tool":
            assert regex.search("npm: command not found")
            assert regex.search("yarn not found in PATH")
            break
    else:
        raise AssertionError("missing_tool pattern not found")

def test_detect_patterns_returns_dict():
    result = per.detect_patterns()
    assert isinstance(result, dict)

def test_env_config_defaults():
    assert per.PATTERN_WINDOW_H > 0
    assert per.ALERT_THRESHOLD > 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
    print("proactive_error_resolver tests complete.")
