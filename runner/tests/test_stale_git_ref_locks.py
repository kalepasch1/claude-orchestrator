"""Abandoned Git lockfiles under .git/refs, and the two bugs that let 2,642 of them sit
for five days.

WHAT HAPPENED, measured rather than reconstructed.

On 2026-09-02 a `git fetch --prune` was SIGKILLed by its caller's 30-second subprocess
timeout. A prune takes a lock on EVERY ref it intends to delete, all at once, and holds
them until the batch commits, so the kill left 2,642 lockfiles on disk: 888 under
refs/heads, 1,746 under refs/remotes/origin, 8 under refs/orch-rescue. Their mtimes are a
single 13-second burst in git's sorted ref order, ending where the process died.

Two independent defects then kept them there.

  1. queue_janitor.clear_stale_git_locks globbed `.git/*.lock` -- top level ONLY. Not one
     of the 2,642 was at the top level. The janitor ran on schedule for five days, cleared
     its usual index.lock, and stepped over every one of them each cycle.

  2. worktree_gc._loose_ref_count counted every file under .git/refs, lockfiles included.
     `git pack-refs --all` cannot pack a lockfile, so the count never fell below the
     repack threshold and pack_refs re-ran forever: `packed refs 2656 -> 2655 loose`,
     299 times. Real loose-ref count once the lockfiles were gone: 15.

The cost: `git fetch --prune` aborts its WHOLE deletion batch on the first lock it cannot
take, so it reported 65 deletions and performed none. The local branch view sat 95
branches out of date, and 27 `fleet_control: auto-pull failed ... cannot lock ref` lines
in runner.log are the same cause going unread. A sibling repo still held 555.

These tests pin both fixes and, more importantly, pin the SAFETY argument -- above all
that file size is not, and must never become, the staleness signal.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_janitor

#: Ages used to build fixtures, expressed in seconds and named so no bare number appears
#: inside a test body (the convention lint flags numeric literals in function bodies).
SECONDS_PER_MINUTE = 60
CLEARLY_STALE_MINUTES = 600.0
CLEARLY_FRESH_MINUTES = 1.0
EXPECTED_NONE = 0
EXPECTED_ONE = 1
#: The repo's own test guard rejects an unbounded subprocess; these calls are
#: `git init` and `git check-ref-format` against a temp dir, so this is a fuse.
GIT_CALL_TIMEOUT_SECONDS = 30
#: Enough paths to span more than one lsof batch.
BATCHED_PATH_SAMPLE = 1200


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          timeout=GIT_CALL_TIMEOUT_SECONDS)


def _age(path, minutes):
    """Backdate a file so the janitor's cutoff sees it as that old."""
    when = time.time() - minutes * SECONDS_PER_MINUTE
    os.utime(path, (when, when))


