import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import canary_triage as ct

def test_conflict_marker():
    assert ct.classify("File economic_scheduler.py line 27\n<<<<<<< HEAD\nSyntaxError") == "conflict-marker"
    assert ct.classify("error: leftover conflict marker") == "conflict-marker"

def test_missing_module():
    assert ct.classify("E   ModuleNotFoundError: No module named 'opportunity_scanner'") == "missing-module"

def test_stale_test():
    assert ct.classify("E  AssertionError: assert {..} == {..}\nLeft contains 2 more items") == "stale-test"

def test_real_regression():
    assert ct.classify("E  AssertionError: expected True but got False") == "real-regression"

def test_collection_error():
    assert ct.classify("Interrupted: 1 error during collection") == "collection-error"

def test_unknown():
    assert ct.classify("some unrelated log line") == "unknown"

def test_triage_files_tier1():
    filed = []
    r = ct.triage("<<<<<<< HEAD leftover conflict marker", enqueue_fn=lambda rec: filed.append(rec), head="deadbeefcafe")
    assert r == {"class": "conflict-marker", "filed": True}
    assert filed[0]["kind"] == "remediation" and filed[0]["priority"] == 1

def test_triage_unknown_no_file():
    filed = []
    r = ct.triage("nothing matches", enqueue_fn=lambda rec: filed.append(rec))
    assert r["filed"] is False and filed == []
