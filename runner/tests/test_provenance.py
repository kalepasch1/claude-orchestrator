"""
test_provenance.py - provenance ledger: lineage, consent gating, revocation, and the
merge-provenance ledger built on top of them.

WHY THIS FILE LOOKS THE WAY IT DOES
-----------------------------------
It used to install a fake `db` module into sys.modules, `import provenance` while that
fake was in place, and then put the real `db` back:

    sys.modules["db"] = mock_db
    import provenance
    sys.modules["db"] = _real_db

That only works when this file is the first thing in the session to import provenance.
It is not: prompt_assembler -> capability -> provenance is a production import chain, and
several earlier test modules pull it in. When provenance is already in sys.modules,
`import provenance` is a no-op returning the module that bound the REAL db at its own
import time, the fake is never consulted, and all eleven db-touching tests here died with
"set SUPABASE_URL and SUPABASE_SERVICE_KEY" -- passing alone, failing in-suite.

The fix is the same one the zombie-reaper suites landed on: patch the OBJECT the code
under test actually calls (`provenance.db`) rather than a name in sys.modules, and leave
sys.modules alone entirely.

REACHABILITY. `record`, `for_capability`, `consent_ok` and `revoke` are live: capability.py
imports this module at module scope and calls record() from publish() and consent_ok() from
instantiate(). The merge-ledger half (record_merge / merge_history / audit_merge /
rollback_merge) has no caller anywhere in the repo -- it is exercised here only.
"""
import os
import sys
import unittest
from unittest.mock import patch

# runner/ appended, never inserted at position 0: at sys.path[0] the module file
# runner/runner.py shadows the runner/ package for the rest of the session (the repo-root
# conftest.py documents this at length).
_RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER_DIR not in sys.path:
    sys.path.append(_RUNNER_DIR)

import provenance  # noqa: E402


class FakeDB:
    """An in-memory stand-in for db.py's PostgREST helpers.

    Only the three entry points provenance uses are implemented, with the PostgREST
    filter syntax the module actually emits (`{"col": "eq.<value>"}`); `select`, `order`
    and `limit` are query modifiers, not filters, and are ignored.
    """

    def __init__(self):
        self.rows = {}
        self._next_id = 0

    def insert(self, table, row):
        self._next_id += 1
        stored = dict(row)
        stored.setdefault("id", str(self._next_id))
        self.rows.setdefault(table, []).append(stored)
        return stored

    def select(self, table, params):
        out = []
        for row in self.rows.get(table, []):
            for key, value in params.items():
                if key in ("select", "order", "limit"):
                    continue
                if not isinstance(value, str) or not value.startswith("eq."):
                    continue
                if str(row.get(key)) != value[3:]:
                    break
            else:
                out.append(row)
        return out

    def update(self, table, match, updates):
        hit = None
        for row in self.rows.get(table, []):
            if all(str(row.get(k)) == str(v) for k, v in match.items()):
                row.update(updates)
                hit = hit or row
        return hit


