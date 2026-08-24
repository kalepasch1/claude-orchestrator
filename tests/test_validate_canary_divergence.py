#!/usr/bin/env python3
"""Two functions named `validate_canary` exist. They now AGREE on the verdict.

    canary.validate_canary            word-boundary match (delegates), WARNING on a miss
    canary_validation.validate_canary word-boundary match (the definition), INFO on a miss

Before 2026-08-13 the first one matched on a substring, so `"precanary"` validated
through one import path and failed through the other — a canary hop could be reported
as both intact and broken depending on which module a caller happened to import. That
divergence was removed by making `canary.py` delegate.

This file pins the post-unification contract: the verdict must be identical through
either import, the two must remain distinct objects (delegation, not aliasing), and the
one remaining deliberate difference — log severity on a miss — must survive.
"""
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

from canary import validate_canary as substring_match  # noqa: E402
from canary_validation import validate_canary as word_boundary_match  # noqa: E402


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
    """What the two still do NOT share, after the 2026-08-13 unification.

    The matching rule is no longer one of them: `canary.validate_canary` now
    delegates to `canary_validation.validate_canary`, so both answer on a WORD
    BOUNDARY. This class used to pin the opposite (substring vs word boundary) and
    was left asserting a divergence the codebase had deliberately removed, so the
    suite failed on green code. The affixed cases are kept — inverted — because
    they are exactly where the old substring rule disagreed, and a regression back
    to `"canary" in text.lower()` must still fail loudly here.
    """

    AFFIXED = ["precanary build", "xcanary", "canaryish"]
    AFFIXED_WITH_SEPARATORS = ["my-canary-token", "canary_build", "build.canary"]

    def test_an_affixed_marker_is_rejected_by_both_implementations(self):
        for text in self.AFFIXED:
            self.assertFalse(substring_match(text),
                             f"canary.py must reject the affixed form {text!r}")
            self.assertFalse(word_boundary_match(text),
                             f"canary_validation.py must reject {text!r}")

    def test_separator_delimited_markers_are_accepted_by_both(self):
        """`-` and `.` are word boundaries; `_` is not. Pinned so the shared regex
        cannot be 'tidied' into something that changes a caller's verdict."""
        self.assertTrue(substring_match("my-canary-token"))
        self.assertTrue(word_boundary_match("my-canary-token"))
        self.assertTrue(substring_match("build.canary"))
        self.assertTrue(word_boundary_match("build.canary"))
        self.assertFalse(substring_match("canary_build"))
        self.assertFalse(word_boundary_match("canary_build"))

    def test_the_two_agree_on_every_affixed_case(self):
        """The unification's actual guarantee: no input may split the verdict."""
        for text in self.AFFIXED + self.AFFIXED_WITH_SEPARATORS:
            self.assertIs(substring_match(text), word_boundary_match(text),
                          f"import path must not change the verdict for {text!r}")

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
