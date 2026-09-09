"""Fleet branch-share regression: a branch created on Mac A must be visible to the
sweeper/merge-train on Mac B once pushed to origin (root cause of the
recover-missing-branch churn: two Macs, one queue, local-only branches)."""
import ast
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import integration_sweeper
import merge_train


#: Every subprocess in this file is bounded at the call site.
#
# `runner/tests/conftest.py` injects a 30s bound and raises UnboundedSubprocessInTest
# for any test child spawned without one, deliberately warning rather than failing so
# the guard could land without turning the suite red. That safety net is not a licence
# to leave the bound implicit: the merge train reported this file by name
# ("undedSubprocessInTest: subprocess.run() called with no timeout from a test") while
# rebasing agent/dropbox-beethoven-core-integrity-audit-merge-safety-self-protection,
# and a warning nobody clears is a warning nobody reads.
#
# 60s matches the sibling that already got this right,
# runner/tests/test_20260816_branch_share_fetch.py — same fixture shape, same git
# clone/push operations against a local bare origin.
GIT_TIMEOUT_S = 60


def _git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                          timeout=GIT_TIMEOUT_S)


class BranchShareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.origin = os.path.join(root, "origin.git")
        subprocess.run(["git", "init", "--bare", self.origin], capture_output=True,
                       timeout=GIT_TIMEOUT_S)
        self.mac_a = os.path.join(root, "mac_a")
        self.mac_b = os.path.join(root, "mac_b")
        subprocess.run(["git", "clone", self.origin, self.mac_a], capture_output=True,
                       timeout=GIT_TIMEOUT_S)
        for repo in (self.mac_a,):
            _git(repo, "config", "user.email", "t@t")
            _git(repo, "config", "user.name", "t")
        open(os.path.join(self.mac_a, "f.txt"), "w").write("base\n")
        _git(self.mac_a, "add", "."); _git(self.mac_a, "commit", "-m", "base")
        _git(self.mac_a, "branch", "-M", "main")
        _git(self.mac_a, "push", "-u", "origin", "main")
        subprocess.run(["git", "clone", self.origin, self.mac_b], capture_output=True,
                       timeout=GIT_TIMEOUT_S)
        _git(self.mac_b, "config", "user.email", "t@t")
        _git(self.mac_b, "config", "user.name", "t")
        # Mac A does agent work and pushes the agent branch (the runner.py branch-share step)
        _git(self.mac_a, "checkout", "-b", "agent/test-slug")
        open(os.path.join(self.mac_a, "g.txt"), "w").write("work\n")
        _git(self.mac_a, "add", "."); _git(self.mac_a, "commit", "-m", "agent work")
        _git(self.mac_a, "push", "-u", "origin", "agent/test-slug")
        integration_sweeper._FETCHED_AGENT_REFS.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_only_check_misses_remote_branch(self):
        # documents the old bug: purely local check on Mac B cannot see Mac A's branch
        self.assertFalse(integration_sweeper._branch_exists(self.mac_b, "agent/test-slug"))

    def test_sweeper_sees_remote_branch(self):
        self.assertTrue(integration_sweeper._branch_exists_anywhere(self.mac_b, "agent/test-slug"))

    def test_sweeper_still_false_for_truly_missing(self):
        self.assertFalse(integration_sweeper._branch_exists_anywhere(self.mac_b, "agent/nope"))

    def test_merge_train_materializes_local_ref(self):
        self.assertTrue(merge_train._materialize_branch(self.mac_b, "agent/test-slug"))
        self.assertEqual(_git(self.mac_b, "rev-parse", "--verify", "agent/test-slug").returncode, 0)

    def test_materialize_false_when_absent_everywhere(self):
        self.assertFalse(merge_train._materialize_branch(self.mac_b, "agent/absent"))

    def test_no_repo_is_fail_soft(self):
        self.assertFalse(integration_sweeper._branch_exists_anywhere("", "agent/x"))
        self.assertFalse(integration_sweeper._branch_exists_anywhere("/nonexistent/path", "agent/x"))


class SubprocessBoundsTest(unittest.TestCase):
    """Every child this file spawns must carry an explicit timeout.

    conftest injects a 30s bound and warns rather than failing, so an unbounded call
    here is invisible at runtime and only surfaces as merge-train noise — which is how
    this file drifted in the first place. Asserting on the source keeps the bound
    explicit at the call site instead of relying on the safety net.
    """

    def test_every_subprocess_run_in_this_file_passes_a_timeout(self):
        with open(os.path.abspath(__file__)) as fh:
            source = fh.read()
        tree = ast.parse(source)
        unbounded = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name not in ("run", "check_output", "call", "check_call"):
                continue
            mod = getattr(getattr(func, "value", None), "id", None)
            if mod != "subprocess":
                continue
            if not any(kw.arg == "timeout" for kw in node.keywords):
                unbounded.append(node.lineno)
        self.assertEqual(unbounded, [],
                         f"subprocess call(s) with no timeout= at line(s) {unbounded}")


if __name__ == "__main__":
    unittest.main()
