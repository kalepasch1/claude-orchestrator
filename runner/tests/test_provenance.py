"""
test_provenance.py - verify provenance module including the merge provenance ledger.
Uses an in-memory mock db to avoid live Supabase.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock db module before importing provenance
import types
_mock_db_store = {}
_mock_db_id = [0]

def _reset_mock():
    _mock_db_store.clear()
    _mock_db_id[0] = 0

def _mock_insert(table, row):
    _mock_db_id[0] += 1
    row = dict(row)
    row["id"] = str(_mock_db_id[0])
    _mock_db_store.setdefault(table, []).append(row)
    return row

def _mock_select(table, params):
    rows = _mock_db_store.get(table, [])
    result = []
    for r in rows:
        match = True
        for k, v in params.items():
            if k in ("select", "order", "limit"):
                continue
            if k in r and v.startswith("eq.") and str(r[k]) != v[3:]:
                match = False
        if match:
            result.append(r)
    return result

def _mock_update(table, match, updates):
    for r in _mock_db_store.get(table, []):
        if all(str(r.get(k)) == str(v) for k, v in match.items()):
            r.update(updates)
            return r

def _mock_upsert(table, row):
    key = row.get("key")
    for r in _mock_db_store.get(table, []):
        if r.get("key") == key:
            r["value"] = row["value"]
            return r
    return _mock_insert(table, row)

# Inject mock db
mock_db = types.ModuleType("db")
mock_db.insert = _mock_insert
mock_db.select = _mock_select
mock_db.update = _mock_update
mock_db.upsert = _mock_upsert
sys.modules["db"] = mock_db

import provenance


class TestProvenance(unittest.TestCase):
    def setUp(self):
        _reset_mock()

    def test_record_and_query(self):
        provenance.record("cap1", "proj-a", "derived", consent=True, residency="US")
        rows = provenance.for_capability("cap1")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["consent"])

    def test_consent_ok_passes(self):
        provenance.record("cap2", "proj-a", "copy", consent=True, residency="US")
        ok, reason = provenance.consent_ok("cap2", "US")
        self.assertTrue(ok)

    def test_consent_ok_fails_no_consent(self):
        provenance.record("cap3", "proj-a", "copy", consent=False)
        ok, reason = provenance.consent_ok("cap3")
        self.assertFalse(ok)
        self.assertIn("lacks consent", reason)

    def test_revoke(self):
        provenance.record("cap4", "proj-a", "copy", consent=True)
        _mock_insert("capabilities", {"id": "cap4", "status": "active"})
        provenance.revoke("cap4")
        rows = provenance.for_capability("cap4")
        self.assertFalse(rows[0]["consent"])


class TestMergeProvenanceLedger(unittest.TestCase):
    def setUp(self):
        _reset_mock()

    def test_record_merge(self):
        provenance.record("cap-a", "proj", "derived", consent=True)
        provenance.record("cap-b", "proj", "derived", consent=True)
        entry = provenance.record_merge("merge-1", ["cap-a", "cap-b"], author="bot")
        self.assertEqual(entry["merge_id"], "merge-1")
        self.assertEqual(len(entry["capability_ids"]), 2)
        self.assertTrue(entry["consent_snapshot"]["cap-a"]["ok"])

    def test_merge_history(self):
        provenance.record("cap-x", "proj", "copy", consent=True)
        provenance.record_merge("m1", ["cap-x"])
        provenance.record_merge("m2", ["cap-x"])
        history = provenance.merge_history()
        self.assertEqual(len(history), 2)

    def test_merge_history_filter_by_id(self):
        provenance.record_merge("m1", ["a"])
        provenance.record_merge("m2", ["b"])
        history = provenance.merge_history(merge_id="m1")
        self.assertEqual(len(history), 1)

    def test_merge_history_filter_by_capability(self):
        provenance.record_merge("m1", ["a", "b"])
        provenance.record_merge("m2", ["c"])
        history = provenance.merge_history(capability_id="a")
        self.assertEqual(len(history), 1)

    def test_audit_merge_ok(self):
        provenance.record("cap-ok", "proj", "copy", consent=True)
        provenance.record_merge("audit-1", ["cap-ok"])
        ok, violations = provenance.audit_merge("audit-1")
        self.assertTrue(ok)
        self.assertEqual(violations, [])

    def test_audit_merge_violations(self):
        provenance.record("cap-bad", "proj", "copy", consent=False)
        provenance.record_merge("audit-2", ["cap-bad"])
        ok, violations = provenance.audit_merge("audit-2")
        self.assertFalse(ok)
        self.assertEqual(len(violations), 1)

    def test_audit_merge_not_found(self):
        ok, violations = provenance.audit_merge("nonexistent")
        self.assertFalse(ok)

    def test_rollback_merge(self):
        provenance.record("cap-r", "proj", "copy", consent=True)
        _mock_insert("capabilities", {"id": "cap-r", "status": "active"})
        provenance.record_merge("rollback-1", ["cap-r"])
        result = provenance.rollback_merge("rollback-1")
        self.assertIn("cap-r", result["revoked"])


if __name__ == "__main__":
    unittest.main()
