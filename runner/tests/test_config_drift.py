"""Tests for config_drift.py and realtime_config.py - pure logic, db mocked."""
import os, sys, types, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Ensure db mock exists
if "db" not in sys.modules:
    fake_db = types.ModuleType("db")
    fake_db.sql = lambda q: []
    fake_db.insert = lambda *a, **k: None
    sys.modules["db"] = fake_db

import config_drift
import realtime_config

def test_config_hash_deterministic():
    h1 = config_drift._config_hash()
    h2 = config_drift._config_hash()
    assert h1 == h2

def test_check_no_drift():
    result = config_drift.check()
    assert isinstance(result, list)
    assert len(result) == 0

def test_realtime_config_get_default():
    realtime_config._cache = {}
    realtime_config._cache_ts = 0
    val = realtime_config.get("NONEXISTENT", "fallback")
    assert val == "fallback"

def test_realtime_config_get_cached():
    import time
    realtime_config._cache = {"MY_KEY": "my_value"}
    realtime_config._cache_ts = time.time()
    assert realtime_config.get("MY_KEY") == "my_value"
