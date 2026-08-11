#!/usr/bin/env python3
"""Tests for runner/patch_template_structure.py — shape observation only."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_template_structure as pts

CANONICAL = """PATCH TEMPLATE 918597e30434
Intent: session recon slice adapt prior patch template
Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.
Implementation slots:
1. Locate the existing owner module/function before adding new files.
2. Reuse matching project helpers and naming conventions.
3. Add or update the narrowest test/check that proves the requested behavior.
Prior merged patterns to adapt:
- smarter/cont-1042d0 sim=0.41: reuse the existing continuation compactor
- beethoven/relfix-07071626 sim=0.33: relfix branch recovery
[patch-template:918597e30434]
"""

NO_MARKER = """PATCH TEMPLATE abc123def456
Intent: something
Implementation slots:
1. do the thing
"""

MISMATCHED = """PATCH TEMPLATE aaaaaaaaaaaa
Intent: drift
Implementation slots:
1. one
[patch-template:bbbbbbbbbbbb]
"""

HEX_STUB = "deadbeefcafe0123456789abcdef0123456789abcdef\n0123456789abcdef\n"

WITH_COMMIT = """PATCH TEMPLATE 0f0f0f0f0f0f
Intent: commit shape
Implementation slots:
1. commit as: agent: my-task-slug
# keep the diff small
"""


class TestText(unittest.TestCase):
    def test_coercion(self):
        self.assertEqual(pts._text(b"abc"), "abc")
        self.assertEqual(pts._text(None), "")
        self.assertEqual(pts._text(7), "7")


class TestObserveCanonical(unittest.TestCase):
    def setUp(self):
        self.obs = pts.observe(CANONICAL)

    def test_prefix_and_id(self):
        self.assertEqual(self.obs["header_prefix"], "PATCH TEMPLATE <id>")
        self.assertEqual(self.obs["template_id"], "918597e30434")

    def test_suffix_marker_agrees_with_header(self):
        self.assertEqual(self.obs["marker_suffix"], "[patch-template:<id>]")
        self.assertTrue(self.obs["marker_matches_header"])

    def test_labels_and_sections_are_separated(self):
        self.assertIn("Intent", self.obs["labels"])
        self.assertIn("Acceptance", self.obs["labels"])
        # trailing-colon-only lines are sections, not labels
        self.assertIn("Implementation slots", self.obs["sections"])
        self.assertNotIn("Implementation slots", self.obs["labels"])

    def test_slot_numbering(self):
        self.assertEqual(self.obs["slot_count"], 3)
        self.assertEqual(self.obs["slot_numbering"], "sequential-from-1")
        self.assertTrue(self.obs["slots"][0].startswith("Locate the existing owner"))

    def test_prior_source_refs_and_similarity(self):
        self.assertEqual(self.obs["bullet_count"], 2)
        self.assertIn("smarter/cont-1042d0", self.obs["sources"])
        self.assertIn("beethoven/relfix-07071626", self.obs["sources"])
        self.assertEqual(self.obs["similarity_values"], ["0.41", "0.33"])

    def test_well_formed(self):
        self.assertTrue(self.obs["well_formed"])
        self.assertFalse(self.obs["is_hex_only_stub"])


class TestObserveDefects(unittest.TestCase):
    def test_missing_marker_is_reported(self):
        obs = pts.observe(NO_MARKER)
        self.assertEqual(obs["marker_suffix"], "")
        self.assertFalse(obs["marker_matches_header"])
        self.assertEqual(obs["template_id"], "abc123def456")

    def test_header_marker_drift_is_reported(self):
        obs = pts.observe(MISMATCHED)
        self.assertTrue(obs["marker_suffix"])
        self.assertFalse(obs["marker_matches_header"])

    def test_hex_only_stub_is_flagged_and_not_well_formed(self):
        obs = pts.observe(HEX_STUB)
        self.assertTrue(obs["is_hex_only_stub"])
        self.assertFalse(obs["well_formed"])

    def test_commit_message_format_detected(self):
        self.assertEqual(pts.observe(WITH_COMMIT)["commit_message_format"], "agent: <slug>")
        self.assertEqual(pts.observe(CANONICAL)["commit_message_format"], "none")

    def test_conventional_commit_with_scope(self):
        body = "PATCH TEMPLATE aaaaaa\nIntent: x\nSlots:\n1. commit\nfeat(intake): add gate\n"
        self.assertEqual(pts.observe(body)["commit_message_format"], "feat(intake): <subject>")

    def test_comment_style(self):
        self.assertEqual(pts.observe(WITH_COMMIT)["comment_style"], "hash")
        self.assertEqual(pts.observe(CANONICAL)["comment_style"], "none")
        js = "PATCH TEMPLATE aaaaaa\nIntent: x\n1. slot\n// note\n// note two\n"
        self.assertEqual(pts.observe(js)["comment_style"], "double-slash")


class TestSlotNumbering(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(pts._slot_numbering([]), "none")
        self.assertEqual(pts._slot_numbering([1, 2, 3]), "sequential-from-1")
        self.assertEqual(pts._slot_numbering([0, 1, 2]), "sequential-from-0")
        self.assertEqual(pts._slot_numbering([1, 3, 7]), "ascending-with-gaps")
        self.assertEqual(pts._slot_numbering([3, 1, 2]), "unordered")


class TestFailSoft(unittest.TestCase):
    def test_empty_and_bad_input(self):
        for bad in (None, "", "   ", 0, b"", [], {}):
            obs = pts.observe(bad)
            self.assertEqual(obs["line_count"], 0)
            self.assertFalse(obs["well_formed"])
            self.assertEqual(obs["labels"], [])

    def test_binary_input_does_not_raise(self):
        obs = pts.observe(b"\xff\xfe\x00binary")
        self.assertIsInstance(obs, dict)

    def test_report_on_empty_is_empty_list(self):
        self.assertEqual(pts.report(None), [])
        self.assertEqual(pts.report(""), [])


class TestReport(unittest.TestCase):
    def test_reports_prefix_suffix_slots_and_commit(self):
        lines = pts.report(CANONICAL)
        joined = "\n".join(lines)
        self.assertIn("prefix: first line is `PATCH TEMPLATE <id>`", joined)
        self.assertIn("suffix: trailing marker `[patch-template:<id>]`", joined)
        self.assertIn("agree", joined)
        self.assertIn("numbering=sequential-from-1", joined)
        self.assertIn("prior-source refs: smarter/cont-1042d0", joined)
        self.assertIn("well-formed: True", joined)

    def test_reports_missing_marker_explicitly(self):
        joined = "\n".join(pts.report(NO_MARKER))
        self.assertIn("no `[patch-template:<id>]` marker", joined)

    def test_reports_hex_stub_warning(self):
        self.assertIn("WARNING", "\n".join(pts.report(HEX_STUB)))

    def test_does_not_adapt_or_echo_intent_content(self):
        # analysis only: the report describes shape, not the template's subject matter
        joined = "\n".join(pts.report(CANONICAL))
        self.assertNotIn("session recon slice adapt", joined)


class TestCompare(unittest.TestCase):
    def test_identical_shapes_have_no_variance(self):
        result = pts.compare([CANONICAL, CANONICAL])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["varies"], [])
        self.assertEqual(result["common"]["header_prefix"], "PATCH TEMPLATE <id>")

    def test_drift_is_surfaced(self):
        result = pts.compare([CANONICAL, NO_MARKER])
        self.assertIn("marker_suffix", result["varies"])
        self.assertIn("slot_count", result["varies"])

    def test_empty_input_is_safe(self):
        for bad in (None, [], [""], [None]):
            self.assertEqual(pts.compare(bad)["count"], 0)


class TestAgainstLiveBuilder(unittest.TestCase):
    def test_current_builder_output_is_well_formed(self):
        try:
            import patch_templates
        except Exception:
            self.skipTest("patch_templates unavailable")
        _tid, body = patch_templates.build(
            {"slug": "structure-probe", "prompt": "add a webhook route and a schema migration"}
        )
        body += f"\n{patch_templates.MARK}{_tid}]"
        obs = pts.observe(body)
        self.assertTrue(obs["well_formed"], f"builder shape drifted: {pts.report(body)}")
        self.assertTrue(obs["marker_matches_header"])
        self.assertEqual(obs["slot_numbering"], "sequential-from-1")


if __name__ == "__main__":
    unittest.main()
