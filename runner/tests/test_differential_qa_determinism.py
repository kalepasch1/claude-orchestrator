"""The QA waiver must depend on which tests failed, not on what order they finished in.

`differential_qa.compare` waives a red baseline only when every candidate failure
also appears in the baseline. It was fed the last 6000 characters of test output —
and `node --test` prints its failing-test summary in COMPLETION order, which is
nondeterministic under concurrency. The same tree run twice produced different
tails, different signature sets, and a waiver granted or refused essentially at
random. A whole family of otherwise-correct branches kept landing in TESTFAIL for
reasons unrelated to their content.

Two independent causes, both fixed and both covered here: the truncated tail, and
`signatures()` capping at 200 in ENCOUNTER order.
"""
import os
import random
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import differential_qa as dq        # noqa: E402
import merge_train                  # noqa: E402


def tap(names):
    """A TAP failing-test summary in the given order, as node --test emits it."""
    lines = ["TAP version 13"]
    for i, name in enumerate(names, start=1):
        lines.append(f"not ok {i} - {name}")
        lines.append("  ---")
        lines.append("  error: 'test failed'")
        lines.append("  ...")
    return "\n".join(lines)


REAL_37 = [f"suite{i // 4} > case {i} does the thing" for i in range(37)]


class IdentifiersAreOrderIndependent(unittest.TestCase):
    def test_same_failures_shuffled_give_the_same_identifier_set(self):
        a = tap(REAL_37)
        shuffled = REAL_37[:]
        random.Random(7).shuffle(shuffled)
        b = tap(shuffled)
        self.assertNotEqual(a, b, "precondition: the two logs really are different text")
        self.assertEqual(dq.test_identifiers(a), dq.test_identifiers(b))

    def test_compare_returns_the_same_verdict_for_either_ordering(self):
        # The acceptance case: two shuffled orderings of one failure set must not
        # produce different verdicts.
        base = tap(REAL_37)
        verdicts = set()
        for seed in range(6):
            shuffled = REAL_37[:]
            random.Random(seed).shuffle(shuffled)
            verdicts.add(dq.compare(tap(shuffled), base)["allowed"])
        self.assertEqual(verdicts, {True},
                         "the same failure set must be waived every time, not sometimes")

    def test_a_genuinely_new_failure_is_still_caught(self):
        # The waiver must stay narrow: order-independence is not permissiveness.
        base = tap(REAL_37)
        cand = tap(REAL_37 + ["suite9 > a brand new regression"])
        result = dq.compare(cand, base)
        self.assertFalse(result["allowed"])
        self.assertIn("a brand new regression", " ".join(result["new"]))

    def test_a_subset_of_the_baseline_is_waived(self):
        self.assertTrue(dq.compare(tap(REAL_37[:5]), tap(REAL_37))["allowed"])

    def test_identifiers_parse_the_common_runner_formats(self):
        self.assertIn("does a thing", dq.test_identifiers("not ok 3 - does a thing"))
        self.assertIn("renders the panel", dq.test_identifiers("  ✕ renders the panel 12 ms"))
        self.assertIn("renders the panel", dq.test_identifiers("  × renders the panel"))
        self.assertIn("tests/x.py::test_y", dq.test_identifiers("FAILED tests/x.py::test_y"))

    def test_identifiers_reject_lines_that_identify_nothing(self):
        for junk in ("FAIL", "not ok", "✕", "✕ 12", ""):
            self.assertEqual(dq.test_identifiers(junk), [], junk)

    def test_identifiers_are_sorted_and_deduplicated(self):
        ids = dq.test_identifiers(tap(["b test", "a test", "b test"]))
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), 2)

    def test_identifiers_never_raise(self):
        for junk in (None, 42, [], {}):
            self.assertEqual(dq.test_identifiers(junk), [])


class SurvivesTruncation(unittest.TestCase):
    def test_a_failure_beyond_the_6000_char_boundary_is_still_recognised(self):
        # The acceptance case. A failure buried under 20k of noise falls outside the
        # tail entirely; the identifier list is built from the full output first.
        noise = "\n".join(f"ok {i} - a passing test with a fairly long name" for i in range(400))
        full_stdout = tap(["the early failure nobody sees"]) + "\n" + noise
        self.assertGreater(len(full_stdout), 12000, "precondition: longer than two tails")
        self.assertNotIn("the early failure nobody sees", full_stdout[-6000:],
                         "precondition: it really is outside the tail")

        detail = merge_train._failure_detail(full_stdout, "")
        self.assertIn("the early failure nobody sees", detail)
        self.assertIn(merge_train.FAILED_TESTS_HEADER, detail)
        self.assertIn("the early failure nobody sees", " ".join(dq.test_identifiers(detail)))

    def test_the_human_readable_tail_is_still_there(self):
        # The identifier block is added, not substituted. A TESTFAIL is read by a
        # person who needs the actual error text.
        detail = merge_train._failure_detail(tap(["a failing case"]) + "\nAssertionError: 1 != 2", "")
        self.assertIn("AssertionError: 1 != 2", detail)

    def test_output_with_no_recognisable_ids_degrades_to_the_plain_tail(self):
        # tsc / lint / build output carries no test IDs. It must still be reported.
        detail = merge_train._failure_detail("src/x.ts(12,5): error TS2345: not assignable", "")
        self.assertIn("error TS2345", detail)
        self.assertNotIn(merge_train.FAILED_TESTS_HEADER, detail)

    def test_failure_detail_never_raises(self):
        for a, b in ((None, None), ("", ""), (None, "x")):
            self.assertIsInstance(merge_train._failure_detail(a, b), str)

    def test_a_detail_string_round_trips_through_compare(self):
        # End to end: what _run_tests stores must be comparable by compare().
        base = merge_train._failure_detail(tap(REAL_37), "")
        shuffled = REAL_37[:]
        random.Random(3).shuffle(shuffled)
        cand = merge_train._failure_detail(tap(shuffled), "")
        self.assertTrue(dq.compare(cand, base)["allowed"])
        self.assertEqual(dq.compare(cand, base).get("basis"), "test_identifiers")


class SignatureCapIsDeterministic(unittest.TestCase):
    def test_the_200_cap_no_longer_depends_on_encounter_order(self):
        # The second, quieter cause. signatures() kept the FIRST 200 in encounter
        # order, so which ones survived depended on runner ordering even when the
        # tail happened to contain everything.
        many = [f"error: failure number {i:04d} in some module" for i in range(300)]
        a = "\n".join(many)
        shuffled = many[:]
        random.Random(11).shuffle(shuffled)
        self.assertEqual(dq.signatures(a), dq.signatures("\n".join(shuffled)))
        self.assertEqual(len(dq.signatures(a)), 200)


class InfrastructureFailuresStillNeverWaived(unittest.TestCase):
    def test_an_infra_failure_is_refused_even_with_matching_identifiers(self):
        # The identifier path must not bypass the infra guard, which is the one
        # rule that exists to stop a broken environment reading as a known-red tree.
        log = tap(REAL_37) + "\nError: Cannot find module 'x'"
        self.assertFalse(dq.compare(log, log)["allowed"])


if __name__ == "__main__":
    unittest.main()
