"""Unit tests for the recovery-ledger publisher.

Run: python3 -m unittest discover -s tools -p 'test_*.py'

No database is touched. The publisher's risky parts are pure: which status an
item maps to, what ends up in the payload, and whether the dedupe read fails
soft — a dedupe that raises would stop a ledger from landing, which is worse
than a duplicate row.
"""

import json
import os
import tempfile
import unittest

import publish_recovery_ledger as p


class Args:
    def __init__(self, **kw):
        self.task_slug = kw.get("task_slug", "slug")
        self.project = kw.get("project", "beethoven")
        self.branch = kw.get("branch", "agent/slug")
        self.commit = kw.get("commit", "deadbeef")


class StatusMapping(unittest.TestCase):
    def test_items_that_still_owe_work_stay_open(self):
        self.assertEqual(p.status_for("RECOVERABLE_VALUE"), "open")
        self.assertEqual(p.status_for("CONFLICTED_NEEDS_FOCUSED_TASK"), "open")

    def test_resolved_classifications_close(self):
        for c in ("ALREADY_PRESENT", "SUPERSEDED_BY_NEWER",
                  "ACTIVE_IN_ANOTHER_TASK"):
            self.assertEqual(p.status_for(c), "closed", c)

    def test_unrecognised_classification_does_not_raise(self):
        self.assertEqual(p.status_for("SOMETHING_NEW"), "closed")


class BuildPayload(unittest.TestCase):
    LEDGER = {"audit_fingerprint": "f" * 64, "evidence_kind": "fallback_kind"}

    def test_carries_provenance_and_classification(self):
        row = p.build_payload(
            {"ref": "refs/orch-rescue/x", "kind": "orchestrator_rescue_refs",
             "classification": "RECOVERABLE_VALUE", "disposition": "why",
             "evidence": "how", "files": ["b.py", "a.py"]},
            self.LEDGER, Args())
        self.assertEqual(row["source"], "refs/orch-rescue/x")
        self.assertEqual(row["source_kind"], "orchestrator_rescue_refs")
        self.assertEqual(row["files"], ["a.py", "b.py"])
        self.assertEqual(row["file_count"], 2)
        self.assertEqual(row["audit_fingerprint"], "f" * 64)
        self.assertEqual(row["commit"], "deadbeef")

    def test_kind_falls_back_to_the_ledger_evidence_kind(self):
        row = p.build_payload({"ref": "r", "classification": "ALREADY_PRESENT"},
                              self.LEDGER, Args())
        self.assertEqual(row["source_kind"], "fallback_kind")

    def test_missing_classification_is_reported_as_unknown_not_guessed(self):
        # Completion requires zero UNKNOWN items, so an item with no
        # classification must stay visibly UNKNOWN rather than defaulting to
        # something reassuring.
        row = p.build_payload({"ref": "r"}, self.LEDGER, Args())
        self.assertEqual(row["classification"], "UNKNOWN")

    def test_recover_files_is_accepted_as_an_alias(self):
        row = p.build_payload(
            {"ref": "r", "classification": "RECOVERABLE_VALUE",
             "recover_files": ["only.py"]}, self.LEDGER, Args())
        self.assertEqual(row["files"], ["only.py"])

    def test_file_list_is_capped_but_the_true_count_survives(self):
        many = ["f%03d.py" % i for i in range(50)]
        row = p.build_payload(
            {"ref": "r", "classification": "ALREADY_PRESENT", "files": many},
            self.LEDGER, Args())
        self.assertEqual(len(row["files"]), 20)
        self.assertEqual(row["file_count"], 50)


class DedupeFailsSoft(unittest.TestCase):
    class Boom:
        def select_all(self, *a, **kw):
            raise RuntimeError("postgrest down")

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def select_all(self, *a, **kw):
            return self.rows

    def test_read_failure_returns_empty_rather_than_raising(self):
        self.assertEqual(p.already_published("f" * 64, self.Boom()), set())

    def test_only_this_fingerprints_sources_are_treated_as_published(self):
        rows = [
            {"payload": json.dumps({"audit_fingerprint": "f" * 64,
                                    "source": "mine"})},
            {"payload": json.dumps({"audit_fingerprint": "a" * 64,
                                    "source": "someone-elses"})},
            {"payload": "not json at all"},
            {"payload": None},
        ]
        self.assertEqual(p.already_published("f" * 64, self.Rows(rows)),
                         {"mine"})


class LedgerWithoutFingerprintIsRefused(unittest.TestCase):
    def test_dry_run_refuses_an_untraceable_ledger(self):
        import sys
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"items": [{"ref": "r", "classification": "ALREADY_PRESENT"}]},
                  tmp)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        argv = sys.argv
        sys.argv = ["x", "--ledger", tmp.name, "--task-slug", "s", "--dry-run"]
        try:
            self.assertEqual(p.main(), 2)
        finally:
            sys.argv = argv


if __name__ == "__main__":
    unittest.main()
