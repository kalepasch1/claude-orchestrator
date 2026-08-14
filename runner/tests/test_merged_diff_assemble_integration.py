#!/usr/bin/env python3
"""assemble_merge_summaries against a REAL git repo.

The mocked suite cannot catch the one thing that actually broke this shape: a plain
`git diff-tree -r <merge-sha>` prints NOTHING for a merge commit, so files_changed came
back empty for every record. Only a real merge commit exposes that, so this file builds
one in a tmpdir.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import merged_diff_memory as mdm


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _build_repo(path):
    _git("init", "-q", "-b", "main", cwd=path)
    _git("config", "user.email", "t@example.test", cwd=path)
    _git("config", "user.name", "T", cwd=path)
    open(os.path.join(path, "base.py"), "w").write("x = 1\n")
    _git("add", "-A", cwd=path)
    _git("commit", "-q", "-m", "base", cwd=path)

    _git("checkout", "-q", "-b", "agent/feature", cwd=path)
    os.makedirs(os.path.join(path, "runner"), exist_ok=True)
    open(os.path.join(path, "runner", "feature.py"), "w").write("y = 2\n")
    _git("add", "-A", cwd=path)
    _git("commit", "-q", "-m", "feat: add feature", cwd=path)

    _git("checkout", "-q", "main", cwd=path)
    _git("merge", "-q", "--no-ff", "-m", "Merge branch 'agent/feature'",
         "agent/feature", cwd=path)


class RealRepoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = cls.tmp.name
        _build_repo(cls.repo)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_a_real_merge_commit_reports_the_files_it_brought_in(self):
        """The regression: this list was empty for every merge before -m --first-parent."""
        out = mdm.assemble_merge_summaries(limit=5, repo=self.repo)
        self.assertTrue(out, "no merges found in the fixture repo")
        merge = out[0]
        self.assertEqual(merge["branch_name"], "agent/feature")
        self.assertIn("runner/feature.py", merge["files_changed"])

    def test_the_summary_reflects_the_real_files(self):
        merge = mdm.assemble_merge_summaries(limit=5, repo=self.repo)[0]
        self.assertNotIn("no files changed", merge["summary"])
        self.assertIn("runner", merge["summary"])

    def test_the_shape_holds_against_a_real_repo(self):
        for rec in mdm.assemble_merge_summaries(limit=5, repo=self.repo):
            self.assertEqual(list(rec.keys()),
                             ["name", "branch_name", "files_changed",
                              "merge_date", "summary"])
            self.assertIsInstance(rec["files_changed"], list)
            self.assertTrue(rec["merge_date"])

    def test_a_directory_that_is_not_a_repo_returns_empty(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(mdm.assemble_merge_summaries(limit=5, repo=empty), [])


if __name__ == "__main__":
    unittest.main()
