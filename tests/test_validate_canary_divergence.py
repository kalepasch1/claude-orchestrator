#!/usr/bin/env python3
"""Two functions named `validate_canary` exist, and they must AGREE on the verdict.

    runner/canary.py            (metrics/canary server)
    runner/canary_validation.py (owner module)

THIS FILE ONCE SAID THE OPPOSITE. It was written to pin a deliberate divergence —
canary.py matched "canary" as a SUBSTRING, canary_validation.py on a WORD BOUNDARY — so
that a future "remove the duplicate" pass had to confront a failing test instead of
silently changing what a caller got.

That divergence has since been decided against, by
`tests/test_canary_validation_agreement.py`: a marker check whose whole job is to prove a
canary survived a pipeline hop must not depend on which import the caller reached for,
so all three entry points now match on a word boundary. This file was left behind
asserting the retired contract and had been failing ever since — a test that fails
because it describes a decision that was reversed teaches the next reader the wrong
thing about the system.

So it now pins the decision that was actually made: the two agree everywhere, INCLUDING
on the affixed forms that used to separate them. What remains genuinely different is
LOGGING SEVERITY on a miss — WARNING in canary.py, INFO in canary_validation.py — and
that IS still deliberate, because an operator greps for the warning. Those tests are
unchanged.
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


class AffixedFormTests(unittest.TestCase):
    """The cases that used to separate the two. They must now agree on all of them."""

    AFFIXED = ["precanary build", "xcanary", "canaryish", "my-canary-token"]

    def test_both_implementations_return_the_same_verdict_for_affixed_forms(self):
        for text in self.AFFIXED:
            self.assertIs(
                substring_match(text), word_boundary_match(text),
                f"the two entry points disagree about {text!r}; a marker check must not "
                f"depend on which import the caller reached for")

    def test_a_marker_glued_to_other_word_characters_is_rejected_everywhere(self):
        for text in ("precanary build", "xcanary", "canaryish"):
            self.assertFalse(substring_match(text), f"canary.py must reject {text!r}")
            self.assertFalse(word_boundary_match(text),
                             f"canary_validation.py must reject {text!r}")

    def test_a_hyphen_is_a_word_boundary_so_the_marker_still_counts(self):
        for text in ("my-canary-token", "canary-build", "build-canary"):
            self.assertTrue(substring_match(text), text)
            self.assertTrue(word_boundary_match(text), text)

    def test_the_two_functions_are_not_the_same_object(self):
        """Agreeing is not the same as being one function.

        They live in different modules with different logging contracts, so aliasing one
        to the other would silently change an operator's warning volume. Agreement is
        asserted by behaviour, never by identity.
        """
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
        """Deliberately INFO there — the ONE difference that survived the decision to
        converge, pinned so a consolidation cannot change an operator's warning volume
        by accident."""
        with self.assertLogs("canary_validation", level="INFO") as captured:
            self.assertFalse(word_boundary_match("nothing to see"))
        self.assertFalse(any(rec.startswith("WARNING") for rec in captured.output),
                         captured.output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
