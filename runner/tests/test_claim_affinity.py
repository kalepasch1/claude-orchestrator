"""Soft affinity for multi-machine task claiming.

`runner/claim_affinity.py` decides which machine gets which task and, on a fallback
claim, pre-fetches the branch so execution can start without waiting for a clone. It
had no tests at all, which is a bad place to have none: the two failure modes are
silent. If affinity is too strong a machine starves while work sits in the queue; if
it is too weak every machine claims every project and the pre-fetch it exists to
avoid happens on every claim.

The two cases the task names, in this module's vocabulary:
  * "preferred machine has capacity"      -> local tasks exist, and they go first
  * "no capacity / repo unavailable"      -> no local tasks, fall through to remote
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import claim_affinity


LOCAL = "11111111-1111-1111-1111-111111111111"
REMOTE = "22222222-2222-2222-2222-222222222222"
OTHER_REMOTE = "33333333-3333-3333-3333-333333333333"


def _task(pid, slug="t", base="master"):
    return {"project_id": pid, "slug": slug, "base_branch": base}


class AffinityTestCase(unittest.TestCase):
    """Pin the env this module reads, so a developer's shell cannot change a verdict."""

    ENV = {
        "ORCH_SOFT_AFFINITY": "true",
        "ORCH_SOFT_AFFINITY_FALLTHROUGH": "true",
        # Off by default here: bootstrap starts real threads that shell out to git.
        # The tests that care about it turn it on and patch the fetch.
        "ORCH_BOOTSTRAP_ON_FALLBACK": "false",
    }

    def setUp(self):
        self._env = patch.dict(os.environ, self.ENV)
        self._env.start()
        self.addCleanup(self._env.stop)


class TestSoftAffinitySort(AffinityTestCase):

    def test_a_machine_that_holds_the_repo_takes_its_own_work_first(self):
        queued = [_task(REMOTE, "remote-1"), _task(LOCAL, "local-1"), _task(REMOTE, "remote-2")]
        out = claim_affinity.soft_affinity_sort(queued, {LOCAL})
        self.assertEqual([t["slug"] for t in out], ["local-1", "remote-1", "remote-2"])

    def test_remote_work_is_reordered_never_dropped(self):
        """Affinity is a preference. Discarding the remote tail would strand tasks
        whose only eligible machine is this one."""
        queued = [_task(REMOTE, "r1"), _task(LOCAL, "l1")]
        out = claim_affinity.soft_affinity_sort(queued, {LOCAL})
        self.assertEqual(len(out), len(queued))
        self.assertCountEqual([t["slug"] for t in out], ["l1", "r1"])

    def test_relative_order_within_each_group_is_preserved(self):
        """The queue is already priority-ordered upstream; affinity must not shuffle it."""
        queued = [_task(LOCAL, f"l{i}") for i in range(3)] + [_task(REMOTE, f"r{i}") for i in range(3)]
        out = claim_affinity.soft_affinity_sort(list(reversed(queued)), {LOCAL})
        self.assertEqual([t["slug"] for t in out], ["l2", "l1", "l0", "r2", "r1", "r0"])

    def test_no_local_work_falls_through_to_remote(self):
        """The 'preferred machine has no capacity' case: an idle machine must not sit
        idle next to a non-empty queue."""
        queued = [_task(REMOTE, "r1"), _task(OTHER_REMOTE, "r2")]
        out = claim_affinity.soft_affinity_sort(queued, {LOCAL})
        self.assertEqual([t["slug"] for t in out], ["r1", "r2"])

    def test_fallthrough_can_be_switched_off(self):
        """A machine can be pinned to its own projects — but then it claims nothing
        rather than claiming someone else's work."""
        with patch.dict(os.environ, {"ORCH_SOFT_AFFINITY_FALLTHROUGH": "false"}):
            out = claim_affinity.soft_affinity_sort([_task(REMOTE)], {LOCAL})
        self.assertEqual(out, [])

    def test_disabling_affinity_returns_the_queue_untouched(self):
        queued = [_task(REMOTE, "r1"), _task(LOCAL, "l1")]
        with patch.dict(os.environ, {"ORCH_SOFT_AFFINITY": "false"}):
            out = claim_affinity.soft_affinity_sort(queued, {LOCAL})
        self.assertIs(out, queued)

    def test_unknown_locality_is_not_treated_as_remote(self):
        """`None` means "we could not work out what this machine holds". Sorting on that
        would be a guess; the queue passes through unchanged instead."""
        queued = [_task(REMOTE, "r1"), _task(LOCAL, "l1")]
        self.assertIs(claim_affinity.soft_affinity_sort(queued, None), queued)

    def test_an_empty_queue_stays_empty(self):
        self.assertEqual(claim_affinity.soft_affinity_sort([], {LOCAL}), [])

    def test_a_task_with_no_project_is_treated_as_remote_not_crashed_on(self):
        out = claim_affinity.soft_affinity_sort([{"slug": "orphan"}], {LOCAL})
        self.assertEqual([t["slug"] for t in out], ["orphan"])


