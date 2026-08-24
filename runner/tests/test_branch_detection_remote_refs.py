"""A branch that was pushed is not missing, even after its local ref is gone.

The missing-branch owner path (runner/auto_remediate.py classifies, then
runner/agentic_repair.repair_patch() decides) acts on what the detectors here
report. `detect_missing_branches` used to ask `git branch --list agent/*`,
which reads refs/heads only.

Per the worktree convention in CLAUDE.md the agent pushes `agent/{slug}` and
the worktree is then removed, and on every other machine in the fleet that
branch has only ever existed as a remote-tracking ref. So the local-only
lookup reported successfully-pushed work as missing, which queues a recovery,
which forks one change into two branches and hands the merge train the exact
conflict the recovery was supposed to prevent.

These tests build a real repository with a real bare origin rather than
mocking git, because the whole defect lives in which ref namespace git was
asked about — a mock would have to encode the answer under test.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_detection  # noqa: E402


def _run(cwd, *args):
    subprocess.run(
        args, cwd=cwd, check=True, timeout=30,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class RemoteRefAwareness(unittest.TestCase):
    """A pushed-then-pruned branch must read as present, not missing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.origin = os.path.join(root, "origin.git")
        self.repo = os.path.join(root, "work")

        _run(root, "git", "init", "--bare", "-q", self.origin)
        _run(root, "git", "clone", "-q", self.origin, self.repo)
        _run(self.repo, "git", "config", "user.email", "kalepasch@gmail.com")
        _run(self.repo, "git", "config", "user.name", "kalepasch1")
        with open(os.path.join(self.repo, "README.md"), "w") as fh:
            fh.write("seed\n")
        _run(self.repo, "git", "add", "-A")
        _run(self.repo, "git", "commit", "-q", "-m", "seed")
        _run(self.repo, "git", "branch", "-M", "master")
        _run(self.repo, "git", "push", "-q", "-u", "origin", "master")

    def tearDown(self):
        self._tmp.cleanup()

    def _push_and_prune(self, slug):
        """Do what an agent run does: push agent/<slug>, then drop the local ref."""
        _run(self.repo, "git", "branch", f"agent/{slug}", "master")
        _run(self.repo, "git", "push", "-q", "origin", f"agent/{slug}")
        _run(self.repo, "git", "branch", "-D", f"agent/{slug}")

    # -- the regression ----------------------------------------------------

    def test_pushed_then_pruned_branch_is_not_reported_missing(self):
        self._push_and_prune("shipped-slug")
        tasks = [{"slug": "shipped-slug", "state": "QUEUED"}]

        missing = branch_detection.detect_missing_branches(self.repo, tasks)

        self.assertEqual(
            missing, [],
            "a branch that IS on origin was reported missing — this is the "
            "false positive that forks work into a second branch",
        )

    def test_pushed_then_pruned_branch_lists_as_an_agent_branch(self):
        self._push_and_prune("shipped-slug")
        self.assertIn("shipped-slug", branch_detection._list_agent_branches(self.repo))

    def test_pushed_then_pruned_branch_classifies_healthy_not_missing(self):
        """The single-branch classifier must agree with the batch sweep."""
        self._push_and_prune("shipped-slug")
        tasks = [{"slug": "shipped-slug", "state": "QUEUED"}]

        result = branch_detection.classify_branch_state(
            self.repo, "shipped-slug", tasks=tasks
        )

        self.assertEqual(result["state"], "healthy")

    # -- behaviour that must NOT change ------------------------------------

    def test_a_genuinely_absent_branch_is_still_reported_missing(self):
        """The widened lookup must not swallow the case recovery exists for."""
        tasks = [{"slug": "never-pushed", "state": "QUEUED"}]

        missing = branch_detection.detect_missing_branches(self.repo, tasks)

        self.assertEqual([t["slug"] for t in missing], ["never-pushed"])
        self.assertEqual(
            branch_detection.classify_branch_state(
                self.repo, "never-pushed", tasks=tasks
            )["state"],
            "missing",
        )

    def test_a_local_only_branch_still_counts_as_existing(self):
        """Widening added remotes; it must not have dropped refs/heads."""
        _run(self.repo, "git", "branch", "agent/local-only", "master")
        tasks = [{"slug": "local-only", "state": "QUEUED"}]

        self.assertIn("local-only", branch_detection._list_agent_branches(self.repo))
        self.assertEqual(branch_detection.detect_missing_branches(self.repo, tasks), [])

    def test_a_slug_containing_a_slash_keeps_its_full_name(self):
        """`agent/a/b` is slug `a/b`, not `b` — splitting on the last slash
        would silently rename the task and make the branch unfindable."""
        _run(self.repo, "git", "branch", "agent/nested/slug", "master")
        self.assertIn("nested/slug", branch_detection._list_agent_branches(self.repo))

    def test_a_remote_branch_only_containing_agent_does_not_masquerade(self):
        """`origin/feature/agent/x` is not `agent/x`. Reading any ref with
        `/agent/` in it as an agent branch would mark a genuinely lost branch
        healthy — a false negative, which is the failure that loses work."""
        _run(self.repo, "git", "branch", "feature/agent/x", "master")
        _run(self.repo, "git", "push", "-q", "origin", "feature/agent/x")
        _run(self.repo, "git", "branch", "-D", "feature/agent/x")

        self.assertNotIn("x", branch_detection._list_agent_branches(self.repo))
        tasks = [{"slug": "x", "state": "QUEUED"}]
        self.assertEqual(
            [t["slug"] for t in branch_detection.detect_missing_branches(self.repo, tasks)],
            ["x"],
        )

    def test_a_pushed_branch_is_not_orphaned_when_a_task_claims_it(self):
        self._push_and_prune("shipped-slug")
        self.assertEqual(
            branch_detection.detect_orphaned_branches(self.repo, {"shipped-slug"}), []
        )

    def test_a_pushed_branch_with_no_task_is_still_orphaned(self):
        """Remote-only branches become visible to the orphan sweep too, which
        is the point: they were previously invisible to it as well."""
        self._push_and_prune("nobody-owns-me")
        self.assertEqual(
            branch_detection.detect_orphaned_branches(self.repo, {"some-other-slug"}),
            ["nobody-owns-me"],
        )

    def test_only_active_tasks_are_considered(self):
        tasks = [{"slug": "never-pushed", "state": "DONE"}]
        self.assertEqual(branch_detection.detect_missing_branches(self.repo, tasks), [])

    # -- fail-soft ---------------------------------------------------------

    def test_a_non_repo_path_reports_nothing_rather_than_everything(self):
        """"Could not tell" must never be read as "all branches are lost" —
        that would queue a recovery for every active task at once."""
        with tempfile.TemporaryDirectory() as plain:
            tasks = [{"slug": "never-pushed", "state": "QUEUED"}]
            self.assertEqual(branch_detection._list_agent_branches(plain), set())
            self.assertEqual(
                branch_detection.detect_missing_branches(
                    os.path.join(plain, "does-not-exist"), tasks
                ),
                [],
            )

    def test_no_tasks_and_no_branches_are_both_tolerated(self):
        self.assertEqual(branch_detection.detect_missing_branches(self.repo, None), [])
        self.assertEqual(branch_detection.detect_orphaned_branches(self.repo, None), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
