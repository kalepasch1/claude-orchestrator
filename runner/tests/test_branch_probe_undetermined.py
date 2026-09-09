#!/usr/bin/env python3
"""A branch probe that times out must not be read as "branch missing".

THE BUG
-------
`integration_sweeper._branch_exists` ran `git rev-parse` with NO timeout — the only
unbounded git call in a module where every other one passes `timeout=30`. It runs once
per task in the scan (LIMIT=150), so a single wedged git (stale network mount, held
index.lock, repo mid-gc) hung the entire sweeper, which then filed nothing and reported
nothing wrong.

Bounding it is necessary but not sufficient, and the "not sufficient" half is the point
of this file. `_queue_recovery` files a recovery task when `_agent_branch_exists` is
falsey, so if a timeout were absorbed into a bare `False` the fix would trade a hang for
the module's other documented failure mode: the stub that always returned False made the
sweeper treat every passed task as a lost branch, and the truncation bug left 3,944
recover-missing-branch-* rows — 17.5% of the entire tasks table. Those recovery tasks are
themselves swept, probed and re-filed, so the loop feeds itself.

Guessing the other way is no better: a false "exists" sends the merge train after a ref
that is not there.

So the probe raises `BranchProbeUndetermined`, and the one place that decides
"missing -> file recovery" treats it as "ask again next sweep".
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import integration_sweeper as sweeper  # noqa: E402


def _run(repo, *args):
    return subprocess.run(list(args), cwd=repo, capture_output=True, text=True, timeout=60)


class ProbeBoundsTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="probe-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        _run(self.repo, "git", "init", "-q", "-b", "master")
        _run(self.repo, "git", "config", "user.name", "kalepasch1")
        _run(self.repo, "git", "config", "user.email", "kalepasch@gmail.com")
        _run(self.repo, "git", "config", "commit.gpgsign", "false")
        with open(os.path.join(self.repo, "a.txt"), "w") as fh:
            fh.write("1\n")
        _run(self.repo, "git", "add", "-A")
        _run(self.repo, "git", "commit", "-qm", "base")

    def test_probe_still_answers_normally(self):
        self.assertTrue(sweeper._branch_exists(self.repo, "master"))
        self.assertFalse(sweeper._branch_exists(self.repo, "agent/nope"))

    def test_absent_repo_is_still_a_plain_false(self):
        """A path that is not a repo is genuinely knowable, not undetermined."""
        self.assertFalse(sweeper._branch_exists("", "agent/x"))
        self.assertFalse(sweeper._branch_exists("/nonexistent/path", "agent/x"))

    def test_probe_passes_a_timeout(self):
        """The bound must be at the call site, not left to conftest's injected default."""
        seen = {}
        real = subprocess.run

        def spy(*a, **kw):
            seen.update(kw)
            return real(*a, **kw)

        sweeper.subprocess.run = spy
        try:
            sweeper._branch_exists(self.repo, "master")
        finally:
            sweeper.subprocess.run = real
        self.assertIn("timeout", seen)
        self.assertEqual(seen["timeout"], sweeper.PROBE_TIMEOUT_S)

    def test_timeout_raises_undetermined_rather_than_returning_false(self):
        real = subprocess.run

        def slow(*a, **kw):
            raise subprocess.TimeoutExpired(cmd=a[0] if a else "git", timeout=30)

        sweeper.subprocess.run = slow
        try:
            with self.assertRaises(sweeper.BranchProbeUndetermined):
                sweeper._branch_exists(self.repo, "agent/whatever")
        finally:
            sweeper.subprocess.run = real


class QueueRecoveryUndeterminedTests(unittest.TestCase):
    """The decision point must not turn "cannot tell" into "missing"."""

    def setUp(self):
        self._real = sweeper._agent_branch_exists
        self.addCleanup(lambda: setattr(sweeper, "_agent_branch_exists", self._real))
        self._real_handle = sweeper._handle_missing_branch
        self.addCleanup(lambda: setattr(sweeper, "_handle_missing_branch",
                                        self._real_handle))
        self.filed = []
        sweeper._handle_missing_branch = lambda task, proj, recovery_index=None: (
            self.filed.append(task.get("slug")) or True)

    def test_undetermined_files_no_recovery(self):
        def undetermined(_repo, _slug):
            raise sweeper.BranchProbeUndetermined("probe timed out")

        sweeper._agent_branch_exists = undetermined
        result = sweeper._queue_recovery({"slug": "s1"}, {"repo_path": "/tmp"})

        self.assertFalse(result)
        self.assertEqual(self.filed, [],
                         "a timed-out probe must not file recovery — that is the "
                         "churn loop this guard exists to prevent")

    def test_a_genuinely_missing_branch_still_files_recovery(self):
        """The guard must not have disabled the sweeper's actual job."""
        sweeper._agent_branch_exists = lambda _repo, _slug: False
        self.assertTrue(sweeper._queue_recovery({"slug": "s2"}, {"repo_path": "/tmp"}))
        self.assertEqual(self.filed, ["s2"])

    def test_a_present_branch_files_nothing(self):
        sweeper._agent_branch_exists = lambda _repo, _slug: True
        self.assertFalse(sweeper._queue_recovery({"slug": "s3"}, {"repo_path": "/tmp"}))
        self.assertEqual(self.filed, [])


if __name__ == "__main__":
    unittest.main()
