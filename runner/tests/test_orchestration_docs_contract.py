#!/usr/bin/env python3
"""docs/ORCHESTRATION_PIPELINE_CONTRACT.md must not drift from the router.

The documented preflight route is the version people quote in review, so a doc that
quietly stops matching the code is worse than no doc. This suite reads the routes OUT of
the markdown and asserts the function really returns them.

It also pins the specific error that produced this document: the request asked for the
legal-class route to be documented as `google:gemini-2.0-flash`. The router returns
`google:gemini-2.5-flash`. The doc records the real value and says why.

Proof: python3 -m pytest runner/tests/test_orchestration_docs_contract.py -q
"""
import os
import re
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(RUNNER)
sys.path.insert(0, RUNNER)

import orchestration_pipeline_config as opc  # noqa: E402

DOC = os.path.join(REPO, "docs", "ORCHESTRATION_PIPELINE_CONTRACT.md")
LEGAL_CLASS = "legal (need 9, risk legal_posture)"
BUILD_CLASS = "build (need 6, risk standard)"


def _doc_text():
    with open(DOC, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


class TestDocExists(unittest.TestCase):
    def test_the_file_is_present(self):
        self.assertTrue(os.path.isfile(DOC), f"{DOC} missing")

    def test_it_has_the_requested_section(self):
        self.assertIn("## Preflight Triage Model Selection Example", _doc_text())

    def test_it_points_at_the_owner_module(self):
        self.assertIn("orchestration_pipeline_config.py", _doc_text())


class TestDocumentedRoutesMatchTheCode(unittest.TestCase):
    """The drift guard. If either side moves, this fails and names which."""

    def test_the_worked_example_matches_the_function(self):
        text = _doc_text()
        m = re.search(r'preflight_triage_model\("legal \(need 9, risk legal_posture\)"\)'
                      r"\s*\n'([^']+)'", text)
        self.assertIsNotNone(m, "the legal worked example is missing from the doc")
        self.assertEqual(m.group(1), opc.preflight_triage_model(LEGAL_CLASS),
                         "the documented legal route no longer matches the router")

    def test_the_default_example_matches_the_function(self):
        text = _doc_text()
        m = re.search(r'preflight_triage_model\("build \(need 6, risk standard\)"\)'
                      r"\s*\n'([^']+)'", text)
        self.assertIsNotNone(m, "the default worked example is missing from the doc")
        self.assertEqual(m.group(1), opc.preflight_triage_model(BUILD_CLASS))

    def test_the_configuration_table_matches_the_constants(self):
        text = _doc_text()
        self.assertIn(opc.PREFLIGHT_ESCALATED_MODEL, text)
        self.assertIn("ORCH_PREFLIGHT_ESCALATED_MODEL", text)
        self.assertIn("ORCH_PREFLIGHT_MODEL", text)

    def test_every_escalated_class_is_documented(self):
        text = _doc_text()
        for name in opc.PREFLIGHT_ESCALATED_CLASSES:
            self.assertIn(f"`{name}`", text, f"escalated class {name} is undocumented")

    def test_the_doc_does_not_carry_the_wrong_value_from_the_request(self):
        """The request said gemini-2.0-flash; the router says 2.5. Only if the router
        genuinely returned 2.0 should that string be documentable."""
        text = _doc_text()
        if opc.preflight_triage_model(LEGAL_CLASS) != "google:gemini-2.0-flash":
            self.assertNotIn("returns `google:gemini-2.0-flash`", text)


class TestRouterBehaviour(unittest.TestCase):
    """The behaviour the doc describes, asserted directly."""

    def test_the_decorated_and_bare_forms_agree(self):
        self.assertEqual(opc.preflight_triage_model(LEGAL_CLASS),
                         opc.preflight_triage_model("legal"))

    def test_every_escalated_class_escalates(self):
        for name in opc.PREFLIGHT_ESCALATED_CLASSES:
            self.assertEqual(opc.preflight_triage_model(name),
                             opc.PREFLIGHT_ESCALATED_MODEL, name)

    def test_an_ordinary_class_takes_the_default(self):
        self.assertNotEqual(opc.preflight_triage_model(BUILD_CLASS),
                            opc.PREFLIGHT_ESCALATED_MODEL)

    def test_case_is_insignificant(self):
        self.assertEqual(opc.preflight_triage_model("LEGAL"),
                         opc.PREFLIGHT_ESCALATED_MODEL)

    def test_bad_input_takes_the_cheap_route_not_the_escalated_one(self):
        """Fail-soft toward the DEFAULT: an unparseable class is a caller bug, and
        escalating on every such call would turn that bug into unbounded spend."""
        for bad in (None, "", "   ", 7, [], {}):
            self.assertNotEqual(opc.preflight_triage_model(bad),
                                opc.PREFLIGHT_ESCALATED_MODEL, bad)

    def test_bad_input_never_raises(self):
        for bad in (None, 7, [], {}, object()):
            self.assertIsInstance(opc.preflight_triage_model(bad), str, bad)


class TestMarkdownIsWellFormed(unittest.TestCase):
    def test_headings_are_ordered(self):
        text = _doc_text()
        self.assertLess(text.index("# Orchestration pipeline contract"),
                        text.index("## Preflight Triage Model Selection Example"))

    def test_code_fences_are_balanced(self):
        self.assertEqual(_doc_text().count("```") % 2, 0, "unbalanced code fence")

    def test_the_table_rows_have_matching_column_counts(self):
        rows = [ln for ln in _doc_text().splitlines() if ln.strip().startswith("|")]
        self.assertTrue(rows)
        widths = {ln.count("|") for ln in rows}
        self.assertEqual(len(widths), 1, f"ragged markdown table: {widths}")


if __name__ == "__main__":
    unittest.main()
