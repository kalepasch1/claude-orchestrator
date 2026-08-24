#!/usr/bin/env python3
"""Two functions named `validate_canary` exist. They now AGREE on the verdict.

    canary.validate_canary            delegates -> word-boundary match, WARNING on a miss
    canary_validation.validate_canary word-boundary match, INFO on a miss

HISTORY, AND WHY THIS FILE CHANGED. It was written when the two disagreed: canary.py
matched on a SUBSTRING, so "precanary" and "canaryX" validated there and failed at the
other two entry points. That is the worst possible shape for a marker check — its whole
job is to confirm a canary survived a pipeline hop, and it returned a different verdict
depending on which import path the caller happened to use. canary.py was unified on
2026-08-13 to delegate to canary_validation, and its own docstring records the reasoning.

This file kept asserting the REMOVED behaviour ("canary.py must accept the affixed form
'precanary build'"), so it has been failing ever since — a test demanding a bug be
restored. The divergence tests are re-pointed at what is now true: the two agree on every
verdict, INCLUDING affixed forms, and remain distinct callables with different logging
severities. The severity difference is real and load-bearing (an operator greps canary.py
warnings), so it is still pinned.
"""
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

from canary import validate_canary as canary_entry  # noqa: E402
from canary_validation import validate_canary as word_boundary_match  # noqa: E402

#: Kept as an alias so the name used throughout this file still reads at every call site.
#: It is NO LONGER a substring matcher — see the module docstring.
substring_match = canary_entry


class AgreementTests(unittest.TestCase):
    """Where they agree, they must keep agreeing."""

    CASES = [
        ("canary", True),
        ("CANARY", True),
        ("this is a canary build", True),
        ("Canary marker present", True),
        ("no marker here", False),
        ("the canaries flew", False),   # 'canaries' does not contain 'canary'
        ("", False),
    ]

    def test_both_implementations_agree_on_the_ordinary_cases(self):
        for text, expected in self.CASES:
            self.assertIs(substring_match(text), expected, f"canary.py: {text!r}")
            self.assertIs(word_boundary_match(text), expected,
                          f"canary_validation.py: {text!r}")

    def test_both_are_fail_soft_on_non_string_input(self):
        for bad in (None, 7, [], {}, object()):
            self.assertFalse(substring_match(bad))
            self.assertFalse(word_boundary_match(bad))


class AffixedFormTests(unittest.TestCase):
    """The cases that USED to diverge, and must now give one answer.

    A marker check whose verdict depends on the import path is worse than a wrong
    verdict: a pipeline hop could be reported as both intact and broken, and neither
    answer was flagged because each copy was self-consistent.
    """

    #: 'my-canary-token' is a word-boundary match — '-' is not a word character — so it
    #: was never part of the disagreement. The other three are the real affixed forms.
    AFFIXED_NO_BOUNDARY = ["precanary build", "xcanary", "canaryish"]
    AFFIXED_WITH_BOUNDARY = ["my-canary-token"]

    def test_an_affixed_marker_without_a_word_boundary_is_rejected_by_both(self):
        for text in self.AFFIXED_NO_BOUNDARY:
            self.assertFalse(word_boundary_match(text),
                             f"canary_validation.py must reject {text!r}")
            self.assertFalse(canary_entry(text),
                             f"canary.py must reject {text!r} since it delegates")

    def test_a_delimited_marker_is_accepted_by_both(self):
        for text in self.AFFIXED_WITH_BOUNDARY:
            self.assertTrue(word_boundary_match(text))
            self.assertTrue(canary_entry(text))

    def test_the_two_entry_points_never_disagree(self):
        """The property the unification exists to guarantee."""
        for text in (self.AFFIXED_NO_BOUNDARY + self.AFFIXED_WITH_BOUNDARY
                     + ["canary", "CANARY", "the canaries flew", "", "no marker"]):
            self.assertIs(canary_entry(text), word_boundary_match(text),
                          f"entry points disagree on {text!r}")

    def test_the_two_functions_are_not_the_same_object(self):
        """They share a verdict, not an identity: canary.py keeps its own logging."""
        self.assertIsNot(canary_entry, word_boundary_match)


class LoggingContractTests(unittest.TestCase):
    """The other difference: severity on a miss. The task spec requires WARNING for
    canary.py, and an operator grepping for warnings depends on it."""

    def test_canary_py_logs_a_warning_when_the_marker_is_absent(self):
        with self.assertLogs("canary", level="WARNING") as captured:
            self.assertFalse(substring_match("nothing to see"))
        self.assertTrue(any("NOT found" in line for line in captured.output),
                        captured.output)

    def test_canary_py_logs_info_when_the_marker_is_present(self):
        with self.assertLogs("canary", level="INFO") as captured:
            self.assertTrue(substring_match("a canary"))
        self.assertTrue(any("found" in line for line in captured.output))

    def test_canary_py_warns_on_non_string_input(self):
        with self.assertLogs("canary", level="WARNING"):
            self.assertFalse(substring_match(None))

    def test_canary_validation_does_not_warn_on_a_miss(self):
        """Deliberately INFO there — this is the second divergence, pinned so a
        consolidation cannot change an operator's warning volume by accident."""
        with self.assertLogs("canary_validation", level="INFO") as captured:
            self.assertFalse(word_boundary_match("nothing to see"))
        self.assertFalse(any(rec.startswith("WARNING") for rec in captured.output),
                         captured.output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
