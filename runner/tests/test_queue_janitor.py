import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_janitor


class ClearStaleGitLocksTest(unittest.TestCase):
    """2026-07-10: clear_stale_git_locks() used to remove any .git/*.lock older than
    LOCK_STALE_MIN based on age alone, with no check that a legitimately slow git
    operation might still be holding it. Verified by hand (via lsof) before manually
    clearing a stale Sustainable_Barks lock that day; these tests cover the automated
    equivalent of that manual check."""

    def _make_repo_with_lock(self, tmp, age_seconds):
        repo = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        lock = os.path.join(repo, ".git", "index.lock")
        with open(lock, "w") as f:
            f.write("")
        old_time = time.time() - age_seconds
        os.utime(lock, (old_time, old_time))
        return repo, lock

    def test_old_unheld_lock_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, lock = self._make_repo_with_lock(tmp, age_seconds=20 * 60)  # 20 min > 15 min default
            fake_db = MagicMock()
            fake_db.select.return_value = [{"repo_path": repo}]
            with patch.object(queue_janitor, "db", fake_db), \
                 patch.object(queue_janitor, "_lock_has_live_holder", return_value=False):
                cleared = queue_janitor.clear_stale_git_locks()
            self.assertEqual(cleared, 1)
            self.assertFalse(os.path.exists(lock))

    def test_old_lock_still_held_by_live_process_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, lock = self._make_repo_with_lock(tmp, age_seconds=20 * 60)
            fake_db = MagicMock()
            fake_db.select.return_value = [{"repo_path": repo}]
            with patch.object(queue_janitor, "db", fake_db), \
                 patch.object(queue_janitor, "_lock_has_live_holder", return_value=True):
                cleared = queue_janitor.clear_stale_git_locks()
            self.assertEqual(cleared, 0)
            self.assertTrue(os.path.exists(lock))

    def test_young_lock_is_left_alone_regardless_of_holder_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, lock = self._make_repo_with_lock(tmp, age_seconds=60)  # 1 min, well under threshold
            fake_db = MagicMock()
            fake_db.select.return_value = [{"repo_path": repo}]
            holder_check = MagicMock(return_value=False)
            with patch.object(queue_janitor, "db", fake_db), \
                 patch.object(queue_janitor, "_lock_has_live_holder", holder_check):
                cleared = queue_janitor.clear_stale_git_locks()
            self.assertEqual(cleared, 0)
            self.assertTrue(os.path.exists(lock))
            holder_check.assert_not_called()

    def test_lsof_failure_fails_closed_and_leaves_lock(self):
        """If lsof itself can't be run, assume the lock is still held rather than risk
        yanking it from a live writer."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, lock = self._make_repo_with_lock(tmp, age_seconds=20 * 60)
            with patch("subprocess.run", side_effect=OSError("lsof not found")):
                held = queue_janitor._lock_has_live_holder(lock)
            self.assertTrue(held)

    def test_lock_with_no_lsof_output_is_considered_unheld(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, lock = self._make_repo_with_lock(tmp, age_seconds=20 * 60)
            fake_result = MagicMock(stdout="")
            with patch("subprocess.run", return_value=fake_result):
                held = queue_janitor._lock_has_live_holder(lock)
            self.assertFalse(held)

    def test_lock_with_lsof_output_is_considered_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, lock = self._make_repo_with_lock(tmp, age_seconds=20 * 60)
            fake_result = MagicMock(stdout="84193\n")
            with patch("subprocess.run", return_value=fake_result):
                held = queue_janitor._lock_has_live_holder(lock)
            self.assertTrue(held)


if __name__ == "__main__":
    unittest.main()
