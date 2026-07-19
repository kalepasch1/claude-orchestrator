import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import branch_reconciler


class BranchReconcilerTest(unittest.TestCase):
    def test_root_slug_strips_retry_wrappers(self):
        self.assertEqual(branch_reconciler._root_slug("recover-missing-branch-relfix-hotel-api"), "hotel-api")

    def test_champions_keep_distinct_patches_and_newest_duplicate(self):
        rows = [
            {"root": "a", "fingerprint": "same", "stamp": 1, "slug": "old"},
            {"root": "a", "fingerprint": "same", "stamp": 2, "slug": "new"},
            {"root": "a", "fingerprint": "other", "stamp": 1, "slug": "different"},
        ]
        chosen, duplicates = branch_reconciler.champions(rows)
        self.assertEqual({row["slug"] for row in chosen}, {"new", "different"})
        self.assertEqual([row["slug"] for row in duplicates], ["old"])


if __name__ == "__main__":
    unittest.main()
