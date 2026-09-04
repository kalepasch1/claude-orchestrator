#!/usr/bin/env python3
"""Tests for tools/ledger_precheck.py."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ledger_precheck as LP  # noqa: E402

FP = "c648ef526fa60874f0345748163809146864d79234605f6675d128d8c74190bf"
SLUG = "chatgpt-local-reconcile-beethoven-c648ef526fa6"


def rec(cls="ALREADY_PRESENT", fp=FP, slug=SLUG, **kw):
    d = {"classification": cls, "audit_fingerprint": fp, "task_slug": slug,
         "source": "refs/orch-rescue/x"}
    d.update(kw)
    return d


class TestCoerceRecord(unittest.TestCase):
    def test_plain_dict_passthrough(self):
        self.assertEqual(LP.coerce_record(rec())["classification"], "ALREADY_PRESENT")

    def test_payload_string_unwrapped(self):
        row = {"status": "open", "payload": json.dumps(rec("RECOVERABLE_VALUE"))}
        got = LP.coerce_record(row)
        self.assertEqual(got["classification"], "RECOVERABLE_VALUE")
        self.assertEqual(got["status"], "open")

    def test_payload_dict_unwrapped(self):
        self.assertEqual(LP.coerce_record({"payload": rec()})["task_slug"], SLUG)

    def test_json_string_row(self):
        self.assertEqual(LP.coerce_record(json.dumps(rec()))["task_slug"], SLUG)

    def test_malformed_payload_returns_empty(self):
        self.assertEqual(LP.coerce_record({"payload": "{oops"}), {})

    def test_non_dict_returns_empty(self):
        self.assertEqual(LP.coerce_record(7), {})
        self.assertEqual(LP.coerce_record(None), {})
        self.assertEqual(LP.coerce_record("not json"), {})


class TestMatches(unittest.TestCase):
    def test_exact_fingerprint(self):
        self.assertTrue(LP.matches(rec(), FP, ""))

    def test_abbreviated_fingerprint_prefix(self):
        self.assertTrue(LP.matches(rec(fp=FP[:12]), FP, ""))

    def test_short_prefix_rejected_as_too_weak(self):
        self.assertFalse(LP.matches(rec(fp="c648"), FP, ""))

    def test_different_fingerprint(self):
        self.assertFalse(LP.matches(rec(fp="f" * 64), FP, ""))

    def test_slug_match_without_fingerprint(self):
        self.assertTrue(LP.matches(rec(fp=""), "", SLUG))

    def test_result_task_counts_as_slug(self):
        r = {"result_task": SLUG}
        self.assertTrue(LP.matches(r, "", SLUG))

    def test_non_dict_safe(self):
        self.assertFalse(LP.matches("junk", FP, ""))


class TestProvenance(unittest.TestCase):
    def test_disposition_is_durable(self):
        self.assertTrue(LP.has_provenance({"disposition": "queued for apply"}))

    def test_branch_is_durable(self):
        self.assertTrue(LP.has_provenance({"result_branch": "agent/x"}))

    def test_blank_fields_not_durable(self):
        self.assertFalse(LP.has_provenance(
            {"result_task": "", "result_branch": "  ", "result_commit": None}))

    def test_empty_record_not_durable(self):
        self.assertFalse(LP.has_provenance({}))
        self.assertFalse(LP.has_provenance(None))


class TestEvaluate(unittest.TestCase):
    def test_complete_ledger_supersedes(self):
        v = LP.evaluate([rec(), rec("SUPERSEDED_BY_NEWER")], FP)
        self.assertEqual(v["verdict"], "supersede")
        self.assertEqual(v["matched"], 2)
        self.assertEqual(v["unknown"], 0)

    def test_no_records_means_scan(self):
        v = LP.evaluate([], FP)
        self.assertEqual(v["verdict"], "scan")
        self.assertIn("at least", v["reason"])

    def test_unrelated_records_means_scan(self):
        v = LP.evaluate([rec(fp="f" * 64, slug="other")], FP, SLUG)
        self.assertEqual(v["verdict"], "scan")
        self.assertEqual(v["matched"], 0)

    def test_unknown_item_blocks_supersede(self):
        v = LP.evaluate([rec(), rec("NONSENSE")], FP)
        self.assertEqual(v["verdict"], "scan")
        self.assertEqual(v["unknown"], 1)
        self.assertIn("UNKNOWN", v["reason"])

    def test_missing_classification_counts_unknown(self):
        v = LP.evaluate([{"audit_fingerprint": FP}], FP)
        self.assertEqual(v["verdict"], "scan")
        self.assertEqual(v["unknown"], 1)

    def test_recoverable_without_provenance_blocks_supersede(self):
        v = LP.evaluate([rec("RECOVERABLE_VALUE")], FP)
        self.assertEqual(v["verdict"], "scan")
        self.assertEqual(v["undurable"], 1)
        self.assertIn("durable", v["reason"])

    def test_recoverable_with_provenance_supersedes(self):
        v = LP.evaluate([rec("RECOVERABLE_VALUE", disposition="queued")], FP)
        self.assertEqual(v["verdict"], "supersede")
        self.assertEqual(v["undurable"], 0)

    def test_conflicted_also_needs_provenance(self):
        v = LP.evaluate([rec("CONFLICTED_NEEDS_FOCUSED_TASK")], FP)
        self.assertEqual(v["verdict"], "scan")

    def test_already_present_needs_no_provenance(self):
        self.assertEqual(LP.evaluate([rec("ALREADY_PRESENT")], FP)["verdict"],
                         "supersede")

    def test_min_items_threshold_enforced(self):
        v = LP.evaluate([rec()], FP, min_items=5)
        self.assertEqual(v["verdict"], "scan")
        self.assertIn("need at least 5", v["reason"])

    def test_counts_histogram_reported(self):
        v = LP.evaluate([rec(), rec(), rec("SUPERSEDED_BY_NEWER")], FP)
        self.assertEqual(v["counts"],
                         {"ALREADY_PRESENT": 2, "SUPERSEDED_BY_NEWER": 1})

    def test_none_records_safe(self):
        self.assertEqual(LP.evaluate(None, FP)["verdict"], "scan")

    def test_real_shape_from_coordination_tasks(self):
        # The payload shape actually stored in coordination_tasks.
        rows = [{"status": "open", "payload": json.dumps({
            "reason": "2 unique commit(s) not on origin/main",
            "source": "refs/orch-rescue/20260803T000716-claude-orchestrator",
            "task_slug": SLUG, "classification": "RECOVERABLE_VALUE",
            "disposition": "left in place and DURABLY QUEUED",
            "result_task": SLUG, "audit_fingerprint": FP})}]
        v = LP.evaluate([LP.coerce_record(r) for r in rows], FP, SLUG)
        self.assertEqual(v["verdict"], "supersede")


class TestLoadAndCli(unittest.TestCase):
    def _write(self, d, data):
        p = os.path.join(d, "r.json")
        with open(p, "w") as fh:
            json.dump(data, fh)
        return p

    def test_load_missing_returns_empty(self):
        self.assertEqual(LP.load_records("/nonexistent/r.json"), [])

    def test_load_malformed_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{oops")
            p = fh.name
        try:
            self.assertEqual(LP.load_records(p), [])
        finally:
            os.unlink(p)

    def test_load_wrapped_in_records_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, {"records": [rec()]})
            self.assertEqual(len(LP.load_records(p)), 1)

    def test_load_skips_unusable_rows(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, [rec(), 7, None, {"payload": "{bad"}])
            self.assertEqual(len(LP.load_records(p)), 1)

    def test_cli_exit_zero_on_supersede(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, [rec()])
            self.assertEqual(LP.main(["--records", p, "--fingerprint", FP]), 0)

    def test_cli_exit_one_on_scan(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, [])
            self.assertEqual(LP.main(["--records", p, "--fingerprint", FP]), 1)

    def test_cli_refuses_without_selector(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, [rec()])
            self.assertEqual(LP.main(["--records", p]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
