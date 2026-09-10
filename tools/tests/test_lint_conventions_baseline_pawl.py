"""The convention-lint ratchet needs a pawl on --update-baseline.

Run: python3 -m pytest tools/tests/test_lint_conventions_baseline_pawl.py

The gate fails when a rule's count rises above the recorded baseline, which is
the right shape. But write_baseline() recorded whatever it was handed and
main() exited 0, so the single move that defeats the ratchet -- run
--update-baseline on a dirty tree -- was also the easiest one, and it
grandfathers the new violations permanently and silently.

The file it generates has always carried the sentence "never raise one to make
a commit pass". A sentence is not a check.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lint_conventions as lc  # noqa: E402


def baseline_file(counts):
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"counts": counts, "total": sum(counts.values())}, fh)
    return path


class TestRaisedRules(unittest.TestCase):
    def test_a_higher_count_on_a_known_rule_is_a_raise(self):
        self.assertEqual(
            lc.raised_rules({"FAIL_SOFT": 12}, {"FAIL_SOFT": 10}),
            [("FAIL_SOFT", 12, 10)])

    def test_an_equal_count_is_not_a_raise(self):
        self.assertEqual(lc.raised_rules({"FAIL_SOFT": 10},
                                         {"FAIL_SOFT": 10}), [])

    def test_a_lower_count_is_not_a_raise(self):
        self.assertEqual(lc.raised_rules({"FAIL_SOFT": 3},
                                         {"FAIL_SOFT": 10}), [])

    def test_a_rule_absent_from_the_baseline_is_not_a_raise(self):
        # A newly added rule has no ceiling to loosen; recording its count is
        # the only way to start ratcheting it.
        self.assertEqual(lc.raised_rules({"BRAND_NEW_RULE": 40}, {}), [])

    def test_multiple_raises_are_all_reported_sorted(self):
        rises = lc.raised_rules({"B": 5, "A": 9}, {"A": 1, "B": 1})
        self.assertEqual([r[0] for r in rises], ["A", "B"])


class TestWriteBaselineRefusesToLoosen(unittest.TestCase):
    def setUp(self):
        self.path = baseline_file({"FAIL_SOFT": 10, "SECRETS": 2})
        self.addCleanup(lambda: os.path.exists(self.path)
                        and os.unlink(self.path))

    def read(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)["counts"]

    def test_raising_is_refused(self):
        with self.assertRaises(lc.BaselineWouldRise) as ctx:
            lc.write_baseline({"FAIL_SOFT": 11, "SECRETS": 2}, path=self.path)
        self.assertEqual(ctx.exception.rises, [("FAIL_SOFT", 11, 10)])

    def test_a_refused_write_leaves_the_file_untouched(self):
        before = self.read()
        with self.assertRaises(lc.BaselineWouldRise):
            lc.write_baseline({"FAIL_SOFT": 99}, path=self.path)
        self.assertEqual(self.read(), before)

    def test_lowering_is_allowed(self):
        lc.write_baseline({"FAIL_SOFT": 4, "SECRETS": 2}, path=self.path)
        self.assertEqual(self.read()["FAIL_SOFT"], 4)

    def test_allow_raise_writes_it(self):
        lc.write_baseline({"FAIL_SOFT": 11, "SECRETS": 2}, path=self.path,
                          allow_raise=True)
        self.assertEqual(self.read()["FAIL_SOFT"], 11)

    def test_adding_a_new_rule_does_not_need_allow_raise(self):
        lc.write_baseline({"FAIL_SOFT": 10, "SECRETS": 2, "NEW": 7},
                          path=self.path)
        self.assertEqual(self.read()["NEW"], 7)

    def test_missing_baseline_file_writes_cleanly(self):
        os.unlink(self.path)
        payload = lc.write_baseline({"FAIL_SOFT": 3}, path=self.path)
        self.assertEqual(payload["counts"]["FAIL_SOFT"], 3)

    def test_generated_comment_no_longer_promises_what_it_cannot_enforce(self):
        payload = lc.write_baseline({"FAIL_SOFT": 1}, path=self.path)
        self.assertIn("--allow-raise", payload["_comment"])


if __name__ == "__main__":
    unittest.main()


class TestEmptyScanRefused(unittest.TestCase):
    """A zero-violation scan is not evidence that the tree is clean."""

    def setUp(self):
        self.path = baseline_file({"FAIL_SOFT": 10, "SECRETS": 2})
        self.addCleanup(lambda: os.path.exists(self.path)
                        and os.unlink(self.path))

    def read(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)["counts"]

    def test_empty_counts_over_a_real_baseline_are_refused(self):
        # Reproduced live while testing this change: passing a path that does
        # not exist warned "not a file or directory", then wrote a baseline of
        # 0 violations across 0 rules over the real one.
        with self.assertRaises(lc.EmptyScanRefused) as ctx:
            lc.write_baseline({}, path=self.path)
        self.assertEqual(ctx.exception.rule_count, 2)

    def test_the_real_baseline_survives_the_refusal(self):
        with self.assertRaises(lc.EmptyScanRefused):
            lc.write_baseline({}, path=self.path)
        self.assertEqual(self.read(), {"FAIL_SOFT": 10, "SECRETS": 2})

    def test_allow_raise_still_lets_a_deliberate_reset_through(self):
        lc.write_baseline({}, path=self.path, allow_raise=True)
        self.assertEqual(self.read(), {})

    def test_an_empty_scan_over_an_empty_baseline_is_fine(self):
        os.unlink(self.path)
        payload = lc.write_baseline({}, path=self.path)
        self.assertEqual(payload["counts"], {})
