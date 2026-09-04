"""Branch-management dedup: exact duplicates, case, empty queue, and bad input.

The 15 cases below are the ones named for this slice. Two of them found a real
defect rather than confirming existing behaviour: normalize_slug() called
.lower() on whatever it was handed, so a None or non-string slug raised
AttributeError and took down the whole auto-queue pass — a fail-soft violation
per CLAUDE.md ("never raise on bad input"). It now normalises to "" instead.

The interesting design point is what an unusable slug should mean. is_duplicate()
returns False for it, NOT True: a "duplicate" verdict silently DROPS the row,
whereas letting it through surfaces the bad slug where someone can see it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auto_queue_branches as aqb


class TestExactDuplicates(unittest.TestCase):
    def test_1_identical_slug_is_a_duplicate(self):
        self.assertTrue(aqb.is_duplicate("fix-login", {"fix-login"}))

    def test_2_distinct_slug_is_not_a_duplicate(self):
        self.assertFalse(aqb.is_duplicate("fix-login", {"add-billing"}))

    def test_3_duplicate_is_found_anywhere_in_the_set(self):
        self.assertTrue(aqb.is_duplicate("fix-login", {"a", "b", "fix-login", "c"}))

    def test_4_version_suffixes_collapse_to_the_same_task(self):
        # agent/foo-v2 is a retry of foo, not new work.
        self.assertTrue(aqb.is_duplicate("fix-login-v2", {"fix-login"}))
        self.assertTrue(aqb.is_duplicate("fix-login", {"fix-login-v3"}))


class TestCaseAndWhitespace(unittest.TestCase):
    def test_5_case_differences_are_the_same_slug(self):
        self.assertTrue(aqb.is_duplicate("Fix-Login", {"fix-login"}))
        self.assertTrue(aqb.is_duplicate("FIX-LOGIN", {"fix-login"}))

    def test_6_surrounding_whitespace_is_ignored(self):
        self.assertTrue(aqb.is_duplicate("  fix-login  ", {"fix-login"}))

    def test_7_separator_style_does_not_matter(self):
        # underscores, spaces and hyphens all normalise to the same slug
        self.assertEqual(aqb.normalize_slug("Fix_Login Now"), "fix-login-now")
        self.assertTrue(aqb.is_duplicate("fix_login", {"fix-login"}))

    def test_8_leading_and_trailing_separators_are_trimmed(self):
        self.assertEqual(aqb.normalize_slug("--fix-login--"), "fix-login")
        self.assertEqual(aqb.normalize_slug("___fix___"), "fix")


class TestEmptyQueue(unittest.TestCase):
    def test_9_empty_existing_set_means_nothing_is_a_duplicate(self):
        self.assertFalse(aqb.is_duplicate("fix-login", set()))

    def test_10_empty_queue_discovers_every_prefixed_branch(self):
        missing = aqb.discover_missing_branches(["agent/a", "agent/b"], set())
        self.assertEqual(missing, ["a", "b"])

    def test_11_no_branches_discovers_nothing(self):
        self.assertEqual(aqb.discover_missing_branches([], {"a"}), [])


class TestBadInputIsFailSoft(unittest.TestCase):
    def test_12_none_slug_does_not_raise(self):
        # Was AttributeError: 'NoneType' object has no attribute 'lower'.
        self.assertEqual(aqb.normalize_slug(None), "")
        self.assertFalse(aqb.is_duplicate(None, {"fix-login"}))

    def test_13_non_string_slugs_do_not_raise(self):
        for bad in (123, 4.5, [], {}, object()):
            self.assertEqual(aqb.normalize_slug(bad), "", repr(bad))
            self.assertFalse(aqb.is_duplicate(bad, {"fix-login"}), repr(bad))

    def test_14_an_unusable_candidate_is_not_reported_as_duplicate(self):
        # False, not True: a duplicate verdict would silently drop the row.
        for junk in ("", "   ", "---", "!!!"):
            self.assertEqual(aqb.normalize_slug(junk), "", repr(junk))
            self.assertFalse(aqb.is_duplicate(junk, {"fix-login", ""}), repr(junk))

    def test_15_a_malformed_entry_in_the_existing_set_is_survivable(self):
        # One bad row in the queue must not break the check for a good candidate.
        self.assertTrue(aqb.is_duplicate("fix-login", {None, 42, "fix-login"}))
        self.assertFalse(aqb.is_duplicate("brand-new", {None, 42, ""}))


class TestSimilarityThresholdStillDiscriminates(unittest.TestCase):
    def test_near_matches_collapse_but_unrelated_work_does_not(self):
        # Guards the cases above from passing on a dedup that says yes to
        # everything: dedup must still let genuinely new work through.
        self.assertTrue(aqb.is_duplicate("fix-login-bug", {"fix-login-bug-now"},
                                         similarity_threshold=0.5))
        self.assertFalse(aqb.is_duplicate("migrate-database-schema",
                                          {"update-readme-links"}))


if __name__ == "__main__":
    unittest.main()
