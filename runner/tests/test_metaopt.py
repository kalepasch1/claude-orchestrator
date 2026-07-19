"""Tests for metaopt.py - loop cadence tuning (pure logic, db mocked)."""
import os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub db module before importing metaopt
_real_db = sys.modules.get("db")
_mock_rows = {"queue": 0, "throughput": 0}
fake_db = types.ModuleType("db")
def _mock_sql(q):
    if "tasks" in q: return [{"n": _mock_rows["queue"]}]
    if "outcomes" in q: return [{"n": _mock_rows["throughput"]}]
    return []
fake_db.sql = _mock_sql
fake_db.insert = lambda *a, **k: None
sys.modules["db"] = fake_db

import metaopt
if _real_db is not None:
    sys.modules["db"] = _real_db
else:
    sys.modules.pop("db", None)

def test_recommend_low_queue():
    _mock_rows["queue"] = 1
    _mock_rows["throughput"] = 1
    r = metaopt.recommend_cadence()
    assert r["poll_interval_sec"] == 300.0

def test_recommend_high_queue():
    _mock_rows["queue"] = 50
    _mock_rows["throughput"] = 20
    r = metaopt.recommend_cadence()
    assert r["poll_interval_sec"] == 30.0

def test_recommend_moderate_queue():
    _mock_rows["queue"] = 10
    _mock_rows["throughput"] = 10
    r = metaopt.recommend_cadence()
    assert 30 <= r["poll_interval_sec"] <= 300

def test_queue_depth_reported():
    _mock_rows["queue"] = 7
    r = metaopt.recommend_cadence()
    assert r["queue_depth"] == 7
