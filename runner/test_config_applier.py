#!/usr/bin/env python3
"""Tests for config_applier.py — configuration management with canary deployment."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
import config_applier


def test_safe_key_allows_orch_prefix():
    assert config_applier._is_safe_key("ORCH_MAX_PARALLEL") is True

def test_safe_key_allows_max_parallel():
    assert config_applier._is_safe_key("MAX_PARALLEL") is True

def test_safe_key_allows_deploy_prefix():
    assert config_applier._is_safe_key("DEPLOY_CANARY") is True

def test_safe_key_rejects_secret():
    assert config_applier._is_safe_key("ORCH_SECRET_KEY") is False

def test_safe_key_rejects_password():
    assert config_applier._is_safe_key("DB_PASSWORD") is False

def test_safe_key_rejects_token():
    assert config_applier._is_safe_key("API_TOKEN") is False

def test_safe_key_rejects_credential():
    assert config_applier._is_safe_key("MY_CREDENTIAL") is False

def test_safe_key_rejects_unknown_prefix():
    assert config_applier._is_safe_key("RANDOM_SETTING") is False

def test_safe_key_empty_string():
    assert config_applier._is_safe_key("") is False

def test_safe_key_none():
    assert config_applier._is_safe_key(None) is False

def test_load_state_returns_default_on_missing():
    state = config_applier._load_state()
    assert isinstance(state, dict)
    assert "applied" in state or state == {"applied": {}, "rollbacks": []}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
    print("config_applier tests complete.")
