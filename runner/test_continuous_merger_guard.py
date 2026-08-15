"""Contract test: continuous_merger must never commit an UNVERIFIED merge.

THE BUG THIS PINS (fixed 2026-08-04): _merge_branch ran a bare `git merge` for
the clean case, deleted the branch, and reported merged — with none of the
anti-loss gates. A branch that silently deletes/guts an implementation merges
CLEANLY, so the improvement was reverted and the only surviving copy (the
branch) was destroyed. This was a primary mechanism behind the 2026-08-04
phantom-merge reclassification.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import continuous_merger  # noqa: E402

REAL_IMPL = """export function assessCredit(input) {
  // real scoring: many branches of business logic
  const score = input.history * 0.6 + input.income * 0.4;
  if (score > 700) return { tier: 'prime', score };
  if (score > 500) return { tier: 'standard', score };
  return { tier: 'subprime', score };
}
"""


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


class ContinuousMergerGuardTest(unittest.TestCase):
    def _mkrepo(self):
        repo = tempfile.mkdtemp(prefix="cm-guard-")
        _git(repo, "init", "-q", "-b", "master")
        _git(repo, "config", "user.name", "t")
        _git(repo, "config", "user.email", "t@t")
        return repo

    def test_clean_merge_that_deletes_impl_is_blocked_and_branch_preserved(self):
        repo = self._mkrepo()
        with open(os.path.join(repo, "credit.js"), "w") as f:
            f.write(REAL_IMPL)
        with open(os.path.join(repo, "other.js"), "w") as f:
            f.write("export const A = 1;\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "real implementation")

        # agent branch: commits a tree WITHOUT credit.js (the silent-drop class)
        _git(repo, "checkout", "-q", "-b", "agent/drop")
        os.remove(os.path.join(repo, "credit.js"))
        with open(os.path.join(repo, "other.js"), "w") as f:
            f.write("export const A = 2;\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "agent work (tree missing credit.js)")
        _git(repo, "checkout", "-q", "master")

        pre = _git(repo, "rev-parse", "HEAD").stdout.strip()
        res = continuous_merger._merge_branch(
            repo, "agent/drop", "master", {"slug": "drop"})

        self.assertFalse(res["merged"],
                         "unverified clean merge went through: %r" % res)
        # master must be exactly where it was
        self.assertEqual(pre, _git(repo, "rev-parse", "HEAD").stdout.strip())
        # the implementation must still exist on master
        self.assertTrue(os.path.exists(os.path.join(repo, "credit.js")))
        # the branch (only other copy of the work) must be preserved
        self.assertEqual(
            _git(repo, "rev-parse", "--verify", "agent/drop").returncode, 0,
            "branch was deleted after a blocked merge")

    def test_harmless_clean_merge_still_goes_through(self):
        repo = self._mkrepo()
        with open(os.path.join(repo, "a.js"), "w") as f:
            f.write("export const A = 1;\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")
        _git(repo, "checkout", "-q", "-b", "agent/add")
        with open(os.path.join(repo, "b.js"), "w") as f:
            f.write("export const B = 2;\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "additive work")
        _git(repo, "checkout", "-q", "master")

        res = continuous_merger._merge_branch(
            repo, "agent/add", "master", {"slug": "add"})
        self.assertTrue(res["merged"], "harmless additive merge blocked: %r" % res)
        self.assertTrue(os.path.exists(os.path.join(repo, "b.js")))

    def test_fail_closed_without_resolver(self):
        repo = self._mkrepo()
        with open(os.path.join(repo, "a.js"), "w") as f:
            f.write("export const A = 1;\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")
        _git(repo, "checkout", "-q", "-b", "agent/x")
        with open(os.path.join(repo, "b.js"), "w") as f:
            f.write("export const B = 2;\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "work")
        _git(repo, "checkout", "-q", "master")

        saved = continuous_merger.auto_conflict_resolver
        continuous_merger.auto_conflict_resolver = None
        try:
            res = continuous_merger._merge_branch(
                repo, "agent/x", "master", {"slug": "x"})
        finally:
            continuous_merger.auto_conflict_resolver = saved
        self.assertFalse(res["merged"],
                         "merge committed with no gate stack available")
        self.assertEqual(
            _git(repo, "rev-parse", "--verify", "agent/x").returncode, 0)


if __name__ == "__main__":
    unittest.main()
