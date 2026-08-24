#!/usr/bin/env python3
"""Regression tests for tools/recovery_apply_check.py.

The bug these pin down: `git apply --check --3way` exits 0 even when git
reports "Applied patch to '<file>' with conflicts". Every reconciler used that
check to decide RECOVERABLE_VALUE, so conflicting diffs were being handed to
recovery tasks as ready to land.

Each test builds a throwaway repo, so nothing here touches real evidence.
"""

import os
import subprocess
import sys
import tempfile
import unittest

# The module under test lives one directory up, beside the rest of tools/.
# This file moved into tools/tests/ so it satisfies write_guard's rule that
# test files live in a `tests` directory; the import target did not move.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from recovery_apply_check import (  # noqa: E402
    VERDICT_CLEAN,
    VERDICT_CONFLICTED,
    VERDICT_EMPTY,
    VERDICT_THREE_WAY,
    apply_verdict,
    deletes_live_paths,
)


def git(*args, cwd, stdin=None):
    return subprocess.run(
        ("git",) + args, cwd=cwd, input=stdin,
        capture_output=True, text=True, errors="replace",
    )


class Repo:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="recovery-test-")
        git("init", "-q", cwd=self.dir)
        git("config", "user.email", "t@example.com", cwd=self.dir)
        git("config", "user.name", "t", cwd=self.dir)

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w") as fh:
            fh.write(text)

    def commit(self, msg):
        git("add", "-A", cwd=self.dir)
        git("commit", "-q", "-m", msg, cwd=self.dir)
        return git("rev-parse", "HEAD", cwd=self.dir).stdout.strip()

    def diff(self, a, b):
        return git("diff", a, b, cwd=self.dir).stdout


class ApplyVerdictTest(unittest.TestCase):
    def test_empty_diff(self):
        r = Repo()
        r.write("a.txt", "one\n")
        r.commit("base")
        self.assertEqual(apply_verdict("", "HEAD", r.dir), VERDICT_EMPTY)

    def test_clean_apply(self):
        """A diff touching an untouched region applies exactly."""
        r = Repo()
        r.write("a.txt", "\n".join(str(i) for i in range(1, 21)) + "\n")
        base = r.commit("base")
        r.write("a.txt", "\n".join(str(i) for i in range(1, 21)) + "added\n")
        tip = r.commit("tip")
        git("reset", "-q", "--hard", base, cwd=r.dir)
        self.assertEqual(
            apply_verdict(r.diff(base, tip), base, r.dir), VERDICT_CLEAN
        )

    def test_conflicting_apply_is_not_clean(self):
        """THE REGRESSION: git apply --check --3way exits 0 here; we must not.

        Branch and base edit the same line differently, so a three-way merge
        conflicts. The old check called this landable.
        """
        r = Repo()
        r.write("a.txt", "\n".join(str(i) for i in range(1, 21)) + "\n")
        base = r.commit("base")

        r.write("a.txt", "\n".join(str(i) for i in range(1, 21)).replace("10", "TIP") + "\n")
        tip = r.commit("tip")

        git("reset", "-q", "--hard", base, cwd=r.dir)
        r.write("a.txt", "\n".join(str(i) for i in range(1, 21)).replace("10", "MASTER") + "\n")
        newer = r.commit("newer base")

        patch = r.diff(base, tip)

        # Document the git behaviour this module exists to correct.
        legacy = subprocess.run(
            ["git", "apply", "--check", "--3way", "-"],
            cwd=r.dir, input=patch, capture_output=True, text=True,
        )
        self.assertEqual(legacy.returncode, 0,
                         "precondition: the old check reports success here")

        self.assertEqual(apply_verdict(patch, newer, r.dir), VERDICT_CONFLICTED)

    def test_three_way_without_conflict(self):
        """Base moved INSIDE the hunk context, but not on the edited line.

        Strict apply fails (the context no longer matches) while the three-way
        merge resolves cleanly. That combination is exactly what
        VERDICT_THREE_WAY exists to name: still landable, just not verbatim.
        """
        r = Repo()
        r.write("a.txt", "\n".join(str(i) for i in range(1, 41)) + "\n")
        base = r.commit("base")

        lines = [str(i) for i in range(1, 41)]
        lines[9] = "TIP"          # tip edits line 10
        r.write("a.txt", "\n".join(lines) + "\n")
        tip = r.commit("tip")

        git("reset", "-q", "--hard", base, cwd=r.dir)
        lines = [str(i) for i in range(1, 41)]
        lines[11] = "MASTER"      # base edits line 12: inside the +/-3 context
        r.write("a.txt", "\n".join(lines) + "\n")
        newer = r.commit("newer base")

        patch = r.diff(base, tip)
        strict = subprocess.run(
            ["git", "apply", "--check", "-"],
            cwd=r.dir, input=patch, capture_output=True, text=True,
        )
        self.assertNotEqual(strict.returncode, 0,
                            "precondition: strict apply must fail here")
        self.assertEqual(apply_verdict(patch, newer, r.dir), VERDICT_THREE_WAY)

    def test_worktree_and_index_untouched(self):
        """Evidence is read-only: verdicts must not disturb the caller."""
        r = Repo()
        r.write("a.txt", "\n".join(str(i) for i in range(1, 21)) + "\n")
        base = r.commit("base")
        r.write("a.txt", "\n".join(str(i) for i in range(1, 21)).replace("5", "TIP") + "\n")
        tip = r.commit("tip")
        git("reset", "-q", "--hard", base, cwd=r.dir)

        before_status = git("status", "--porcelain", cwd=r.dir).stdout
        before_head = git("rev-parse", "HEAD", cwd=r.dir).stdout
        apply_verdict(r.diff(base, tip), base, r.dir)
        self.assertEqual(git("status", "--porcelain", cwd=r.dir).stdout, before_status)
        self.assertEqual(git("rev-parse", "HEAD", cwd=r.dir).stdout, before_head)


class DeletesLivePathsTest(unittest.TestCase):
    def test_detects_deletion_of_a_file_base_still_has(self):
        """A stale branch deleting a module base still ships is a revert."""
        r = Repo()
        r.write("keep.txt", "one\n")
        r.write("doomed.txt", "two\n")
        base = r.commit("base")
        os.unlink(os.path.join(r.dir, "doomed.txt"))
        tip = r.commit("tip deletes doomed")
        self.assertEqual(
            deletes_live_paths(r.diff(base, tip), base, r.dir), ["doomed.txt"]
        )

    def test_no_false_positive_on_pure_addition(self):
        r = Repo()
        r.write("keep.txt", "one\n")
        base = r.commit("base")
        r.write("new.txt", "two\n")
        tip = r.commit("tip adds")
        self.assertEqual(deletes_live_paths(r.diff(base, tip), base, r.dir), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