class ProvenanceTestCase(unittest.TestCase):
    """Binds a fresh FakeDB onto provenance.db for the duration of each test."""

    def setUp(self):
        self.db = FakeDB()
        patcher = patch.object(provenance, "db", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestProvenance(ProvenanceTestCase):
    def test_record_and_query(self):
        provenance.record("cap1", "proj-a", "derived", consent=True, residency="US")
        rows = provenance.for_capability("cap1")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["consent"])
        self.assertEqual(rows[0]["source_project"], "proj-a")
        self.assertEqual(rows[0]["derivation"], "derived")
        self.assertEqual(rows[0]["data_residency"], "US")

    def test_for_capability_filters_by_capability_id(self):
        provenance.record("cap-mine", "proj-a", "copy", consent=True)
        provenance.record("cap-other", "proj-b", "copy", consent=True)
        rows = provenance.for_capability("cap-mine")
        self.assertEqual([r["capability_id"] for r in rows], ["cap-mine"])

    def test_consent_ok_passes(self):
        provenance.record("cap2", "proj-a", "copy", consent=True, residency="US")
        ok, reason = provenance.consent_ok("cap2", "US")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_consent_ok_fails_no_consent(self):
        provenance.record("cap3", "proj-a", "copy", consent=False)
        ok, reason = provenance.consent_ok("cap3")
        self.assertFalse(ok)
        self.assertIn("lacks consent", reason)

    def test_consent_ok_fails_with_no_provenance_at_all(self):
        """Absent lineage is a denial, not a pass: an un-recorded capability cannot be
        proved compliant, and instantiate() is gated on this answer."""
        ok, reason = provenance.consent_ok("never-recorded")
        self.assertFalse(ok)
        self.assertIn("no provenance", reason)

    def test_consent_ok_requires_every_source_to_consent(self):
        """A capability derived from several apps is only usable if ALL of them consented."""
        provenance.record("cap-multi", "proj-a", "derived", consent=True)
        provenance.record("cap-multi", "proj-b", "derived", consent=False)
        ok, reason = provenance.consent_ok("cap-multi")
        self.assertFalse(ok)
        self.assertIn("lacks consent", reason)

    def test_consent_ok_blocks_on_residency_mismatch(self):
        provenance.record("cap-eu", "proj-a", "copy", consent=True, residency="EU")
        ok, reason = provenance.consent_ok("cap-eu", "US")
        self.assertFalse(ok)
        self.assertIn("residency mismatch", reason)

    def test_residency_is_only_checked_when_a_target_is_given(self):
        """No target residency means no residency constraint to violate."""
        provenance.record("cap-eu2", "proj-a", "copy", consent=True, residency="EU")
        ok, _ = provenance.consent_ok("cap-eu2")
        self.assertTrue(ok)

    def test_revoke(self):
        provenance.record("cap4", "proj-a", "copy", consent=True)
        self.db.insert("capabilities", {"id": "cap4", "status": "active"})
        provenance.revoke("cap4")
        rows = provenance.for_capability("cap4")
        self.assertFalse(rows[0]["consent"])

    def test_revoke_retires_the_capability_and_closes_the_consent_gate(self):
        """Revocation is the whole point of the module: after it, instantiate()'s gate
        must say no, and the capability row must be marked retired."""
        provenance.record("cap5", "proj-a", "copy", consent=True)
        self.db.insert("capabilities", {"id": "cap5", "status": "active"})

        self.assertTrue(provenance.consent_ok("cap5")[0])
        provenance.revoke("cap5")

        self.assertFalse(provenance.consent_ok("cap5")[0])
        self.assertEqual(self.db.rows["capabilities"][0]["status"], "retired")

    def test_revoke_flips_every_source_record(self):
        provenance.record("cap6", "proj-a", "copy", consent=True)
        provenance.record("cap6", "proj-b", "derived", consent=True)
        self.db.insert("capabilities", {"id": "cap6", "status": "active"})
        provenance.revoke("cap6")
        self.assertTrue(all(not r["consent"] for r in provenance.for_capability("cap6")))


