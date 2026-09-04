"""Unit tests for the live-task ownership lookup.

Run: python3 -m unittest discover -s tools -p 'test_*.py'

Task state is injected, so no database is touched. The cases mirror the three
worktrees that provoked this module: each was dirty, each looked recoverable to
git, and each was owned by a RUNNING task under another executor.
"""

import unittest

import live_task_owner as l


class SlugFromPath(unittest.TestCase):
    def test_plain_directory_name(self):
        self.assertEqual(l.slug_from_path("/a/b/canary-deepseek-1"),
                         "canary-deepseek-1")

    def test_trailing_short_sha_is_stripped(self):
        self.assertEqual(l.slug_from_path("/wt/backlog-batch-beethoven-abc 8309febb"),
                         "backlog-batch-beethoven-abc")

    def test_trailing_sha_joined_by_dash_is_stripped(self):
        self.assertEqual(l.slug_from_path("/wt/some-slug-8309febb"), "some-slug")

    def test_trailing_slash_does_not_produce_empty_slug(self):
        self.assertEqual(l.slug_from_path("/wt/madeus-group-3/"), "madeus-group-3")

    def test_empty_input_is_empty_not_an_exception(self):
        self.assertEqual(l.slug_from_path(""), "")
        self.assertEqual(l.slug_from_path(None), "")


class OwnerLookup(unittest.TestCase):
    STATES = {
        "canary-deepseek-1": "RUNNING",
        "orch-cross-project-depends": "RUNNING",
        "dropbox-beethoven-madeus-web-multi-tenant-group-3": "RUNNING",
        "spine-types-x2": "DONE",
        "old-thing": "MERGED",
        "waiting-thing": "QUEUED",
    }

    def setUp(self):
        self.is_owned = l.owner_lookup(self.STATES)

    def test_running_task_owns_its_worktree(self):
        self.assertEqual(self.is_owned("/wt/canary-deepseek-1"),
                         ("canary-deepseek-1", "RUNNING"))

    def test_queued_counts_as_live_because_somebody_will_still_ship_it(self):
        self.assertEqual(self.is_owned("/wt/waiting-thing"),
                         ("waiting-thing", "QUEUED"))

    def test_finished_task_does_not_own_its_worktree(self):
        self.assertIsNone(self.is_owned("/wt/spine-types-x2"))
        self.assertIsNone(self.is_owned("/wt/old-thing"))

    def test_unknown_slug_has_no_owner(self):
        self.assertIsNone(self.is_owned("/wt/never-heard-of-it"))

    def test_truncated_worktree_name_resolves_to_the_full_slug(self):
        # The runner truncates long slugs when naming a worktree, so the
        # directory is a prefix of the task slug, not equal to it.
        got = self.is_owned("/wt/dropbox-beethoven-madeus-web-multi-tenant")
        self.assertEqual(got[1], "RUNNING")
        self.assertTrue(got[0].endswith("group-3"))

    def test_empty_path_has_no_owner(self):
        self.assertIsNone(self.is_owned(""))


class FailSoft(unittest.TestCase):
    def test_unreadable_task_state_reports_no_owner_by_default(self):
        # A reconciler that cannot reach the database must still produce a
        # ledger rather than raising.
        self.assertIsNone(l.owner_lookup({})("/wt/anything"))

    def test_strict_callers_can_prefer_deferring_to_racing(self):
        got = l.owner_lookup({}, strict=True)("/wt/anything")
        self.assertEqual(got, ("anything", "UNKNOWN"))

    def test_strict_mode_is_irrelevant_when_state_is_readable(self):
        self.assertIsNone(
            l.owner_lookup({"x": "DONE"}, strict=True)("/wt/x"))


if __name__ == "__main__":
    unittest.main()
