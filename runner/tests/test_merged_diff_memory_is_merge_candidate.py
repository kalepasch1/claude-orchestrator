#!/usr/bin/env python3
"""Message-only merge gate for merged-diff memory: merged_diff_memory.is_merge_candidate.

The function decides whether a commit is worth extracting exemplars from BEFORE any
repository work happens, so its two expensive errors are opposite in kind:

  - a false NEGATIVE loses a real merge's lessons silently,
  - a false POSITIVE on a REVERT teaches the fleet the inverse of the lesson.

The revert cases below are therefore the load-bearing ones: a revert of a merge
contains a perfect merge subject verbatim, so anything that checks for merge phrases
before checking for a revert gets them wrong.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import merged_diff_memory as mdm


class IsMergeCandidateAcceptanceTest(unittest.TestCase):
    """The acceptance cases from the task spec, verbatim."""

    def test_true_cases(self):
        for msg in (
            "Merge pull request #123 from feature/foo",
            "Merge branch 'main' into develop",
            "Merge remote-tracking branch 'origin/release'",
        ):
            with self.subTest(msg=msg):
                self.assertTrue(mdm.is_merge_candidate(msg))

    def test_false_cases(self):
        for msg in (
            "Add new cache layer",
            'Revert "Merge pull request #123 from feature/foo"',
            "",
            "   ",
        ):
            with self.subTest(msg=msg):
                self.assertFalse(mdm.is_merge_candidate(msg))


class IsMergeCandidateRevertTest(unittest.TestCase):
    """A revert is not a merge, however merge-shaped its text is."""

    def test_revert_of_a_merge_branch_subject(self):
        self.assertFalse(mdm.is_merge_candidate("Revert \"Merge branch 'x' into main\""))

    def test_revert_anywhere_in_the_body_still_loses(self):
        self.assertFalse(
            mdm.is_merge_candidate(
                "Merge pull request #9 from hotfix\n\nThis reverts commit abc123."
            )
        )

    def test_revert_is_case_insensitive(self):
        self.assertFalse(mdm.is_merge_candidate("revert \"Merge branch 'x'\""))

    def test_reverted_word_form(self):
        self.assertFalse(mdm.is_merge_candidate("Merge branch 'x' (reverted later)"))


class IsMergeCandidateRealFleetSubjectsTest(unittest.TestCase):
    """Subjects this fleet actually produces, not invented ones."""

    def test_auto_conflict_resolver_subject(self):
        self.assertTrue(mdm.is_merge_candidate("Merge branch 'agent/x' (auto-resolved)"))

    def test_multiline_merge_train_body(self):
        self.assertTrue(
            mdm.is_merge_candidate(
                "release: batch train 2026-08-23\n\nMerge pull request #95 from agent/foo"
            )
        )

    def test_merge_tag_subject(self):
        self.assertTrue(mdm.is_merge_candidate("Merge tag 'v1.2.0' into master"))

    def test_lowercase_merge_prefix(self):
        self.assertTrue(mdm.is_merge_candidate("merge branch 'agent/y' into master"))

    def test_leading_whitespace_is_tolerated(self):
        self.assertTrue(mdm.is_merge_candidate("   Merge branch 'agent/z'"))


class IsMergeCandidateNonMergeTest(unittest.TestCase):
    """Ordinary commits stay out of merged-diff memory."""

    def test_plain_feature_commit(self):
        self.assertFalse(mdm.is_merge_candidate("feat: add fleet health badge"))

    def test_word_boundaries_are_respected(self):
        # 'submerged' and 'merger' contain the letters but are not the word.
        self.assertFalse(mdm.is_merge_candidate("fix: submerged log lines in the tail"))
        self.assertFalse(mdm.is_merge_candidate("docs: note the merger of two teams"))

    def test_hyphenated_forms_are_not_the_bare_word(self):
        self.assertFalse(mdm.is_merge_candidate("chore: rename merge-train config key"))


class IsMergeCandidateBadInputTest(unittest.TestCase):
    """Fail-soft: bad input returns False rather than raising, per repo convention."""

    def test_none(self):
        self.assertFalse(mdm.is_merge_candidate(None))

    def test_non_string_types(self):
        for bad in (0, 1, [], {}, object(), b"Merge branch 'x'"):
            with self.subTest(bad=type(bad).__name__):
                self.assertFalse(mdm.is_merge_candidate(bad))

    def test_whitespace_only_variants(self):
        for blank in ("", " ", "\t", "\n", "  \n\t "):
            with self.subTest(blank=repr(blank)):
                self.assertFalse(mdm.is_merge_candidate(blank))

    def test_returns_a_real_bool(self):
        # Callers persist this value; a truthy match object would serialize wrong.
        self.assertIsInstance(mdm.is_merge_candidate("Merge branch 'x'"), bool)
        self.assertIsInstance(mdm.is_merge_candidate("nope"), bool)


class IsMergeCandidateModuleContractTest(unittest.TestCase):
    """It is module-level and importable at the path the spec names."""

    def test_is_module_level_callable(self):
        self.assertTrue(callable(getattr(mdm, "is_merge_candidate", None)))

    def test_importable_by_name(self):
        from merged_diff_memory import is_merge_candidate  # noqa: F401

        self.assertTrue(is_merge_candidate("Merge branch 'x'"))


if __name__ == "__main__":
    unittest.main()
