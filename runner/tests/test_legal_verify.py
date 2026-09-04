#!/usr/bin/env python3
"""LEGAL-VERIFY gate.

Acceptance (from the task): a too-close-to-competitor draft is demonstrably
REJECTED by the similarity ceiling, a contradicting-clause fixture is flagged, and
a missing-jurisdiction fixture is flagged. 20+ tests.

Proof: python3 -m pytest runner/tests/test_legal_verify.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from legal import legal_verify as lv  # noqa: E402

CLEAN_DRAFT = """
Welcome. We keep your data safe.
"Service" means the app you use. The Service is simple.
We will delete your files after 30 days.
You may ask us to stop. We will stop.
We follow the rules in the United States. We follow the rules in Canada.
We follow the rules in Brazil.
""".strip()

CONTRADICTING_DRAFT = """
"Service" means the app you use. The Service is simple.
We will sell your data to partners.
Later in this document, we say the opposite.
We will not sell your data to partners.
We follow the rules in the United States.
""".strip()

CONFLICTING_PERIODS_DRAFT = """
"Service" means the app you use. The Service is simple.
Logs are retained for 30 days.
Elsewhere the policy says logs are retained for 90 days.
We follow the rules in the United States.
""".strip()

COMPETITOR_DOC = """
We collect the information you give us when you create an account and when you
use the product, including your name, your email address, and the pages you view.
We use that information to operate the product, to keep it safe, and to tell you
about changes. We do not sell that information to anyone at any time.
""".strip()


def _copy_with_light_edits(text):
    """A draft that is plainly lifted: a couple of words changed, structure intact."""
    return text.replace("the product", "the service").replace("anyone", "third parties")


class TestReadability(unittest.TestCase):
    def test_simple_text_scores_low(self):
        self.assertLess(lv.readability_grade("We keep your data safe. You may ask us to stop."), 8)

    def test_dense_legalese_scores_high(self):
        dense = ("Notwithstanding any provision herein to the contrary, the "
                 "aforementioned indemnification obligations shall survive termination "
                 "irrespective of the characterization of any consequential liability.")
        self.assertGreater(lv.readability_grade(dense), 14)

    def test_empty_text_is_zero_not_an_exception(self):
        self.assertEqual(lv.readability_grade(""), 0.0)
        self.assertEqual(lv.readability_grade(None), 0.0)

    def test_readability_ceiling_produces_a_warning_not_an_error(self):
        dense = ("Notwithstanding any provision herein to the contrary, the "
                 "aforementioned indemnification obligations shall survive termination "
                 "irrespective of the characterization of any consequential liability.")
        findings = lv.check_readability(dense, ceiling=6.0)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "warning")

    def test_readable_text_produces_no_finding(self):
        self.assertEqual(lv.check_readability("We keep it safe. You may stop.", 14.0), [])


class TestSimilarity(unittest.TestCase):
    def test_identical_text_is_one(self):
        self.assertEqual(lv.similarity(COMPETITOR_DOC, COMPETITOR_DOC), 1.0)

    def test_unrelated_text_is_near_zero(self):
        self.assertLess(lv.similarity(COMPETITOR_DOC, "The cat sat on the mat quietly."), 0.05)

    def test_lightly_edited_copy_is_still_very_similar(self):
        self.assertGreater(
            lv.similarity(COMPETITOR_DOC, _copy_with_light_edits(COMPETITOR_DOC)), 0.35)

    def test_similarity_is_symmetric(self):
        a, b = COMPETITOR_DOC, _copy_with_light_edits(COMPETITOR_DOC)
        self.assertEqual(lv.similarity(a, b), lv.similarity(b, a))

    def test_similarity_is_fail_soft(self):
        for bad in (None, "", 7, [], {}):
            self.assertEqual(lv.similarity(bad, COMPETITOR_DOC), 0.0, bad)


class TestCompetitorCeilingRejects(unittest.TestCase):
    """The headline acceptance case: too close to a competitor -> REJECTED."""

    def test_lifted_draft_is_rejected(self):
        result = lv.verify(_copy_with_light_edits(COMPETITOR_DOC),
                           competitor_snapshots=[{"text": COMPETITOR_DOC,
                                                  "source": "competitor-a"}])
        self.assertFalse(result.ok)
        self.assertIn("competitor_similarity", [f.check for f in result.errors])

    def test_rejection_is_an_error_not_a_warning(self):
        result = lv.verify(_copy_with_light_edits(COMPETITOR_DOC),
                           competitor_snapshots=[COMPETITOR_DOC])
        self.assertTrue(any(f.check == "competitor_similarity" and f.severity == "error"
                            for f in result.findings))

    def test_rejection_names_the_source_and_the_score(self):
        result = lv.verify(_copy_with_light_edits(COMPETITOR_DOC),
                           competitor_snapshots=[{"text": COMPETITOR_DOC,
                                                  "source": "competitor-a"}])
        finding = next(f for f in result.errors if f.check == "competitor_similarity")
        self.assertEqual(finding.evidence["source"], "competitor-a")
        self.assertGreater(finding.evidence["similarity"], finding.evidence["ceiling"])

    def test_original_draft_passes_the_same_corpus(self):
        result = lv.verify(CLEAN_DRAFT,
                           required_jurisdictions=["United States", "Canada", "Brazil"],
                           competitor_snapshots=[{"text": COMPETITOR_DOC,
                                                  "source": "competitor-a"}])
        self.assertTrue(result.ok, result.reasons())

    def test_ceiling_is_caller_overridable(self):
        draft = _copy_with_light_edits(COMPETITOR_DOC)
        self.assertFalse(lv.verify(draft, competitor_snapshots=[COMPETITOR_DOC],
                                   similarity_ceiling=0.10).ok)
        self.assertTrue(lv.verify(draft, competitor_snapshots=[COMPETITOR_DOC],
                                  similarity_ceiling=0.99).ok)

    def test_empty_corpus_cannot_reject(self):
        self.assertEqual(lv.check_competitor_similarity(CLEAN_DRAFT, []), [])

    def test_blank_snapshots_are_skipped_not_scored(self):
        self.assertEqual(
            lv.check_competitor_similarity(CLEAN_DRAFT, ["", "   ", {"text": None}]), [])

    def test_max_similarity_is_reported_even_on_a_pass(self):
        result = lv.verify(CLEAN_DRAFT,
                           required_jurisdictions=["United States", "Canada", "Brazil"],
                           competitor_snapshots=[COMPETITOR_DOC])
        self.assertIn("max_competitor_similarity", result.metrics)
        self.assertLessEqual(result.metrics["max_competitor_similarity"],
                             result.metrics["similarity_ceiling"])


class TestInternalConsistency(unittest.TestCase):
    def test_contradicting_clause_fixture_is_flagged(self):
        findings = lv.check_internal_consistency(CONTRADICTING_DRAFT)
        self.assertTrue(any(f.check == "internal_consistency" for f in findings), findings)

    def test_contradiction_fails_the_gate(self):
        result = lv.verify(CONTRADICTING_DRAFT,
                           required_jurisdictions=["United States"])
        self.assertFalse(result.ok)

    def test_conflicting_retention_periods_are_flagged(self):
        findings = lv.check_internal_consistency(CONFLICTING_PERIODS_DRAFT)
        self.assertTrue(any("retained" in f.message for f in findings), findings)

    def test_conflicting_period_finding_lists_both_values(self):
        findings = [f for f in lv.check_internal_consistency(CONFLICTING_PERIODS_DRAFT)
                    if f.evidence and "values" in (f.evidence or {})]
        self.assertEqual(findings[0].evidence["values"], [30, 90])

    def test_consistent_draft_has_no_consistency_findings(self):
        self.assertEqual(lv.check_internal_consistency(CLEAN_DRAFT), [])

    def test_consistency_check_survives_junk(self):
        self.assertEqual(lv.check_internal_consistency(""), [])
        self.assertEqual(lv.check_internal_consistency(None), [])


class TestJurisdictionCoverage(unittest.TestCase):
    def test_missing_jurisdiction_fixture_is_flagged(self):
        findings = lv.check_jurisdiction_coverage(
            CLEAN_DRAFT, ["United States", "Canada", "Brazil", "Japan"])
        self.assertEqual([f.evidence["jurisdiction"] for f in findings], ["Japan"])

    def test_missing_jurisdiction_fails_the_gate(self):
        result = lv.verify(CLEAN_DRAFT, required_jurisdictions=["Japan"])
        self.assertFalse(result.ok)
        self.assertIn("jurisdiction_coverage", [f.check for f in result.errors])

    def test_covered_jurisdictions_produce_no_findings(self):
        self.assertEqual(
            lv.check_jurisdiction_coverage(CLEAN_DRAFT, ["United States", "Canada"]), [])

    def test_matching_is_case_insensitive(self):
        self.assertEqual(lv.check_jurisdiction_coverage(CLEAN_DRAFT, ["united states"]), [])

    def test_blank_entries_in_the_registry_are_ignored(self):
        self.assertEqual(lv.check_jurisdiction_coverage(CLEAN_DRAFT, ["", "   ", None, 5]), [])

    def test_no_registry_means_no_coverage_requirement(self):
        self.assertEqual(lv.check_jurisdiction_coverage(CLEAN_DRAFT), [])


class TestDefinedTerms(unittest.TestCase):
    def test_unused_defined_term_is_flagged(self):
        draft = '"Widget" means a thing. We keep your data safe in the United States.'
        findings = lv.check_defined_terms(draft)
        self.assertTrue(any("never used" in f.message for f in findings), findings)

    def test_undefined_term_shaped_phrase_is_flagged(self):
        draft = "We process your data under the Data Processing Addendum at all times."
        findings = lv.check_defined_terms(draft)
        self.assertTrue(any("never defined" in f.message for f in findings), findings)

    def test_defined_and_used_term_is_clean(self):
        draft = '"Service" means the app. The Service is simple and safe.'
        self.assertEqual([f for f in lv.check_defined_terms(draft)
                          if "Service" in f.message], [])

    def test_defined_term_findings_are_warnings_not_gate_failures(self):
        draft = '"Widget" means a thing. We keep your data safe.'
        result = lv.verify(draft)
        self.assertTrue(all(f.severity == "warning" for f in result.findings), result.findings)
        self.assertTrue(result.ok)


class TestResultContract(unittest.TestCase):
    def test_passing_result_is_truthy_and_bounces_nothing(self):
        result = lv.verify(CLEAN_DRAFT,
                           required_jurisdictions=["United States", "Canada", "Brazil"])
        self.assertTrue(result)
        self.assertIsNone(result.bounce())
        self.assertEqual(result.reasons(), ())

    def test_failing_result_bounces_grouped_by_check(self):
        result = lv.verify(CONTRADICTING_DRAFT, required_jurisdictions=["Japan"])
        bounce = result.bounce()
        self.assertEqual(bounce["action"], "revise")
        self.assertIn("internal_consistency", bounce["blocking"])
        self.assertIn("jurisdiction_coverage", bounce["blocking"])

    def test_bounce_carries_actionable_findings_not_just_a_verdict(self):
        result = lv.verify(CLEAN_DRAFT, required_jurisdictions=["Japan"])
        findings = result.bounce()["findings"]["jurisdiction_coverage"]
        self.assertEqual(findings[0]["evidence"]["jurisdiction"], "Japan")

    def test_result_serializes(self):
        payload = lv.verify(CLEAN_DRAFT, required_jurisdictions=["Japan"]).as_dict()
        self.assertIn("ok", payload)
        self.assertIn("findings", payload)
        self.assertIn("metrics", payload)

    def test_errors_and_warnings_are_separated(self):
        result = lv.verify(CLEAN_DRAFT, required_jurisdictions=["Japan"])
        self.assertTrue(all(f.severity == "error" for f in result.errors))
        self.assertTrue(all(f.severity == "warning" for f in result.warnings))

    def test_unknown_severity_is_coerced_to_error(self):
        self.assertEqual(lv.Finding("x", "whatever", "m").severity, "error")

    def test_metrics_report_the_measured_numbers(self):
        result = lv.verify(CLEAN_DRAFT,
                           required_jurisdictions=["United States", "Canada", "Brazil"])
        self.assertGreater(result.metrics["words"], 0)
        self.assertIn("readability_grade", result.metrics)


class TestFailSoft(unittest.TestCase):
    def test_empty_draft_is_rejected_with_a_reason_not_an_exception(self):
        result = lv.verify("")
        self.assertFalse(result.ok)
        self.assertTrue(result.reasons())

    def test_non_text_draft_is_rejected(self):
        for bad in (None, 7, [], {}):
            self.assertFalse(lv.verify(bad).ok, bad)

    def test_whitespace_draft_is_rejected(self):
        self.assertFalse(lv.verify("   \n  ").ok)

    def test_bad_env_knob_falls_back_to_the_default(self):
        os.environ["ORCH_LEGAL_TEST_KNOB"] = "not-a-number"
        try:
            self.assertEqual(lv._env_float("ORCH_LEGAL_TEST_KNOB", 1.5), 1.5)
        finally:
            os.environ.pop("ORCH_LEGAL_TEST_KNOB", None)

    def test_unset_env_knob_uses_the_default(self):
        os.environ.pop("ORCH_LEGAL_TEST_KNOB", None)
        self.assertEqual(lv._env_float("ORCH_LEGAL_TEST_KNOB", 2.5), 2.5)


class TestModuleHygiene(unittest.TestCase):
    def test_no_network_db_or_filesystem_access(self):
        """The gate is pure logic; every corpus is injected by the caller."""
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "legal", "legal_verify.py")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read())
        allowed = {"os", "re", "typing", "__future__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed, alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                self.assertIn((node.module or "").split(".")[0], allowed, node.module)

    def test_check_ids_are_pinned(self):
        self.assertEqual(lv.CHECKS, (
            "internal_consistency", "defined_terms", "jurisdiction_coverage",
            "readability", "competitor_similarity"))


if __name__ == "__main__":
    unittest.main()
