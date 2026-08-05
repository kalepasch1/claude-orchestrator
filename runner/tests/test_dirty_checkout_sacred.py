"""Contract: no merge path may destroy uncommitted work in the MAIN checkout.

FOUR loss paths of this family have been found and fixed:
  1. merge_train / auto_conflict_resolver committing unverified merges   (d8db4535)
  2. continuous_merger's unconditional `reset --hard` on every task done  (48498b68)
  3. self_healing_merge stashing the main checkout and never popping      (2026-07-30)
  4. auto_conflict_resolver.resolve_repo opening with an unconditional
     `checkout base` + `reset --hard HEAD`                                (820ad37b)

(4) was the worst of them: it left no stash, so sentinel.wip_stash_rescue — which makes
stashed work unloseable by branching it — had nothing to preserve. Work simply vanished.
Confirmed live 2026-08-05 reverting an in-progress edit to runner/db.py.

The operator's standing directive is that this class CANNOT recur, so it is pinned here.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auto_conflict_resolver as acr  # noqa: E402
import continuous_merger as cm  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _mkrepo():
    repo = tempfile.mkdtemp(prefix="sacred-")
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t")
    with open(os.path.join(repo, "keep.py"), "w") as f:
        f.write("ORIGINAL = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


PRECIOUS = "PRECIOUS_UNCOMMITTED_WORK = 'do not destroy'\n"


class ResolveRepoRefusesDirtyCheckout(unittest.TestCase):
    def test_refuses_and_preserves(self):
        repo = _mkrepo()
        with open(os.path.join(repo, "keep.py"), "w") as f:
            f.write(PRECIOUS)

        result = acr.resolve_repo(repo, "master")

        self.assertTrue(result.get("refused"),
                        "resolve_repo must refuse a dirty main checkout")
        self.assertEqual(result.get("total_merged"), 0)
        with open(os.path.join(repo, "keep.py")) as f:
            self.assertEqual(f.read(), PRECIOUS,
                             "resolve_repo destroyed uncommitted work")

    def test_clean_checkout_is_not_refused(self):
        repo = _mkrepo()
        result = acr.resolve_repo(repo, "master")
        self.assertFalse(result.get("refused"),
                         "a clean checkout must not be refused")

    def test_untracked_files_alone_do_not_block(self):
        """Untracked scratch files are not work `reset --hard` would destroy."""
        repo = _mkrepo()
        with open(os.path.join(repo, "scratch.log"), "w") as f:
            f.write("noise\n")
        result = acr.resolve_repo(repo, "master")
        self.assertFalse(result.get("refused"))


class ContinuousMergerRefusesDirtyCheckout(unittest.TestCase):
    def test_refuses_and_preserves(self):
        repo = _mkrepo()
        _git(repo, "checkout", "-q", "-b", "agent/x")
        _git(repo, "checkout", "-q", "master")
        with open(os.path.join(repo, "keep.py"), "w") as f:
            f.write(PRECIOUS)

        res = cm._merge_branch(repo, "agent/x", "master", {"slug": "x"})

        self.assertFalse(res["merged"])
        self.assertEqual(res["strategy"], "skipped-dirty")
        with open(os.path.join(repo, "keep.py")) as f:
            self.assertEqual(f.read(), PRECIOUS,
                             "continuous_merger destroyed uncommitted work")


class NoUnconditionalResetOnMainCheckout(unittest.TestCase):
    """Static guard: every `reset --hard` on a MAIN checkout must be dirt-aware.

    Cheap to keep, and it catches a reintroduction in review rather than in production.
    """

    def test_resolve_repo_checks_dirt_before_reset(self):
        import inspect
        src = inspect.getsource(acr.resolve_repo)
        self.assertIn("_dirty_tracked", src)
        reset_at = src.find('"reset", "--hard"')
        dirty_at = src.find("_dirty_tracked")
        self.assertNotEqual(reset_at, -1)
        self.assertLess(dirty_at, reset_at,
                        "the dirt check must come BEFORE the reset")

    def test_merge_branch_checks_dirt_before_reset(self):
        import inspect
        src = inspect.getsource(cm._merge_branch)
        reset_at = src.find('"reset", "--hard"')
        dirty_at = src.find("status")
        self.assertNotEqual(reset_at, -1)
        self.assertLess(dirty_at, reset_at,
                        "the dirt check must come BEFORE the reset")


if __name__ == "__main__":
    unittest.main()
