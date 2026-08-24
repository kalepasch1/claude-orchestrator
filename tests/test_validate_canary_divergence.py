#!/usr/bin/env python3
"""Two functions named `validate_canary` exist. They now agree on the VERDICT and
still differ on LOG SEVERITY.

    canary.validate_canary            word-boundary match, WARNING on a miss
    canary_validation.validate_canary word-boundary match, INFO on a miss

HISTORY (2026-08-13 unification): canary.py used to match on a bare SUBSTRING, so
"precanary" validated there and failed at the other entry point — the same hop could be
reported as both intact and broken depending on the import path. canary.py now delegates
to canary_validation, and this file pins that convergence: an affixed marker must be
rejected by BOTH. The severity difference is deliberate and is still pinned below,
because an operator grepping for warnings depends on it.
"""
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

from canary import validate_canary as canary_py_match  # noqa: E402
from canary_validation import validate_canary as word_boundary_match  # noqa: E402

# Kept so the historical name in this file still reads: both are word-boundary now.
substring_match = canary_py_match


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


class DivergenceTests(unittest.TestCase):
    """What used to diverge, and what still does."""

    # No word boundary around the marker — rejected by BOTH since the unification.
    AFFIXED = ["precanary build", "xcanary", "canaryish"]
    # A hyphen IS a word boundary, so this one is a match for both.
    DELIMITED = ["my-canary-token"]

    def test_an_affixed_marker_is_now_rejected_by_both_implementations(self):
        """Regression pin for the 2026-08-13 unification: canary.py no longer
        substring-matches, so the two entry points cannot disagree about a hop."""
        for text in self.AFFIXED:
            self.assertFalse(canary_py_match(text),
                             f"canary.py must reject the affixed form {text!r}")
            self.assertFalse(word_boundary_match(text),
                             f"canary_validation.py must reject {text!r}")

    def test_a_delimited_marker_is_accepted_by_both(self):
        for text in self.DELIMITED:
            self.assertTrue(canary_py_match(text), f"canary.py: {text!r}")
            self.assertTrue(word_boundary_match(text), f"canary_validation.py: {text!r}")

    def test_an_affixed_marker_without_a_word_boundary_is_rejected_by_the_other(self):
        for text in ("precanary build", "xcanary", "canaryish"):
            self.assertFalse(word_boundary_match(text),
                             f"canary_validation.py must reject {text!r}")

    def test_the_two_functions_are_not_the_same_object(self):
        """Guards against a 'deduplication' that aliases one to the other."""
        self.assertIsNot(substring_match, word_boundary_match)


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
