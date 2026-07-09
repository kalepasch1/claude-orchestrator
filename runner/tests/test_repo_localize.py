import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


class RepoLocalizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(os.path.join(self.home, "Documents", "proj"))  # local clone exists here
        os.environ.pop("ORCH_REPO_LOCALIZE", None)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("ORCH_REPO_LOCALIZE", None)

    def _expand(self, p):
        return self.home if p == "~" else p

    def test_remaps_foreign_home_to_local_clone(self):
        # /Users/<owner>/... doesn't exist here, but ~/Documents/proj does -> remap.
        with patch("os.path.expanduser", side_effect=self._expand):
            out = db.localize_repo_path("/Users/kpasch/Documents/proj")
        self.assertEqual(out, os.path.join(self.home, "Documents", "proj"))

    def test_noop_when_stored_path_exists(self):
        # on the owning machine the stored path is real -> returned unchanged.
        real = os.path.join(self.home, "Documents", "proj")
        self.assertEqual(db.localize_repo_path(real), real)

    def test_unchanged_when_no_local_clone(self):
        with patch("os.path.expanduser", side_effect=self._expand):
            out = db.localize_repo_path("/Users/kpasch/Documents/missing")
        self.assertEqual(out, "/Users/kpasch/Documents/missing")

    def test_opt_out_env(self):
        os.environ["ORCH_REPO_LOCALIZE"] = "false"
        with patch("os.path.expanduser", side_effect=self._expand):
            out = db.localize_repo_path("/Users/kpasch/Documents/proj")
        self.assertEqual(out, "/Users/kpasch/Documents/proj")  # untouched when disabled

    def test_repo_runnable_here(self):
        with patch("os.path.expanduser", side_effect=self._expand):
            self.assertTrue(db.repo_runnable_here(""))                               # no repo -> runs anywhere
            self.assertTrue(db.repo_runnable_here("/Users/kpasch/Documents/proj"))   # localizes to existing
            self.assertFalse(db.repo_runnable_here("/Users/kpasch/Documents/missing"))  # no local clone


if __name__ == "__main__":
    unittest.main()
