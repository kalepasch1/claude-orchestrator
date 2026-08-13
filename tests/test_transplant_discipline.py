#!/usr/bin/env python3
"""Wave C, Part 4 — the codegen disciplines, held in place.

Each test pins one clause of the spec that was previously prose:
  "merged-diff library at the raised 0.55 similarity; never grow tumors; contract-first
   generation (emit failing test + type signatures first) — the verify gate IS the spec"
"""
import os
import sys
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import transplant_discipline as td  # noqa: E402


class SimilarityFloorTests(unittest.TestCase):
    def test_the_floor_is_the_spec_value(self):
        self.assertEqual(td.MIN_TRANSPLANT_SIMILARITY, 0.55)

    def test_a_weak_match_is_inadmissible(self):
        """0.309 is a real observed value from a queued prompt — it must not transplant."""
        self.assertFalse(td.transplant_admissible(0.309))
        self.assertFalse(td.transplant_admissible(0.18))
        self.assertFalse(td.transplant_admissible(0.25))

    def test_a_strong_match_is_admissible(self):
        self.assertTrue(td.transplant_admissible(0.55))
        self.assertTrue(td.transplant_admissible(0.9))

    def test_rejection_states_the_cost_not_just_the_number(self):
        reason = td.rejection_reason(0.309)
        self.assertIn("0.309", reason)
        self.assertIn("0.55", reason)
        self.assertIn("unmergeable", reason)

    def test_an_admissible_candidate_has_no_rejection_reason(self):
        self.assertEqual(td.rejection_reason(0.8), "")

    def test_missing_or_junk_similarity_is_inadmissible_not_crashing(self):
        for value in (None, "", "abc", [], {}):
            self.assertFalse(td.transplant_admissible(value), repr(value))

    def test_an_explicit_floor_overrides_the_default(self):
        self.assertTrue(td.transplant_admissible(0.3, floor=0.25))
        self.assertFalse(td.transplant_admissible(0.3, floor=0.9))


class PatchTransplantWiringTests(unittest.TestCase):
    """The floor must be unbypassable through the real entry points."""

    def test_hint_suppresses_a_weak_match(self):
        import merged_diff_library
        import patch_transplant
        real = merged_diff_library.find
        merged_diff_library.find = lambda task, limit=1: [{
            "similarity": 0.309, "project": "beethoven", "slug": "deployfix-x",
            "summary": "s", "diff": "d",
        }]
        try:
            self.assertEqual(patch_transplant.hint({"prompt": "do a thing"}), "")
        finally:
            merged_diff_library.find = real

    def test_hint_emits_for_a_strong_match(self):
        import merged_diff_library
        import patch_transplant
        real = merged_diff_library.find
        merged_diff_library.find = lambda task, limit=1: [{
            "similarity": 0.71, "project": "beethoven", "slug": "relfix-y",
            "summary": "s", "diff": "d",
        }]
        try:
            self.assertIn("PATCH TRANSPLANT", patch_transplant.hint({"prompt": "do a thing"}))
        finally:
            merged_diff_library.find = real

    def test_both_transplant_paths_now_share_one_floor(self):
        import inspect
        import patch_transplant
        default = inspect.signature(
            patch_transplant.find_transplant_source).parameters["min_similarity"].default
        self.assertIsNone(default, "the second path must defer to the shared floor, not carry "
                                   "its own hardcoded 0.25")

    def test_find_transplant_source_rejects_a_weak_row(self):
        import db
        import patch_transplant
        real = db.select
        db.select = lambda table, params=None: [{"slug": "s", "similarity": 0.3}]
        try:
            self.assertIsNone(patch_transplant.find_transplant_source({}))
        finally:
            db.select = real

    def test_find_transplant_source_accepts_a_strong_row(self):
        import db
        import patch_transplant
        real = db.select
        db.select = lambda table, params=None: [{"slug": "s", "similarity": 0.8}]
        try:
            self.assertEqual(patch_transplant.find_transplant_source({})["slug"], "s")
        finally:
            db.select = real


ORGAN_DIFF = """\
--- a/mod.py
+++ b/mod.py
-def compute(x):
-    return x
+def compute(x, y):
+    return x + y
"""

TUMOR_DIFF = """\
--- a/mod.py
+++ b/mod.py
+def compute(x, y):
+    return x + y
+
"""

SELF_DUPLICATING_DIFF = """\
--- a/mod.py
+++ b/mod.py
+def handle(a):
+    return a
+def handle(a):
+    return a
"""