class TestAffinityScore(AffinityTestCase):

    def test_local_outranks_remote(self):
        self.assertLess(
            claim_affinity.affinity_score(_task(LOCAL), {LOCAL}),
            claim_affinity.affinity_score(_task(REMOTE), {LOCAL}),
        )

    def test_score_is_zero_when_locality_is_unknown(self):
        """Unknown must not silently score as remote, or every task looks like a
        fallback claim and every claim triggers a bootstrap fetch."""
        self.assertEqual(claim_affinity.affinity_score(_task(REMOTE), None), 0)

    def test_a_task_with_no_project_scores_remote(self):
        self.assertEqual(claim_affinity.affinity_score({}, {LOCAL}), 1)


class TestBootstrapOnFallback(AffinityTestCase):
    """The fetch that makes a fallback claim usable. Threads are started for real;
    only the git call underneath is replaced."""

    def _run_fallthrough(self, tasks, local=frozenset({LOCAL})):
        started = []
        real_thread = claim_affinity.threading.Thread

        def capture(*args, **kwargs):
            th = real_thread(*args, **kwargs)
            started.append(kwargs.get("args") or ())
            return th

        with patch.dict(os.environ, {"ORCH_BOOTSTRAP_ON_FALLBACK": "true"}), \
             patch.object(claim_affinity.threading, "Thread", side_effect=capture):
            claim_affinity.soft_affinity_sort(list(tasks), set(local))
        return started

    def test_each_remote_project_is_bootstrapped_once(self):
        """Two tasks from one project are one fetch, not two — the dedupe is the point."""
        started = self._run_fallthrough([
            _task(REMOTE, "r1", "main"), _task(REMOTE, "r2", "main"), _task(OTHER_REMOTE, "r3", "dev"),
        ])
        self.assertEqual([a[0] for a in started], [REMOTE, OTHER_REMOTE])
        self.assertEqual([a[1] for a in started], ["main", "dev"])

    def test_a_task_with_no_base_branch_defaults_rather_than_failing(self):
        started = self._run_fallthrough([{"project_id": REMOTE, "slug": "r"}])
        self.assertEqual(started, [(REMOTE, "master")])

    def test_no_bootstrap_when_there_is_local_work(self):
        """Local work means no fallback claim, so nothing to pre-fetch."""
        started = self._run_fallthrough([_task(LOCAL, "l1"), _task(REMOTE, "r1")])
        self.assertEqual(started, [])

    def test_bootstrap_can_be_switched_off(self):
        with patch.dict(os.environ, {"ORCH_BOOTSTRAP_ON_FALLBACK": "false"}), \
             patch.object(claim_affinity.threading, "Thread") as thread:
            claim_affinity.soft_affinity_sort([_task(REMOTE)], {LOCAL})
        thread.assert_not_called()


class TestDoBootstrapIsFailSoft(AffinityTestCase):
    """Claiming must never fail because a pre-fetch did. The fetch is an optimisation."""

    def test_an_unknown_repo_path_is_a_no_op(self):
        with patch.object(claim_affinity, "_find_repo_path", return_value=None), \
             patch.object(claim_affinity.subprocess, "run") as run:
            claim_affinity._do_bootstrap(REMOTE, "master")
        run.assert_not_called()

    def test_a_git_failure_is_swallowed(self):
        with patch.object(claim_affinity, "_find_repo_path", return_value="/tmp"), \
             patch.object(claim_affinity.os.path, "isdir", return_value=True), \
             patch.object(claim_affinity.subprocess, "run", side_effect=OSError("git missing")):
            claim_affinity._do_bootstrap(REMOTE, "master")  # must not raise

    def test_the_in_flight_marker_is_released_after_a_failure(self):
        """Leaking the marker would make the project un-bootstrappable for the life of
        the process — a slow claim forever, with no error to explain it."""
        with patch.object(claim_affinity, "_find_repo_path", return_value="/tmp"), \
             patch.object(claim_affinity.os.path, "isdir", return_value=True), \
             patch.object(claim_affinity.subprocess, "run", side_effect=OSError("boom")):
            claim_affinity._do_bootstrap(REMOTE, "master")
        self.assertNotIn(REMOTE, claim_affinity._bootstrapping)

    def test_find_repo_path_survives_an_unreachable_db(self):
        with patch.dict(sys.modules, {"db": None}):
            self.assertIsNone(claim_affinity._find_repo_path(REMOTE))


class TestBootstrapForTask(AffinityTestCase):

    def test_it_bootstraps_the_tasks_base_branch(self):
        with patch.object(claim_affinity, "_do_bootstrap") as boot:
            claim_affinity.bootstrap_for_task(_task(REMOTE, "r", "release"))
        boot.assert_called_once_with(REMOTE, "release")

    def test_a_task_with_no_project_is_skipped(self):
        with patch.object(claim_affinity, "_do_bootstrap") as boot:
            claim_affinity.bootstrap_for_task({"slug": "orphan"})
        boot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
