"""The public-copy gate must not flag the inside of a block comment.

Apparently release ce3433f9 was blocked by this: line 5 of
app/components/one-apparently/BenchReviewedSeal.vue is the middle of an HTML
comment reading "...the internal engine id (CADE) never surfaces here" — a
comment whose whole purpose is to state the rule the guard enforces. The guard
recognised comments only by how a line STARTS, so it flagged the documentation
of its own rule and stopped a release.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import public_copy_guard as g  # noqa: E402

SEAL_HEADER = [
    "<!--",
    "  one-apparently 14.3 - the Bench-reviewed seal. Renders on a deliverable and",
    "  deep-links to the review record (Risk Lineage). User-facing name is always",
    "  'The Bench'; the internal engine id (CADE) never surfaces here. All non-trivial",
    "  logic lives in the tested helpers benchSealLabel / benchReviewHref.",
    "-->",
]

PATH = "app/components/one-apparently/BenchReviewedSeal.vue"


class BlockCommentTests(unittest.TestCase):
    def test_the_exact_line_that_blocked_ce3433f9_is_not_flagged(self):
        lines = list(enumerate(SEAL_HEADER, start=1))
        self.assertEqual(g.scan_lines(PATH, lines), [])

    def test_mask_marks_the_body_of_an_html_comment_and_nothing_after(self):
        mask = g._block_comment_mask(SEAL_HEADER + ["<p>Real CADE copy</p>"])
        self.assertEqual(mask[0], False, "the opener line is handled by IGNORED_LINE_RE")
        self.assertEqual(mask[1:5], [True] * 4, "every middle line is comment body")
        self.assertEqual(mask[5], True, "the closing --> line is still inside")
        self.assertEqual(mask[6], False, "copy after the comment is scanned again")

    def test_mask_handles_c_style_blocks(self):
        mask = g._block_comment_mask(
            ["/*", "  describes CADE internals", "*/", "const x = 'CADE'"])
        self.assertEqual(mask, [False, True, True, False])

    def test_single_line_block_does_not_leak_state(self):
        mask = g._block_comment_mask(["<!-- inline -->", "<p>Powered by CADE</p>"])
        self.assertEqual(mask, [False, False])

    def test_real_public_copy_is_still_flagged(self):
        """The fix must not become a hole. Ordinary copy is still scanned."""
        lines = [(1, '  <p>Powered by our CADE engine and hivemind routing.</p>')]
        findings = g.scan_lines(PATH, lines)
        self.assertTrue(findings)
        self.assertEqual(findings[0]["rule"], "proprietary_mechanism")

    def test_copy_merely_lacking_a_comment_marker_is_still_scanned(self):
        self.assertFalse(g._is_block_comment_body("  Powered by the CADE engine."))
        self.assertFalse(g._is_block_comment_body(""))
        self.assertFalse(g._is_block_comment_body(None))

    def test_single_line_comment_forms_still_ignored(self):
        for raw in ("// CADE is the engine", "/* CADE */", " * CADE", "<!-- CADE -->"):
            self.assertEqual(g.scan_lines(PATH, [(1, raw)]), [], raw)

    def test_non_public_paths_are_untouched(self):
        lines = [(1, '  <p>Powered by our CADE engine.</p>')]
        self.assertEqual(g.scan_lines("runner/internal_notes.ts", lines), [])


if __name__ == "__main__":
    unittest.main()
