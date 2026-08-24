#!/usr/bin/env python3
"""Regression tests for recovery_ledger_publish fingerprint/kind tolerance.

A fully classified ledger emitted by a single-kind reconciler
(reconcile_local_branch_tips.py) uses the keys `fingerprint` and `kind`, while
reconcile_all_evidence.py uses `audit_fingerprint` and `evidence_kind`. The
publisher used to read only the latter pair, so a correct ledger produced by the
narrower tool refused to publish and left zero durable records behind. These
tests pin both spellings.
"""

import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "recovery_ledger_publish", os.path.join(_HERE, "recovery_ledger_publish.py")
)
rlp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rlp)


class FingerprintTolerance(unittest.TestCase):
    def test_prefers_audit_fingerprint(self):
        ledger = {"audit_fingerprint": "aaa", "fingerprint": "bbb"}
        self.assertEqual(rlp.fingerprint_of(ledger), "aaa")

    def test_falls_back_to_fingerprint(self):
        self.assertEqual(rlp.fingerprint_of({"fingerprint": "bbb"}), "bbb")

    def test_missing_is_empty_not_raising(self):
        self.assertEqual(rlp.fingerprint_of({}), "")

    def test_empty_string_does_not_shadow_fallback(self):
        ledger = {"audit_fingerprint": "", "fingerprint": "bbb"}
        self.assertEqual(rlp.fingerprint_of(ledger), "bbb")


class EvidenceKindTolerance(unittest.TestCase):
    def test_prefers_evidence_kind(self):
        ledger = {"evidence_kind": "mixed", "kind": "local_only_branch_tips"}
        self.assertEqual(rlp.evidence_kind_of(ledger), "mixed")

    def test_falls_back_to_kind(self):
        self.assertEqual(
            rlp.evidence_kind_of({"kind": "local_only_branch_tips"}),
            "local_only_branch_tips",
        )

    def test_default_is_unspecified(self):
        self.assertEqual(rlp.evidence_kind_of({}), "unspecified")


class RecordShape(unittest.TestCase):
    def test_record_from_single_kind_ledger_is_publishable(self):
        ledger = {
            "fingerprint": "f" * 64,
            "kind": "local_only_branch_tips",
            "base": "origin/master",
        }
        item = {
            "ref": "agent/example",
            "sha": "0" * 40,
            "classification": "RECOVERABLE_VALUE",
            "disposition": "merges cleanly",
            "files_changed": 3,
        }
        rec = rlp.record_for(item, ledger, "slug", "agent/slug", "cafe123")
        self.assertEqual(rec["audit_fingerprint"], "f" * 64)
        self.assertEqual(rec["evidence_kind"], "local_only_branch_tips")
        self.assertEqual(rec["source"], "agent/example")
        self.assertEqual(rec["classification"], "RECOVERABLE_VALUE")
        self.assertEqual(rec["branch"], "agent/slug")
        self.assertEqual(rec["commit"], "cafe123")

    def test_source_falls_back_through_ref_source_path(self):
        base = {"fingerprint": "x", "kind": "k"}
        self.assertEqual(
            rlp.record_for({"source": "s"}, base, "t", "b", "c")["source"], "s")
        self.assertEqual(
            rlp.record_for({"path": "p"}, base, "t", "b", "c")["source"], "p")
        self.assertEqual(
            rlp.record_for({}, base, "t", "b", "c")["source"], "")

    def test_unclassified_item_is_recorded_as_unknown_not_dropped(self):
        rec = rlp.record_for({"ref": "r"}, {"fingerprint": "x"}, "t", "b", "c")
        self.assertEqual(rec["classification"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
