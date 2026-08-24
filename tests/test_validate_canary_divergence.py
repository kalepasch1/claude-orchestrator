#!/usr/bin/env python3
"""Two functions named `validate_canary` exist, and they now AGREE on the verdict.

    canary.validate_canary            delegates; WARNING on a miss
    canary_validation.validate_canary word-boundary match, INFO on a miss

HISTORY, because this file used to assert the opposite. There were three copies of this
check and they disagreed: canary.py matched on a SUBSTRING, so "precanary" and "canaryX"
validated there and failed at the other two entry points — a canary hop could be reported
as both intact and broken depending on which import the caller happened to use. That was
unified on 2026-08-13: canary.validate_canary now DELEGATES to
canary_validation.validate_canary, so word-boundary matching is the single semantics.

This file was written before that unification and still pinned the divergence, so
`test_an_affixed_marker_is_a_match_only_for_the_substring_implementation` had been
FAILING on master ever since — asserting a behaviour the codebase deliberately removed. A
red test that demands a fixed defect back is worse than no test: the next agent to "make
the suite green" restores the split-brain. It now pins AGREEMENT on the verdict, which is
the contract that actually holds.

What still differs, and is still pinned below: the LOG SEVERITY on a miss (WARNING from
canary.py, INFO from canary_validation), and the fact that they remain two distinct
callables rather than one aliased to the other.
"""
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

from canary import validate_canary as canary_entry  # noqa: E402
from canary_validation import validate_canary as word_boundary_match  # noqa: E402


class AgreementTests(unittest.TestCase):
    """Where they agree, they must keep agreeing."""

    CASES = [
        ("canary", True),
        ("CANARY", True),
        ("this is a canary build", True),
        ("Canary marker present", True),
        # The case named by the task: an ordinary sentence carrying the marker.
        ("I found the canary in the coal mine.", True),
        ("no marker here", False),
        ("the canaries flew", False),   # 'canaries' is not the token 'canary'
        ("", False),
    ]

    def test_both_implementations_agree_on_the_ordinary_cases(self):
        for text, expected in self.CASES:
            self.assertIs(canary_entry(text), expected, f"canary.py: {text!r}")
            self.assertIs(word_boundary_match(text), expected,
                          f"canary_validation.py: {text!r}")

    def test_the_requested_sentence_validates(self):
        """The acceptance case, asserted on its own so a failure names it directly."""
        self.assertTrue(word_boundary_match("I found the canary in the coal mine."))
        self.assertTrue(canary_entry("I found the canary in the coal mine."))

    def test_the_return_value_is_a_real_bool(self):
        """A truthy match object would satisfy `if validate_canary(...)` and then fail
        a caller that serialises the result to JSON."""
        for text in ("a canary", "nothing"):
            self.assertIsInstance(word_boundary_match(text), bool)
            self.assertIsInstance(canary_entry(text), bool)

    def test_both_are_fail_soft_on_non_string_input(self):
        for bad in (None, 7, [], {}, object()):
            self.assertFalse(canary_entry(bad))
            self.assertFalse(word_boundary_match(bad))


class UnifiedSemanticsTests(unittest.TestCase):
    """The affixed forms: the exact cases the three copies used to disagree on."""

    AFFIXED = ["precanary build", "xcanary", "canaryish", "precanaryX"]

    def test_an_affixed_marker_is_rejected_by_both(self):
        for text in self.AFFIXED:
            self.assertFalse(word_boundary_match(text),
                             f"canary_validation.py must reject {text!r}")
            self.assertFalse(canary_entry(text),
                             f"canary.py must reject {text!r} after the unification")

    def test_a_hyphenated_marker_is_accepted_by_both(self):
        """A hyphen IS a word boundary, so this one is a match — and both must say so."""
        for text in ("my-canary-token", "canary-build"):
            self.assertTrue(word_boundary_match(text), text)
            self.assertTrue(canary_entry(text), text)

    def test_the_two_entry_points_never_disagree(self):
        """The property the unification exists to guarantee, stated once."""
        corpus = (list(AgreementTests.CASES)
                  + [(t, False) for t in self.AFFIXED]
                  + [("my-canary-token", True), ("canary.", True), ("(canary)", True)])
        for text, _expected in corpus:
            self.assertIs(canary_entry(text), word_boundary_match(text),
                          f"entry points disagree on {text!r}")

    def test_the_two_functions_are_not_the_same_object(self):
        """Guards against a 'deduplication' that aliases one to the other and so drops
        canary.py's WARNING-on-miss contract."""
        self.assertIsNot(canary_entry, word_boundary_match)


class LoggingContractTests(unittest.TestCase):
    """The remaining difference: severity on a miss. An operator grepping for warnings
    depends on canary.py logging WARNING, and on canary_validation not doing so."""

    def test_canary_py_logs_a_warning_when_the_marker_is_absent(self):
        with self.assertLogs("canary", level="WARNING") as captured:
            self.assertFalse(canary_entry("nothing to see"))
        self.assertTrue(any("NOT found" in line for line in captured.output),
                        captured.output)

    def test_canary_py_logs_info_when_the_marker_is_present(self):
        with self.assertLogs("canary", level="INFO") as captured:
            self.assertTrue(canary_entry("a canary"))
        self.assertTrue(any("found" in line for line in captured.output))

    def test_canary_py_warns_on_non_string_input(self):
        with self.assertLogs("canary", level="WARNING"):
            self.assertFalse(canary_entry(None))

    def test_canary_validation_does_not_warn_on_a_miss(self):
        """Deliberately INFO there — pinned so a consolidation cannot change an
        operator's warning volume by accident."""
        with self.assertLogs("canary_validation", level="INFO") as captured:
            self.assertFalse(word_boundary_match("nothing to see"))
        self.assertFalse(any(rec.startswith("WARNING") for rec in captured.output),
                         captured.output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
