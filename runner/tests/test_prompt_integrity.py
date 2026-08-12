"""Tests for prompt_integrity — the two quarantine causes it closes.

Measured over 7 days before this change:
    28 tasks  "GC: preflight: PATCH TEMPLATE or garbage prompt"
    87 tasks  "spec-lost: prompt overwritten with the stub"

Both were caught at PREFLIGHT, after the task existed and had burned a slot. The tests
below pin the two properties that move the catch to the write boundary:

  INSERT  the gate agrees with preflight, including on preamble-wrapped stubs, and does
          NOT false-positive on a long real prompt that quotes a template (that mistake
          cost 10 real 5 KB work prompts on 2026-07-31).
  UPDATE  a stub may not replace a real specification — but every other prompt write,
          and every write where the current prompt is unknown, still goes through.
"""
import os
import sys
import unittest

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import prompt_integrity as pi  # noqa: E402

REAL = ("## ORCHESTRATION PIPELINE CONTRACT\n- project: beethoven\n\n"
        "Implement the thing: add a bounded retry to the settlement reconciler and cover "
        "the failure path with a test that proves the second attempt is not issued after "
        "a terminal error.\n") * 3

STUB = "Complete the task 'some-slug'."


class StubTest(unittest.TestCase):
    def test_recognises_the_exact_stub(self):
        self.assertTrue(pi.is_stub(STUB))

    def test_recognises_it_without_the_period(self):
        self.assertTrue(pi.is_stub("Complete the task 'x'"))

    def test_tolerates_surrounding_whitespace(self):
        self.assertTrue(pi.is_stub("  Complete the task 'x'.  \n"))

    def test_real_prompt_is_not_a_stub(self):
        self.assertFalse(pi.is_stub(REAL))

    def test_a_prompt_that_merely_starts_that_way_is_not_a_stub(self):
        self.assertFalse(pi.is_stub(
            "Complete the task 'x'. Then also refactor the reconciler and add tests."))

    def test_none_and_empty_are_not_stubs(self):
        self.assertFalse(pi.is_stub(None))
        self.assertFalse(pi.is_stub(""))


class GarbageTest(unittest.TestCase):
    def test_empty_prompt(self):
        self.assertIn("empty", pi.garbage_reason(""))

    def test_trivial_prompt(self):
        self.assertIn("empty", pi.garbage_reason("do it"))

    def test_bare_patch_template(self):
        self.assertIn("PATCH TEMPLATE", pi.garbage_reason("PATCH TEMPLATE 4e4ada7eab9d"))

    def test_preamble_wrapped_patch_template_is_still_garbage(self):
        # THE INSERT GAP: startswith() missed this, because the filing paths PREPEND the
        # contract header. It reached preflight and was auto-quarantined there instead.
        wrapped = ("## ORCHESTRATION PIPELINE CONTRACT\n- project: beethoven\n\n"
                   "PATCH TEMPLATE 4e4ada7eab9d\n")
        self.assertIsNotNone(pi.garbage_reason(wrapped))

    def test_merged_diff_library_wrapped_stub_is_still_garbage(self):
        wrapped = "MERGED-DIFF LIBRARY: adapt proven prior diffs.\n\nPATCH TEMPLATE 7ba77da9\n"
        self.assertIsNotNone(pi.garbage_reason(wrapped))

    def test_long_real_prompt_quoting_a_template_is_NOT_garbage(self):
        # The false positive that cost 10 real 5 KB work prompts on 2026-07-31. A quoted
        # template deep inside a long body is evidence of reuse, not garbage.
        quoting = REAL + "\nPrior art: PATCH TEMPLATE 8f30996b38d4 was adapted here.\n" + REAL
        self.assertIsNone(pi.garbage_reason(quoting))

    def test_stub_is_garbage(self):
        self.assertIsNotNone(pi.garbage_reason(STUB))

    def test_error_only_prompt(self):
        self.assertIn("error", pi.garbage_reason(
            "Traceback (most recent call last):\nfatal: bad object\nError: nope"))

    def test_real_prompt_is_clean(self):
        self.assertIsNone(pi.garbage_reason(REAL))

    def test_none_is_garbage_not_a_crash(self):
        self.assertIsNotNone(pi.garbage_reason(None))


class StripPreambleTest(unittest.TestCase):
    def test_strips_contract_header(self):
        self.assertTrue(
            pi.strip_preamble("junk\n## TASK\nreal body").startswith("## TASK"))

    def test_strips_merged_diff_library_block(self):
        self.assertEqual(
            pi.strip_preamble("MERGED-DIFF LIBRARY: stuff\n\nreal body"), "real body")

    def test_leaves_a_plain_prompt_alone(self):
        self.assertEqual(pi.strip_preamble("plain body"), "plain body")

    def test_handles_none(self):
        self.assertEqual(pi.strip_preamble(None), "")


class UpdateTransitionTest(unittest.TestCase):
    """The 87-task cause: judged as a transition, never as a value."""

    def test_stub_over_a_real_spec_is_refused(self):
        why = pi.reject_reason_for_update(STUB, REAL)
        self.assertIsNotNone(why)
        self.assertIn("overwrite", why)

    def test_garbage_over_a_real_spec_is_refused(self):
        self.assertIsNotNone(
            pi.reject_reason_for_update("PATCH TEMPLATE 4e4ada7e", REAL))

    def test_substance_over_substance_is_allowed(self):
        self.assertIsNone(pi.reject_reason_for_update(REAL + "\nrefined", REAL))

    def test_stub_over_nothing_is_allowed(self):
        # Nothing to destroy. Unhelpful, but not the bug being fixed.
        self.assertIsNone(pi.reject_reason_for_update(STUB, ""))
        self.assertIsNone(pi.reject_reason_for_update(STUB, None))

    def test_stub_over_an_already_broken_prompt_is_allowed(self):
        self.assertIsNone(pi.reject_reason_for_update(STUB, "PATCH TEMPLATE 4e4ada7e"))

    def test_not_touching_the_prompt_is_allowed(self):
        self.assertIsNone(pi.reject_reason_for_update(None, REAL))

    def test_substance_over_a_stub_is_allowed(self):
        self.assertIsNone(pi.reject_reason_for_update(REAL, STUB))


class DbBoundaryWiringTest(unittest.TestCase):
    """The guards must actually be ON the two boundaries, not merely available."""

    def _db_source(self):
        with open(os.path.join(_DIR, "db.py")) as fh:
            return fh.read()

    def _update_body(self):
        src = self._db_source()
        start = src.index("def update(table, match, patch):")
        return src[start:start + 4000]

    def test_insert_gate_uses_the_shared_judgement(self):
        self.assertIn("prompt_integrity.reject_reason_for_insert", self._db_source())

    def test_update_path_guards_the_prompt(self):
        self.assertIn("prompt_integrity.reject_reason_for_update", self._update_body())

    def test_update_guard_drops_only_the_prompt_field(self):
        # Dropping the whole patch would strand the task instead of protecting it.
        body = self._update_body()
        self.assertIn('k != "prompt"', body)

    def test_update_guard_is_fail_open(self):
        body = self._update_body()
        self.assertIn("fail-open", body)


if __name__ == "__main__":
    unittest.main()
