"""A worktree must be able to prove which task it serves.

The reconciler decides whether a dirty worktree holds abandoned work or work a
live agent is editing right now. That decision needs a slug, and until now the
only evidence was the directory name.

It was not enough. On 2026-08-23 `madeus-group-3` was classified RECOVERABLE_VALUE
while owned by a task in state RUNNING, because its slug is

    dropbox-beethoven-madeus-web-multi-tenant-claude-preneur-platform-bi-group-3

and no prefix, suffix or token-boundary rule links those two strings. The obvious
patch — fuzzy matching — is the one thing that must not be done: a false positive
marks recoverable work as owned and drops it, silently. So the slug is recorded
at creation and read back, and "unknown" is a distinct answer from "unowned".
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worktree_identity as wi  # noqa: E402

REAL_SLUG = "dropbox-beethoven-madeus-web-multi-tenant-claude-preneur-platform-bi-group-3"
REAL_DIRNAME = "madeus-group-3"


class StampAndRead(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_the_case_that_caused_this(self):
        # The directory name proves nothing about the slug; the marker does.
        wt = os.path.join(self.dir, REAL_DIRNAME)
        os.makedirs(wt)
        self.assertTrue(wi.stamp(wt, REAL_SLUG))
        self.assertEqual(wi.read_slug(wt), REAL_SLUG)
        self.assertNotIn(os.path.basename(wt), REAL_SLUG.split("-")[:2])

    def test_round_trip_records_branch_and_repo(self):
        wt = os.path.join(self.dir, "wt")
        os.makedirs(wt)
        wi.stamp(wt, "some-slug", branch="agent/some-slug", repo="/repos/x")
        got = wi.read_identity(wt)
        self.assertEqual(got["slug"], "some-slug")
        self.assertEqual(got["branch"], "agent/some-slug")
        self.assertEqual(got["repo"], "/repos/x")
        self.assertEqual(got["schema"], wi.SCHEMA_VERSION)
        self.assertIsInstance(got["created_at"], int)

    def test_branch_defaults_to_the_agent_convention(self):
        wt = os.path.join(self.dir, "wt")
        os.makedirs(wt)
        wi.stamp(wt, "some-slug")
        self.assertEqual(wi.read_identity(wt)["branch"], "agent/some-slug")

    def test_stamp_creates_the_directory_if_absent(self):
        wt = os.path.join(self.dir, "not-yet")
        self.assertTrue(wi.stamp(wt, "s"))
        self.assertEqual(wi.read_slug(wt), "s")

    def test_marker_is_a_dotfile_so_it_is_not_read_as_evidence(self):
        # The reconciler inspects dirty worktrees. An identity marker that itself
        # showed up as an uncommitted change would create the very ambiguity it
        # exists to remove.
        self.assertTrue(wi.MARKER.startswith("."))

    def test_restamping_overwrites_rather_than_appending(self):
        wt = os.path.join(self.dir, "wt")
        os.makedirs(wt)
        wi.stamp(wt, "first")
        wi.stamp(wt, "second")
        self.assertEqual(wi.read_slug(wt), "second")
        with open(os.path.join(wt, wi.MARKER)) as fh:
            json.load(fh)          # still one valid document, not two concatenated

    def test_no_tmp_file_is_left_behind(self):
        wt = os.path.join(self.dir, "wt")
        os.makedirs(wt)
        wi.stamp(wt, "s")
        self.assertEqual([f for f in os.listdir(wt) if f.endswith(".tmp")], [])


class UnknownIsNotUnowned(unittest.TestCase):
    """Every degraded path returns None, and None must be read as "decide by other
    means" — never as permission to discard the work."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_unstamped_worktree_is_unknown(self):
        wt = os.path.join(self.dir, "wt")
        os.makedirs(wt)
        self.assertIsNone(wi.read_slug(wt))
        self.assertFalse(wi.is_stamped(wt))

    def test_nonexistent_path_is_unknown(self):
        self.assertIsNone(wi.read_slug(os.path.join(self.dir, "nope")))

    def test_corrupt_marker_is_unknown_not_an_exception(self):
        wt = os.path.join(self.dir, "wt")
        os.makedirs(wt)
        with open(os.path.join(wt, wi.MARKER), "w") as fh:
            fh.write("{not json at all")
        self.assertIsNone(wi.read_slug(wt))

    def test_marker_without_a_slug_is_unknown(self):
        wt = os.path.join(self.dir, "wt")
        os.makedirs(wt)
        with open(os.path.join(wt, wi.MARKER), "w") as fh:
            json.dump({"schema": 1, "branch": "agent/x"}, fh)
        self.assertIsNone(wi.read_slug(wt))

    def test_marker_that_is_a_list_is_unknown(self):
        wt = os.path.join(self.dir, "wt")
        os.makedirs(wt)
        with open(os.path.join(wt, wi.MARKER), "w") as fh:
            json.dump(["slug"], fh)
        self.assertIsNone(wi.read_slug(wt))

    def test_stamp_refuses_empty_inputs_without_raising(self):
        for path, slug in ((None, "s"), ("", "s"), (self.dir, None), (self.dir, "")):
            self.assertFalse(wi.stamp(path, slug))

    def test_read_helpers_never_raise_on_junk_input(self):
        for bad in (None, "", 0, [], {}):
            self.assertIsNone(wi.read_slug(bad))
            self.assertIsNone(wi.read_identity(bad))
            self.assertFalse(wi.is_stamped(bad))


class NoGuessing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_resolution_does_not_infer_by_default(self):
        # This is the guarantee. Given the real directory name and no marker,
        # the answer is None — not a plausible-looking slug.
        wt = os.path.join(self.dir, REAL_DIRNAME)
        os.makedirs(wt)
        self.assertIsNone(wi.slug_for_path(wt))

    def test_basename_fallback_is_verbatim_and_opt_in(self):
        # For pre-existing worktrees the basename is the only evidence there is.
        # It is returned exactly, so a caller can check it against real task
        # state; it is never massaged into a match.
        wt = os.path.join(self.dir, REAL_DIRNAME)
        os.makedirs(wt)
        self.assertEqual(wi.slug_for_path(wt, fallback_to_basename=True), REAL_DIRNAME)
        self.assertNotEqual(wi.slug_for_path(wt, fallback_to_basename=True), REAL_SLUG)

    def test_recorded_slug_beats_the_basename(self):
        wt = os.path.join(self.dir, REAL_DIRNAME)
        os.makedirs(wt)
        wi.stamp(wt, REAL_SLUG)
        self.assertEqual(wi.slug_for_path(wt, fallback_to_basename=True), REAL_SLUG)

    def test_trailing_slash_does_not_produce_an_empty_basename(self):
        wt = os.path.join(self.dir, "trailing")
        os.makedirs(wt)
        self.assertEqual(wi.slug_for_path(wt + "/", fallback_to_basename=True), "trailing")


class CreationSitesStamp(unittest.TestCase):
    """The module is only worth anything if the code that makes worktrees calls it."""

    def _source(self, name):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, name), encoding="utf-8") as fh:
            return fh.read()

    def test_cowork_executor_stamps_the_worktree_it_creates(self):
        src = self._source("cowork_executor.py")
        self.assertIn("import worktree_identity", src)
        self.assertIn("worktree_identity.stamp(", src)

    def test_build_daemon_stamps_warm_worktrees(self):
        src = self._source("build_daemon.py")
        self.assertIn("import worktree_identity", src)
        self.assertIn("worktree_identity.stamp(", src)


if __name__ == "__main__":
    unittest.main()
