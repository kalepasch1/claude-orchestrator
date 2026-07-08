import os
import unittest

RUNNER_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner.py")


class RunnerLegacyMergeUsesIsolatedRebaseTest(unittest.TestCase):
    """Source-level regression guard: the legacy local-merge path in runner.py used to run
    `git rebase base branch` directly with cwd=repo (the primary checkout) — this asserts it now
    delegates to approval_merge._rebase_isolated instead, so a future edit can't silently
    reintroduce the direct-checkout-in-primary-repo pattern at this call site."""

    def setUp(self):
        self.src = open(RUNNER_PY, encoding="utf-8").read()

    def test_no_direct_rebase_with_repo_cwd_pattern_remains(self):
        self.assertNotIn('subprocess.run(["git", "rebase", base, branch], cwd=repo', self.src)

    def test_calls_approval_merge_rebase_isolated(self):
        self.assertIn("approval_merge._rebase_isolated(repo, base, branch)", self.src)


if __name__ == "__main__":
    unittest.main()
