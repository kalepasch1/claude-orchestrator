"""A named threshold is not a stubbed function.

stub_guard asks "does this declaration's body reduce to a literal". For a function
that is exactly right. For a constant it is exactly wrong: a threshold is SUPPOSED
to be a literal. Without the distinction the guard filed this, against smarter:

    CRITICAL: `REPLACEMENT_MARGIN` has a constant body `= 0.01`. Its NAME promises
    a computation, a price or an enforcement decision, so a constant body means the
    check no longer runs and the number is fabricated.

The declaration it was describing:

    /**
     * The margin a challenger must beat the incumbent by.
     * Not zero. With a strict-greater-than rule and a generator that produces
     * near-identical cells, the elite churns on floating-point noise forever...
     */
    export const REPLACEMENT_MARGIN = 0.01

...documented, and used one screen down in `score > incumbent.score + REPLACEMENT_MARGIN`.
Nothing had stopped running. The remediation the guard attached — "if it is
genuinely unimplemented it MUST throw" — would have replaced a live tunable with
an exception, so acting on the finding made the repository worse.

These tests pin the discriminator: decided on the DECLARATION, never the name, so
a stubbed arrow function with the same name is still caught.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stub_guard as g


class ValueConstantsAreNotStubs(unittest.TestCase):
    def test_a_named_numeric_threshold_is_a_constant(self):
        self.assertTrue(g.is_value_constant("export const REPLACEMENT_MARGIN = 0.01", "REPLACEMENT_MARGIN"))

    def test_a_typed_constant_is_a_constant(self):
        self.assertTrue(g.is_value_constant("export const SETTLEMENT_FEE: number = 2.5;", "SETTLEMENT_FEE"))

    def test_string_boolean_and_negative_values_are_constants(self):
        self.assertTrue(g.is_value_constant("export const TAX_MODE = 'gross'", "TAX_MODE"))
        self.assertTrue(g.is_value_constant("export const MARGIN_ENABLED = true", "MARGIN_ENABLED"))
        self.assertTrue(g.is_value_constant("export const EXPOSURE_FLOOR = -1.5", "EXPOSURE_FLOOR"))
        self.assertTrue(g.is_value_constant("export const RATE = 1e-6", "RATE"))


class CallablesAreStillCallables(unittest.TestCase):
    """The discriminator must not become a way to hide a stub behind `const`."""

    def test_a_stubbed_arrow_function_is_not_a_constant(self):
        self.assertFalse(g.is_value_constant("export const getPrice = () => 0", "getPrice"))

    def test_a_stubbed_function_expression_is_not_a_constant(self):
        self.assertFalse(
            g.is_value_constant("export const computeFee = function () { return 0 }", "computeFee"))

    def test_a_call_result_is_not_a_constant(self):
        self.assertFalse(g.is_value_constant("export const RATE = compute()", "RATE"))

    def test_an_object_literal_is_not_treated_as_a_value_constant(self):
        # Object stubs stay in scope: `= {}` from a pricing function is the classic shape.
        self.assertFalse(g.is_value_constant("export const PRICING = {}", "PRICING"))

    def test_a_plain_declaration_without_export_is_not_matched(self):
        self.assertFalse(g.is_value_constant("const MARGIN = 0.01", "MARGIN"))

    def test_missing_inputs_do_not_throw(self):
        self.assertFalse(g.is_value_constant("", "X"))
        self.assertFalse(g.is_value_constant("export const X = 1", ""))
        self.assertFalse(g.is_value_constant(None, None))


class ScanBehaviour(unittest.TestCase):
    """End to end through scan_fabricated, which is what files the tasks."""

    def _scan(self, source, name="admit.ts"):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(source)
            return g.scan_fabricated(d, files=[path])

    def test_the_documented_threshold_is_not_reported(self):
        src = (
            "/**\n * The margin a challenger must beat the incumbent by.\n */\n"
            "export const REPLACEMENT_MARGIN = 0.01\n\n"
            "export function admit(a: number, b: number) {\n"
            "  return a > b + REPLACEMENT_MARGIN\n"
            "}\n"
        )
        self.assertEqual([v["symbol"] for v in self._scan(src)], [])

    def test_a_genuinely_stubbed_critical_function_is_still_reported(self):
        src = "export function computeSettlementPrice(a: number) { return 0 }\n"
        found = [v["symbol"] for v in self._scan(src)]
        self.assertIn("computeSettlementPrice", found,
                      "the discriminator must not blind the guard to real stubs")

    def test_a_stubbed_arrow_with_a_critical_name_is_still_reported(self):
        src = "export const computeMargin = () => 0\n"
        found = [v["symbol"] for v in self._scan(src)]
        self.assertIn("computeMargin", found)

    def test_a_constant_and_a_stub_in_one_file_report_only_the_stub(self):
        src = (
            "export const REPLACEMENT_MARGIN = 0.01\n"
            "export function computeExposure() { return 0 }\n"
        )
        found = [v["symbol"] for v in self._scan(src)]
        self.assertEqual(found, ["computeExposure"])


class WorktreesAreNotScanned(unittest.TestCase):
    """The finding pointed into `.spine-wt/`, a gitignored git worktree.

    The fleet's convention is `{repo}-wt/{slug}` and projects keep scratch
    checkouts as `.<name>-wt/`. Both are working copies of code already scanned at
    its real path, so visiting them re-reports the same symbols through a path
    that exists on no branch — the task this test came from named a file that
    `git cat-file` cannot resolve.
    """

    def test_fleet_worktree_directories_are_skipped(self):
        for p in ("smarter/.spine-wt/packages/x/src/admit.ts",
                  "darwn/darwn-wt/some-slug/src/a.ts",
                  "repo/.runtime/integration-worktrees/x/a.ts"):
            self.assertTrue(g._SKIP_DIR.search(p), "%s should be skipped" % p)

    def test_ordinary_paths_are_still_scanned(self):
        for p in ("smarter/packages/corpus-lattice/src/admit.ts",
                  "runner/db.py",
                  "src/what-not/admit.ts"):
            self.assertFalse(g._SKIP_DIR.search(p), "%s must still be scanned" % p)


if __name__ == "__main__":
    unittest.main()