class TestConsentGateIsWiredIntoCapability(ProvenanceTestCase):
    """The production consumer. capability.instantiate() is the caller this module exists
    to serve (go_to_market.py -> capability.instantiate), and nothing else in the suite
    covers that seam -- test_capability_contract_radius.py stubs `provenance` out entirely.
    """

    def setUp(self):
        super().setUp()
        import capability
        self.capability = capability
        patcher = patch.object(capability, "db", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        # capability holds its own reference to the provenance MODULE, not to db, so the
        # provenance.db patch from the base class already covers the nested calls.
        self.db.insert("capabilities", {"id": "cap-gated", "slug": "gated", "status": "active"})

    def test_instantiate_is_refused_without_consent(self):
        provenance.record("cap-gated", "proj-a", "copy", consent=False)
        res = self.capability.instantiate("gated", "target-project")
        self.assertFalse(res["ok"])
        self.assertIn("consent/residency block", res["error"])

    def test_instantiate_is_refused_after_revocation(self):
        provenance.record("cap-gated", "proj-a", "copy", consent=True)
        self.assertTrue(self.capability.instantiate("gated", "target-project")["ok"])

        provenance.revoke("cap-gated")
        res = self.capability.instantiate("gated", "target-project")
        self.assertFalse(res["ok"])
        # revoke() retires the row first, so that is the error the caller sees.
        self.assertEqual(res["error"], "capability retired")

    def test_instantiate_succeeds_when_consent_and_residency_line_up(self):
        provenance.record("cap-gated", "proj-a", "copy", consent=True, residency="US")
        res = self.capability.instantiate("gated", "target-project", target_residency="US")
        self.assertTrue(res["ok"])
        self.assertEqual(self.db.rows["capability_instances"][0]["project"], "target-project")

    def test_instantiate_is_refused_on_residency_mismatch(self):
        provenance.record("cap-gated", "proj-a", "copy", consent=True, residency="EU")
        res = self.capability.instantiate("gated", "target-project", target_residency="US")
        self.assertFalse(res["ok"])
        self.assertIn("residency mismatch", res["error"])
        self.assertNotIn("capability_instances", self.db.rows)


class TestMergeProvenanceLedger(ProvenanceTestCase):
    """The merge ledger. NOTE: no production code calls any of these four functions --
    they are reachable only from this file. The tests below therefore pin the contract the
    module documents for itself rather than any observed caller's expectations.
    """

    def test_record_merge(self):
        provenance.record("cap-a", "proj", "derived", consent=True)
        provenance.record("cap-b", "proj", "derived", consent=True)
        entry = provenance.record_merge("merge-1", ["cap-a", "cap-b"], author="bot")
        self.assertEqual(entry["merge_id"], "merge-1")
        self.assertEqual(len(entry["capability_ids"]), 2)
        self.assertTrue(entry["consent_snapshot"]["cap-a"]["ok"])
        self.assertEqual(entry["author"], "bot")
        self.assertEqual(entry["status"], "active")

    def test_record_merge_accepts_a_bare_capability_id(self):
        provenance.record("cap-solo", "proj", "copy", consent=True)
        entry = provenance.record_merge("merge-solo", "cap-solo")
        self.assertEqual(entry["capability_ids"], ["cap-solo"])

    def test_record_merge_snapshots_consent_as_it_was_at_merge_time(self):
        """The snapshot is the audit trail's whole value: it distinguishes 'this merge was
        never compliant' from 'consent was withdrawn afterwards'."""
        provenance.record("cap-t", "proj", "copy", consent=True)
        self.db.insert("capabilities", {"id": "cap-t", "status": "active"})
        provenance.record_merge("merge-t", ["cap-t"])

        provenance.revoke("cap-t")

        stored = provenance.merge_history(merge_id="merge-t")[0]
        self.assertTrue(stored["consent_snapshot"]["cap-t"]["ok"])
        self.assertFalse(provenance.consent_ok("cap-t")[0])

    def test_record_merge_is_fail_soft_when_the_ledger_write_fails(self):
        """Documented behaviour: a merge must not be blocked by a ledger outage."""
        with patch.object(self.db, "insert", side_effect=RuntimeError("ledger down")):
            entry = provenance.record_merge("merge-soft", ["cap-x"])
        self.assertEqual(entry["merge_id"], "merge-soft")
        self.assertEqual(provenance.merge_history(merge_id="merge-soft"), [])

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
        self.assertEqual(history[0]["merge_id"], "m1")

    def test_merge_history_filter_by_capability(self):
        provenance.record_merge("m1", ["a", "b"])
        provenance.record_merge("m2", ["c"])
        history = provenance.merge_history(capability_id="a")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["merge_id"], "m1")

    def test_merge_history_is_fail_soft_on_a_dead_ledger(self):
        with patch.object(self.db, "select", side_effect=RuntimeError("ledger down")):
            self.assertEqual(provenance.merge_history(), [])

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
        self.assertEqual(violations[0]["capability_id"], "cap-bad")
        self.assertIn("lacks consent", violations[0]["reason"])

    def test_audit_merge_reports_consent_withdrawn_after_the_merge(self):
        """A capability that was compliant at merge time and is not now is exactly the
        case the snapshot exists to surface: flagged, and marked as previously ok."""
        provenance.record("cap-later", "proj", "copy", consent=True)
        self.db.insert("capabilities", {"id": "cap-later", "status": "active"})
        provenance.record_merge("audit-3", ["cap-later"])

        provenance.revoke("cap-later")

        ok, violations = provenance.audit_merge("audit-3")
        self.assertFalse(ok)
        self.assertEqual(len(violations), 1)
        self.assertIs(violations[0]["was_ok_at_merge"], True)

    def test_audit_merge_not_found(self):
        ok, violations = provenance.audit_merge("nonexistent")
        self.assertFalse(ok)
        self.assertEqual(violations, [{"error": "merge not found"}])

    def test_rollback_merge(self):
        provenance.record("cap-r", "proj", "copy", consent=True)
        self.db.insert("capabilities", {"id": "cap-r", "status": "active"})
        provenance.record_merge("rollback-1", ["cap-r"])
        result = provenance.rollback_merge("rollback-1")
        self.assertIn("cap-r", result["revoked"])

    def test_rollback_merge_revokes_every_capability_and_marks_the_entry(self):
        for cid in ("cap-r1", "cap-r2"):
            provenance.record(cid, "proj", "copy", consent=True)
            self.db.insert("capabilities", {"id": cid, "status": "active"})
        provenance.record_merge("rollback-2", ["cap-r1", "cap-r2"])

        result = provenance.rollback_merge("rollback-2")

        self.assertEqual(sorted(result["revoked"]), ["cap-r1", "cap-r2"])
        self.assertFalse(provenance.consent_ok("cap-r1")[0])
        self.assertFalse(provenance.consent_ok("cap-r2")[0])
        self.assertEqual(
            {r["id"]: r["status"] for r in self.db.rows["capabilities"]},
            {"cap-r1": "retired", "cap-r2": "retired"},
        )
        self.assertEqual(provenance.merge_history(merge_id="rollback-2")[0]["status"],
                         "rolled_back")

    def test_rollback_of_an_unknown_merge_revokes_nothing(self):
        provenance.record("cap-safe", "proj", "copy", consent=True)
        result = provenance.rollback_merge("no-such-merge")
        self.assertEqual(result, {"merge_id": "no-such-merge", "revoked": []})
        self.assertTrue(provenance.consent_ok("cap-safe")[0])


if __name__ == "__main__":
    unittest.main()
