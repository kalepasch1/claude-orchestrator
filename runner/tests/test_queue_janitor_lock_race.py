#!/usr/bin/env python3
"""The janitor's object-archive guard survives a lockfile that vanishes.

A git lockfile is transient, so it can disappear between the glob that lists it
and the stat that measures it. Until this was fixed, archive_stale_git_objects()
called os.path.getmtime() bare inside a genexpr, so that race raised
FileNotFoundError out of the whole queue-janitor run -- 9 occurrences in
.runtime/logs/queue-janitor.err, 90% of that job's tracebacks.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import queue_janitor as qj  # noqa: E402

GIT_TIMEOUT_S = 60


class ArchiveStaleGitObjectsLockRace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        subprocess.run(
            ["git", "init", "-q", self.repo],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
        )
        self.git_dir = os.path.join(self.repo, ".git")

    def tearDown(self):
        self._tmp.cleanup()

    def _lock(self, name="index.lock"):
        path = os.path.join(self.git_dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")
        return path

    def test_lock_that_vanishes_mid_check_does_not_raise(self):
        """The regression: glob sees the lock, the stat no longer does."""
        lock = self._lock()

        real_getmtime = os.path.getmtime

        def vanishing(path):
            if path == lock:
                # Exactly what a finishing git does, at the worst moment.
                os.remove(lock)
                return real_getmtime(lock)  # raises FileNotFoundError
            return real_getmtime(path)

        with mock.patch.object(qj, "_lock_has_live_holder", return_value=False), \
                mock.patch("os.path.getmtime", side_effect=vanishing):
            result = qj.archive_stale_git_objects(self.repo)

        # Fails closed: a writer was active moments ago, so nothing is touched.
        self.assertEqual(result, {"refs": 0, "objects": 0})

    def test_vanished_lock_blocks_rather_than_permits(self):
        lock = self._lock()
        os.remove(lock)
        with mock.patch.object(qj, "_lock_has_live_holder", return_value=False):
            self.assertTrue(qj._lock_blocks_object_archive(lock, 0.0, 0.0))

    def test_live_holder_still_blocks(self):
        lock = self._lock()
        with mock.patch.object(qj, "_lock_has_live_holder", return_value=True):
            self.assertTrue(qj._lock_blocks_object_archive(lock, 0.0, 0.0))

    def test_old_unheld_lock_does_not_block(self):
        """The guard must not become a blanket no-op: abandoned locks pass."""
        lock = self._lock()
        old = 1_000_000.0
        os.utime(lock, (old, old))
        with mock.patch.object(qj, "_lock_has_live_holder", return_value=False):
            self.assertFalse(
                qj._lock_blocks_object_archive(lock, old + 10_000.0, 60.0)
            )

    def test_recent_unheld_lock_blocks(self):
        lock = self._lock()
        now = 2_000_000.0
        os.utime(lock, (now, now))
        with mock.patch.object(qj, "_lock_has_live_holder", return_value=False):
            self.assertTrue(qj._lock_blocks_object_archive(lock, now + 5.0, 600.0))


class AcrossProjectsIsolatesOneBadRepo(unittest.TestCase):
    """One raising repo must not cancel the repos behind it in the sweep."""

    def test_sweep_continues_past_a_raising_repo(self):
        with tempfile.TemporaryDirectory() as bad, tempfile.TemporaryDirectory() as good:
            rows = [{"repo_path": bad}, {"repo_path": good}]
            seen = []

            def fake_archive(repo):
                seen.append(repo)
                if repo == bad:
                    raise FileNotFoundError(
                        2, "No such file or directory", os.path.join(bad, ".git/index.lock")
                    )
                return {"refs": 1, "objects": 2}

            with mock.patch.object(qj.db, "select", return_value=rows), \
                    mock.patch.object(qj, "archive_stale_git_objects", side_effect=fake_archive):
                refs, objects = qj.archive_stale_git_objects_across_projects()

            self.assertEqual(seen, [bad, good])
            self.assertEqual((refs, objects), (1, 2))


if __name__ == "__main__":
    unittest.main()
