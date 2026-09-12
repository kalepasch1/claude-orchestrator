"""Zero UNKNOWN, even when the evidence is one opaque FAILURE/SLOG line.

The recovery hand-off usually arrives as prose, not as a set of refs. Enumerating the
repo then finds nothing to classify, the caller reports UNKNOWN for the whole hand-off,
and the same reconciliation gets queued again. `reconcile_text()` closes that: every
extracted item gets one of the five labels, and an item whose evidence is incomplete is
CONFLICTED_NEEDS_FOCUSED_TASK with the missing information named.

Everything here is read-only — no test creates, moves or deletes a ref.
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
for _p in (_REPO, os.path.join(_REPO, "runner")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import local_evidence_reconciler as ler  # noqa: E402

# The task's literal acceptance input: one failure line, no real evidence paths.
SLOG_LINE = ("FAILURE/SLOG chatgpt-local-reconcile-beethoven-939f3db3fe9c: "
             "local repo reconciliation classifier produced no ledger")


class ExtractionTest(unittest.TestCase):

    def test_a_bare_line_still_yields_an_item(self):
        # The only identifier in this line is the audit fingerprint, which reads as a
        # short sha — so it is extracted as a commit rather than falling through to the
        # slog-line catch-all. Either way the line produces something to classify.
        items = ler.extract_evidence_from_text(SLOG_LINE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "commit")
        self.assertEqual(items[0]["ref"], "939f3db3fe9c")

    def test_a_line_with_no_identifier_at_all_falls_back_to_the_line(self):
        items = ler.extract_evidence_from_text("reconciliation produced no ledger")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "slog-line")
        self.assertIn("missing", items[0])

    def test_empty_input_still_yields_one_item(self):
        for blob in ("", None, "   "):
            items = ler.extract_evidence_from_text(blob)
            self.assertEqual(len(items), 1, blob)

    def test_branch_names_are_extracted(self):
        items = ler.extract_evidence_from_text("lost work on agent/foo-bar and hotfix/baz")
        refs = {i["ref"] for i in items}
        self.assertIn("agent/foo-bar", refs)
        self.assertIn("hotfix/baz", refs)

    def test_refs_stashes_and_worktrees_are_extracted(self):
        blob = ("refs/archive/agent/x/1786 plus stash@{3} plus "
                "/Users/x/repo-wt/some-slug")
        kinds = {i["kind"]: i["ref"] for i in ler.extract_evidence_from_text(blob)}
        self.assertIn("rescue-ref", kinds)
        self.assertIn("stash", kinds)
        self.assertIn("worktree", kinds)

    def test_duplicate_identifiers_are_extracted_once(self):
        items = ler.extract_evidence_from_text("agent/dup and agent/dup again")
        self.assertEqual([i["ref"] for i in items].count("agent/dup"), 1)

    def test_a_ref_is_not_double_counted_as_a_branch(self):
        items = ler.extract_evidence_from_text("refs/heads/agent/thing")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "rescue-ref")


class ClassifyIncompleteTest(unittest.TestCase):

    def test_incomplete_is_conflicted_not_unknown(self):
        rec = ler.classify_incomplete({"kind": "slog-line", "name": "x"}, "missing ref")
        self.assertEqual(rec["classification"], "CONFLICTED_NEEDS_FOCUSED_TASK")
        self.assertIn("missing ref", rec["disposition"])

    def test_record_has_every_ledger_field(self):
        rec = ler.classify_incomplete({"kind": "slog-line", "name": "x"}, "why")
        for field in ("source", "kind", "name", "slug", "classification", "disposition",
                      "unique_commits", "paths", "task", "branch", "commit", "detail"):
            self.assertIn(field, rec)

    def test_classify_any_flags_missing_ref(self):
        rec = ler.classify_any("", {"kind": "slog-line", "name": "x", "ref": ""})
        self.assertEqual(rec["classification"], "CONFLICTED_NEEDS_FOCUSED_TASK")
        self.assertIn("ref", rec["detail"])

    def test_classify_any_without_context_is_conflicted(self):
        rec = ler.classify_any("", {"kind": "branch", "name": "agent/x", "ref": "agent/x"})
        self.assertEqual(rec["classification"], "CONFLICTED_NEEDS_FOCUSED_TASK")

    def test_classify_any_never_returns_unknown_for_garbage(self):
        for item in ({}, {"kind": ""}, {"ref": None}, {"kind": "branch"}):
            rec = ler.classify_any("", item)
            self.assertIn(rec["classification"], ler.CLASSIFICATIONS)


class ReconcileTextAcceptanceTest(unittest.TestCase):
    """The stated acceptance test: one FAILURE/SLOG line in, zero UNKNOWN out."""

    def test_no_unknown_anywhere_in_the_output_json(self):
        report = ler.reconcile_text(SLOG_LINE, "939f3db3fe9c", write=False)
        self.assertNotIn("UNKNOWN", json.dumps(report))

    def test_every_extracted_item_has_a_classification(self):
        report = ler.reconcile_text(SLOG_LINE, "939f3db3fe9c", write=False)
        self.assertTrue(report["records"])
        for rec in report["records"]:
            self.assertIn(rec["classification"], ler.CLASSIFICATIONS)

    def test_report_is_complete_and_json_serialisable(self):
        report = ler.reconcile_text(SLOG_LINE, "939f3db3fe9c", write=False)
        self.assertTrue(report["complete"])
        self.assertEqual(report["unknown"], [])
        json.dumps(report, default=str)

    def test_counts_sum_to_the_record_count(self):
        report = ler.reconcile_text(
            "agent/a refs/archive/b stash@{0} " + SLOG_LINE, "fp", write=False)
        self.assertEqual(sum(report["counts"].values()), len(report["records"]))

    def test_items_needing_work_are_listed_for_followup(self):
        report = ler.reconcile_text(SLOG_LINE, "fp", write=False)
        self.assertTrue(report["needs_followup"])

    def test_a_missing_repo_path_does_not_raise(self):
        report = ler.reconcile_text(SLOG_LINE, "fp", repo="/nonexistent/path", write=False)
        self.assertTrue(report["complete"])
        self.assertNotIn("UNKNOWN", json.dumps(report))

    def test_nothing_is_written_when_write_is_false(self):
        report = ler.reconcile_text(SLOG_LINE, "fp", write=False)
        self.assertIsNone(report["ledger"])

    def test_empty_input_is_still_a_complete_report(self):
        report = ler.reconcile_text("", "fp", write=False)
        self.assertEqual(len(report["records"]), 1)
        self.assertTrue(report["complete"])


class RealRepoTest(unittest.TestCase):
    """With a live repo, a named ref is classified against actual ancestry."""

    def test_master_is_already_present(self):
        report = ler.reconcile_text("agent/does-not-exist-anywhere-xyz", "fp",
                                    repo=_REPO, write=False)
        self.assertTrue(report["records"])
        for rec in report["records"]:
            self.assertIn(rec["classification"], ler.CLASSIFICATIONS)
        self.assertNotIn("UNKNOWN", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