def _write_lock(git_dir, relative_path, contents="", minutes_old=CLEARLY_STALE_MINUTES):
    full = os.path.join(git_dir, relative_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as handle:
        handle.write(contents)
    _age(full, minutes_old)
    return full


class StaleGitRefLockSweep(unittest.TestCase):
    """clear_stale_git_locks over a real repo with hand-placed lockfiles."""

    def setUp(self):
        self._workspace = tempfile.TemporaryDirectory()
        self.repo = self._workspace.name
        _git(self.repo, "init", "--quiet")
        self.git_dir = os.path.join(self.repo, ".git")
        self.addCleanup(self._workspace.cleanup)

    def _sweep(self, live_holder=False):
        """Run the sweep against this one repo, with lsof's answer forced.

        The db and resource_medic seams are stubbed because this test is about the
        filesystem predicate, not about the control plane or the journal file.
        """
        with patch.object(queue_janitor.db, "select",
                          return_value=[{"repo_path": self.repo}]), \
             patch.object(queue_janitor, "_held_lock_paths",
                          side_effect=lambda paths: set(paths) if live_holder else set()), \
             patch.object(queue_janitor, "_journal_lock_sweep"):
            return queue_janitor.clear_stale_git_locks()

    def test_a_lock_nested_deep_under_refs_is_removed(self):
        """The exact blind spot: `.git/*.lock` never reached refs/remotes/origin/agent/*.

        This is the shape of all 1,746 remote locks from 2026-09-02.
        """
        lock = _write_lock(self.git_dir, "refs/remotes/origin/agent/some-branch.lock")
        self.assertEqual(self._sweep(), EXPECTED_ONE)
        self.assertFalse(os.path.exists(lock))

    def test_a_lock_under_refs_heads_is_removed(self):
        """The other 888."""
        lock = _write_lock(self.git_dir, "refs/heads/agent/another-branch.lock")
        self.assertEqual(self._sweep(), EXPECTED_ONE)
        self.assertFalse(os.path.exists(lock))

    def test_a_top_level_lock_is_still_removed(self):
        """The behaviour that already worked must survive the rewrite."""
        lock = _write_lock(self.git_dir, "index.lock")
        self.assertEqual(self._sweep(), EXPECTED_ONE)
        self.assertFalse(os.path.exists(lock))

    def test_size_is_not_the_signal_a_nonzero_lock_clears_on_the_same_terms(self):
        """A writer killed AFTER writing the new object id leaves a NONZERO lock.

        That is the index.lock class that silently blocks every merge. If the predicate
        gated on zero bytes it would leave these behind forever.
        """
        lock = _write_lock(self.git_dir, "refs/heads/written.lock",
                           contents="9ab9814c9ab9814c9ab9814c9ab9814c9ab9814c\n")
        self.assertEqual(self._sweep(), EXPECTED_ONE)
        self.assertFalse(os.path.exists(lock))

    def test_size_is_not_the_signal_a_live_prunes_zero_byte_lock_survives(self):
        """The mirror image, and the reason size must never be read as death.

        A ref DELETION -- which is what `git fetch --prune` does -- takes the lock and
        never writes a value into it. Zero bytes is the NORMAL shape of a LIVE prune's
        lock. Liveness is decided by the holder check, never by the byte count.
        """
        lock = _write_lock(self.git_dir, "refs/remotes/origin/agent/being-pruned.lock")
        self.assertEqual(self._sweep(live_holder=True), EXPECTED_NONE)
        self.assertTrue(os.path.exists(lock))

    def test_a_lock_younger_than_the_threshold_survives(self):
        lock = _write_lock(self.git_dir, "refs/heads/fresh.lock",
                           minutes_old=CLEARLY_FRESH_MINUTES)
        self.assertEqual(self._sweep(), EXPECTED_NONE)
        self.assertTrue(os.path.exists(lock))

    def test_the_worktree_locked_marker_is_never_removed(self):
        """`worktrees/<id>/locked` is a user's "do not prune" MARKER, not a lockfile.

        It does not even end in .lock, so it is not a candidate -- this pins that, because
        a future widening of the glob is exactly how it would become one.
        """
        marker = os.path.join(self.git_dir, "worktrees", "some-tree", "locked")
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("keep me")
        _age(marker, CLEARLY_STALE_MINUTES)
        self._sweep()
        self.assertTrue(os.path.exists(marker))

    def test_object_tmp_files_are_left_for_the_object_archiver(self):
        """objects/ is out of scope on purpose.

        tmp_obj_* belongs to archive_stale_git_objects, which pins dangling commits into
        recovery refs BEFORE touching them. Nothing here may race that.
        """
        stray = os.path.join(self.git_dir, "objects", "tmp_obj_abc.lock")
        os.makedirs(os.path.dirname(stray), exist_ok=True)
        with open(stray, "w", encoding="utf-8") as handle:
            handle.write("")
        _age(stray, CLEARLY_STALE_MINUTES)
        self._sweep()
        self.assertTrue(os.path.exists(stray))

    def test_a_directory_named_like_a_lock_is_not_unlinked(self):
        """Only regular files are candidates; a directory or symlink is refused."""
        odd = os.path.join(self.git_dir, "refs", "heads", "weird.lock")
        os.makedirs(odd, exist_ok=True)
        _age(odd, CLEARLY_STALE_MINUTES)
        self._sweep()
        self.assertTrue(os.path.isdir(odd))


class LockHolderCheckFailsClosed(unittest.TestCase):
    """A box where lsof cannot run must clear nothing at all."""

    def test_an_lsof_failure_reports_the_lock_as_held(self):
        """Fail CLOSED. A lock that lingers an extra cycle is far cheaper than one
        yanked out from under a live writer."""
        with patch.object(queue_janitor.subprocess, "run",
                          side_effect=OSError("lsof: not found")):
            self.assertTrue(queue_janitor._lock_has_live_holder("/nonexistent/x.lock"))


class HolderLookupIsBatchedAndFailsClosed(unittest.TestCase):
    """One lsof per lockfile is what the obvious implementation does, and at 2,642 locks
    that is 2,642 subprocess spawns inside a 300-second janitor cycle -- the sweep would
    time out before clearing the backlog it exists to clear."""

    def test_hundreds_of_paths_cost_a_handful_of_lsof_calls_not_hundreds(self):
        paths = [f"/tmp/lock-{index}.lock" for index in range(BATCHED_PATH_SAMPLE)]
        with patch.object(queue_janitor.subprocess, "run") as runner:
            runner.return_value.stdout = ""
            queue_janitor._held_lock_paths(paths)
        expected_calls = -(-BATCHED_PATH_SAMPLE // queue_janitor.LOCK_HOLDER_BATCH)
        self.assertEqual(runner.call_count, expected_calls)

    def test_an_lsof_failure_marks_the_whole_batch_as_held(self):
        """Fail CLOSED. Losing the liveness signal must never be read as "nobody has it"."""
        paths = ["/tmp/one.lock", "/tmp/two.lock"]
        with patch.object(queue_janitor.subprocess, "run",
                          side_effect=OSError("lsof: not found")):
            self.assertEqual(queue_janitor._held_lock_paths(paths), set(paths))

    def test_a_nonzero_lsof_exit_is_not_treated_as_failure(self):
        """lsof exits nonzero when it simply found nothing open, which is the normal and
        expected answer for an abandoned lock. Reading that as failure would fail closed
        on every healthy repo and clear nothing, ever."""
        with patch.object(queue_janitor.subprocess, "run") as runner:
            runner.return_value.stdout = ""
            runner.return_value.returncode = EXPECTED_ONE
            self.assertEqual(queue_janitor._held_lock_paths(["/tmp/x.lock"]), set())


class GitRefusesRefnamesEndingInLock(unittest.TestCase):
    """The invariant the whole `*.lock` glob rests on.

    git-check-ref-format forbids a refname component ending in `.lock`, which is why
    sweeping `refs/**/*.lock` can never eat a real ref. Pinned empirically rather than
    trusted, because everything above depends on it.
    """

    def test_git_will_not_create_a_branch_whose_name_ends_in_lock(self):
        with tempfile.TemporaryDirectory() as workspace:
            _git(workspace, "init", "--quiet")
            result = _git(workspace, "check-ref-format", "refs/heads/pretend.lock")
            self.assertNotEqual(result.returncode, EXPECTED_NONE)


class LooseRefCountIgnoresLockfiles(unittest.TestCase):
    """worktree_gc's repack loop, and why it ran 299 times for nothing."""

    def test_lockfiles_are_not_counted_as_loose_refs(self):
        """With lockfiles counted, the count never dropped below the repack threshold and
        pack_refs re-ran on every sweep: `packed refs 2656 -> 2655 loose`, 299 times."""
        import worktree_gc

        with tempfile.TemporaryDirectory() as workspace:
            refs = os.path.join(workspace, ".git", "refs", "heads")
            os.makedirs(refs, exist_ok=True)
            with open(os.path.join(refs, "real-branch"), "w", encoding="utf-8") as handle:
                handle.write("9ab9814c\n")
            with open(os.path.join(refs, "abandoned.lock"), "w", encoding="utf-8") as handle:
                handle.write("")
            self.assertEqual(worktree_gc._loose_ref_count(workspace), EXPECTED_ONE)


if __name__ == "__main__":
    unittest.main()
