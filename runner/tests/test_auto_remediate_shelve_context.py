"""Shelving must fail gracefully WITHOUT dropping the error context.

Shelving is the end of the automated line: after repeated remediations the task
stops looping and waits for a human, and the note is the only thing that human
gets. The existing shelve test asserts state == "SHELVED" and nothing else, so
two real losses went uncovered:

  * the terminal error lives in `log_tail`, not `note`. run() builds
    `signal = note + log_tail` for pattern matching, but only `note` reached the
    shelved row — so "terminal_reason: max_turns" never survived the shelve.
  * `(prefix + note)[:500]` let a long accumulated note push everything past the
    cap and cut mid-word, with nothing to indicate the note was clipped.

These exercise auto_remediate._shelve_note directly rather than driving run().
run() performs live selects around the shelve branch, so a test that goes
through it is measuring the network, not the note — the existing suite already
covers the state transition itself.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auto_remediate

NOTE = "auto-decomposed from big-feature; quality gate: still failing"
TAIL = "terminal_reason: max_turns after 15 turns; last tool call timed out"


class TestShelveKeepsErrorContext(unittest.TestCase):
    def test_the_terminal_error_reaches_the_shelved_note(self):
        # The regression: log_tail carried the reason and never made it in.
        out = auto_remediate._shelve_note(6, NOTE, TAIL)
        self.assertIn("max_turns", out)
        self.assertIn("last error:", out)

    def test_the_original_note_and_prefix_are_still_present(self):
        out = auto_remediate._shelve_note(6, NOTE, TAIL)
        self.assertIn("shelved after 6 remediations", out)
        self.assertIn("quality gate", out)

    def test_a_long_note_cannot_evict_the_error_metadata(self):
        # Notes accumulate across remediations; the evidence must not be what falls off.
        out = auto_remediate._shelve_note(6, "x" * 4000, TAIL)
        self.assertLessEqual(len(out), 500)
        self.assertIn("max_turns", out)
        self.assertTrue(out.rstrip().endswith("timed out"))

    def test_a_clipped_note_is_visibly_clipped(self):
        out = auto_remediate._shelve_note(6, "y" * 4000, TAIL)
        self.assertIn("…", out, "truncation must be signalled, not silent")

    def test_a_long_tail_is_clipped_from_the_front_keeping_the_end(self):
        # The end of a log tail is where the failure is; keep that half.
        out = auto_remediate._shelve_note(6, NOTE, "noise " * 200 + "FINAL: unbuildable")
        self.assertLessEqual(len(out), 500)
        self.assertIn("FINAL: unbuildable", out)

    def test_no_log_tail_degrades_to_the_old_shape(self):
        out = auto_remediate._shelve_note(6, NOTE, None)
        self.assertLessEqual(len(out), 500)
        self.assertIn("shelved after", out)
        self.assertIn("quality gate", out)
        self.assertNotIn("last error:", out)

    def test_newlines_in_the_tail_are_flattened(self):
        # The note is a single-line field; a raw multi-line tail renders badly.
        out = auto_remediate._shelve_note(6, NOTE, "line one\nline two\n\tindented")
        self.assertNotIn("\n", out)
        self.assertIn("line one line two indented", out)

    def test_bounded_for_pathological_input(self):
        out = auto_remediate._shelve_note(9, "n" * 10000, "t" * 10000)
        self.assertLessEqual(len(out), 500)
        self.assertIn("last error:", out)

    def test_empty_inputs_are_fail_soft(self):
        self.assertLessEqual(len(auto_remediate._shelve_note(0, "", "")), 500)
        self.assertLessEqual(len(auto_remediate._shelve_note(0, None, None)), 500)


class TestShelveBranchStillUsesTheHelper(unittest.TestCase):
    def test_the_shelve_branch_calls_the_helper(self):
        # Guards against the helper being added and then bypassed by a later edit.
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "auto_remediate.py"), encoding="utf-8").read()
        self.assertIn('"state": "SHELVED"', src)
        shelve_at = src.index('"state": "SHELVED"')
        window = src[shelve_at:shelve_at + 240]
        self.assertIn("_shelve_note(", window)


if __name__ == "__main__":
    unittest.main()