class TumorTests(unittest.TestCase):
    def test_a_replacement_is_an_organ(self):
        result = td.tumor_check(ORGAN_DIFF, existing_symbols={"compute"})
        self.assertFalse(result["tumor"])

    def test_an_additive_redeclaration_is_a_tumor(self):
        result = td.tumor_check(TUMOR_DIFF, existing_symbols={"compute"})
        self.assertTrue(result["tumor"])
        self.assertEqual(result["duplicated"], ["compute"])
        self.assertIn("two implementations", result["reason"])

    def test_the_tumor_reason_names_why_tests_still_pass(self):
        self.assertIn("every test still passes",
                      td.tumor_check(TUMOR_DIFF, existing_symbols={"compute"})["reason"])

    def test_a_diff_that_duplicates_a_symbol_within_itself_is_a_tumor(self):
        result = td.tumor_check(SELF_DUPLICATING_DIFF)
        self.assertTrue(result["tumor"])
        self.assertEqual(result["duplicated"], ["handle"])

    def test_genuinely_new_code_is_not_a_tumor(self):
        result = td.tumor_check(TUMOR_DIFF, existing_symbols={"something_else"})
        self.assertFalse(result["tumor"])

    def test_added_and_removed_lines_are_counted(self):
        result = td.tumor_check(ORGAN_DIFF, existing_symbols={"compute"})
        self.assertGreater(result["added"], 0)
        self.assertGreater(result["removed"], 0)

    def test_a_redeclaration_alongside_deletions_is_flagged_for_review_not_blocked(self):
        diff = ORGAN_DIFF + "+def compute(x, y, z):\n+    return 0\n"
        result = td.tumor_check(diff, existing_symbols={"compute"})
        self.assertFalse(result["tumor"], "a diff that also deletes must not be auto-blocked")
        self.assertIn("review", result["reason"])

    def test_typescript_and_javascript_declarations_are_recognised(self):
        diff = "+export function build(a) {\n+  return a\n+}\n"
        self.assertTrue(td.tumor_check(diff, existing_symbols={"build"})["tumor"])

    def test_junk_input_is_never_called_a_tumor(self):
        for value in (None, "", 42, [], {}):
            self.assertFalse(td.tumor_check(value)["tumor"], repr(value))


class ContractFirstGateTests(unittest.TestCase):
    def test_a_complete_contract_passes(self):
        result = td.contract_first_gate({
            "failing_test": "assert compute(1, 2) == 3",
            "signatures": ["def compute(x: int, y: int) -> int"],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing"], [])

    def test_a_spec_with_no_test_is_blocked(self):
        result = td.contract_first_gate({"signatures": ["def f() -> None"]})
        self.assertFalse(result["ok"])
        self.assertIn("failing_test", result["missing"])
        self.assertIn("the verify gate IS the spec", result["reason"])

    def test_a_spec_with_no_signatures_is_blocked(self):
        result = td.contract_first_gate({"failing_test": "assert f()"})
        self.assertFalse(result["ok"])
        self.assertIn("signatures", result["missing"])

    def test_a_test_that_already_passes_is_not_a_contract(self):
        """A contract must fail before the implementation exists, or it constrains nothing."""
        result = td.contract_first_gate({
            "failing_test": "assert True",
            "signatures": ["def f() -> None"],
            "test_currently_passes": True,
        })
        self.assertFalse(result["ok"])
        self.assertIn("constrains nothing", result["reason"])

    def test_an_empty_spec_names_both_gaps(self):
        self.assertEqual(td.contract_first_gate({})["missing"], ["failing_test", "signatures"])

    def test_a_whitespace_only_test_does_not_count(self):
        result = td.contract_first_gate({"failing_test": "   ", "signatures": ["x"]})
        self.assertFalse(result["ok"])

    def test_junk_specs_are_blocked_rather_than_crashing(self):
        for value in (None, "string", 42, []):
            self.assertFalse(td.contract_first_gate(value)["ok"], repr(value))


class RenderTests(unittest.TestCase):
    def test_a_blocked_gate_says_blocked(self):
        text = td.render(gate_result=td.contract_first_gate({}))
        self.assertIn("BLOCKED", text)

    def test_a_tumor_is_named_in_the_summary(self):
        text = td.render(diff_result=td.tumor_check(TUMOR_DIFF, existing_symbols={"compute"}))
        self.assertIn("TUMOR", text)

    def test_render_is_fail_soft(self):
        self.assertIsInstance(td.render(), str)
        self.assertIsInstance(td.render(None, None), str)


if __name__ == "__main__":
    unittest.main()
