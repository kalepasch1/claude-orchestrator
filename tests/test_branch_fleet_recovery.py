#!/usr/bin/env python3
"""Pins branch_fleet_recovery: a branch that is ON ORIGIN must never be requeued.

recover_branch() checked the remote, and when the fetch failed it fell through to
the requeue path and filed a recover-{slug} task noting "branch missing everywhere".
The branch was not missing — only the fetch had failed — so that path manufactured
duplicate recovery work for branches that already existed. It is the same
false-missing pathology tests/test_branch_durability.py pins from the other side.

Run: python3 -m pytest tests/test_branch_fleet_recovery.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import branch_fleet_recovery as bfr  # noqa: E402


class FetchFailureDoesNotRequeue(unittest.TestCase):
    """Remote says the branch is there; the fetch fails anyway."""

    def setUp(self):
        self.task = {"id": "t-1", "slug": "some-work", "project_id": "p-1",
                     "kind": "build", "prompt": "x", "base_branch": "master"}
        self._saved = (bfr._branch_exists_local, bfr._branch_exists_remote,
                       bfr.git_auth, bfr.db, bfr.DRY_RUN)
        bfr._branch_exists_local = lambda repo, branch: False
        bfr._branch_exists_remote = lambda repo, branch: True
        bfr.DRY_RUN = False

        test = self

        class FakeGitAuth:
            @staticmethod
            def fetch_branch(repo, branch, remote="origin"):
                return False, "fatal: could not read Username"

            @staticmethod
            def pat_available():
                return True

        class FakeDb:
            @staticmethod
            def select(*a, **k):
                return []

            @staticmethod
            def insert(*a, **k):
                test.fail("requeued a branch that exists on origin")

            @staticmethod
            def update(*a, **k):
                test.fail("rewrote the note of a task whose branch exists on origin")

        bfr.git_auth = FakeGitAuth
        bfr.db = FakeDb

    def tearDown(self):
        (bfr._branch_exists_local, bfr._branch_exists_remote,
         bfr.git_auth, bfr.db, bfr.DRY_RUN) = self._saved

    def test_reports_fetch_failure_rather_than_requeuing(self):
        result = bfr.recover_branch(self.task, "/nonexistent-repo")
        self.assertEqual(result["strategy"], "fetch_failed_branch_present")
        self.assertFalse(result["recovered"])
        self.assertIn("Username", result["detail"])


class MissingEverywhereStillRequeues(unittest.TestCase):
    """The genuine missing case must keep working."""

    def setUp(self):
        self.task = {"id": "t-2", "slug": "lost-work", "project_id": "p-1",
                     "kind": "build", "prompt": "x", "base_branch": "master"}
        self.inserted = []
        self._saved = (bfr._branch_exists_local, bfr._branch_exists_remote,
                       bfr.git_auth, bfr.db, bfr.DRY_RUN)
        bfr._branch_exists_local = lambda repo, branch: False
        bfr._branch_exists_remote = lambda repo, branch: False
        bfr.DRY_RUN = False

        inserted = self.inserted

        class FakeGitAuth:
            @staticmethod
            def pat_available():
                return True

        class FakeDb:
            @staticmethod
            def select(*a, **k):
                return []

            @staticmethod
            def insert(table, row, **k):
                inserted.append(row)

            @staticmethod
            def update(*a, **k):
                return None

        bfr.git_auth = FakeGitAuth
        bfr.db = FakeDb

    def tearDown(self):
        (bfr._branch_exists_local, bfr._branch_exists_remote,
         bfr.git_auth, bfr.db, bfr.DRY_RUN) = self._saved

    def test_requeues_once(self):
        result = bfr.recover_branch(self.task, "/nonexistent-repo")
        self.assertEqual(result["strategy"], "requeued")
        self.assertEqual(len(self.inserted), 1)
        self.assertEqual(self.inserted[0]["slug"], "recover-lost-work")


if __name__ == "__main__":
    unittest.main()
