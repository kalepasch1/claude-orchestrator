"""Regression tests: auto-rebase must never park the primary checkout on an agent branch.

An auto-rebase runs against projects.repo_path — the PRIMARY checkout, not a
worktree. It used to `git checkout <agent branch>` and never return, leaving the
primary tree parked there (1001 checkout-drift events by 2026-07-16). That drift
is load-bearing: while parked on an agent branch the repo runs THAT branch's code
and honours THAT branch's .gitignore, so fixes committed to master go inert
precisely when they matter. It is the upstream cause of the intake-drop losses.

THIS FILE USED TO TEST A FUNCTION THAT NO LONGER EXISTS. It targeted
conflict_auto_resolve.attempt_auto_rebase, which was fixed for exactly this in
5e9b862a and 8b93a4f2 — "auto-rebase must not park the primary checkout on agent
branches" — and then deleted, along with the fix, when conflict_auto_resolve was
rewritten wholesale in 28a90157. All six tests have been red on
`module 'conflict_auto_resolve' does not have the attribute '_git'` since.

The invariant outlived the function. branch_repair_bot._auto_rebase is a second
copy of the same three lines and never received the fix, so that is what these
tests guard now. Nothing imports branch_repair_bot today — the defect there is
latent, not active — but .env.example documents its three variables as live
configuration, so it reads as wired and one import would arm it.

Stdlib + unittest.mock only (runner convention).
"""
import ast
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_repair_bot as brb


class _GitRecorder:
    """Records git calls and simulates the checked-out branch.

    Mirrors branch_repair_bot._git's contract: (returncode, stdout, stderr).
    """

    def __init__(self, current="master", rebase_rc=0, checkout_fails_for=(),
                 rebase_raises=False):
        self.current = current
        self.rebase_rc = rebase_rc
        self.checkout_fails_for = set(checkout_fails_for)
        self.rebase_raises = rebase_raises
        self.calls = []

    def __call__(self, repo, *args, timeout=30):
        self.calls.append(args)
        if args[:2] == ("branch", "--show-current"):
            return 0, self.current, ""
        if args[0] == "checkout":
            target = args[1]
            if target in self.checkout_fails_for:
                return 1, "", "error: pathspec"
            self.current = target
            return 0, "", ""
        if args[0] == "rebase":
            if len(args) > 1 and args[1] == "--abort":
                return 0, "", ""
            if self.rebase_raises:
                raise RuntimeError("git exploded")
            return self.rebase_rc, "", "" if self.rebase_rc == 0 else "CONFLICT"
        return 0, "", ""

    def checkouts(self):
        return [a[1] for a in self.calls if a[0] == "checkout"]


def _run(recorder, branch="agent/x", base="master", repo="/repo"):
    with mock.patch.object(brb, "_git", side_effect=recorder), \
         mock.patch.object(brb, "_log"):
        return brb._auto_rebase(repo, base, branch)


class TestNoDrift(unittest.TestCase):
    def test_returns_to_original_branch_on_success(self):
        g = _GitRecorder(current="master", rebase_rc=0)
        self.assertTrue(_run(g))
        self.assertEqual(g.current, "master",
                         "primary checkout was left drifted after success")

    def test_returns_to_original_branch_on_rebase_failure(self):
        g = _GitRecorder(current="master", rebase_rc=1)
        self.assertFalse(_run(g))
        self.assertEqual(g.current, "master",
                         "primary checkout was left drifted after a failed rebase")
        self.assertIn(("rebase", "--abort"), g.calls)

    def test_restores_even_if_rebase_raises(self):
        g = _GitRecorder(current="master", rebase_raises=True)
        with self.assertRaises(RuntimeError):
            _run(g)
        self.assertEqual(g.current, "master",
                         "an exception must not leave the checkout parked")

    def test_returns_to_non_master_original_branch(self):
        """Restores where it started, not a hardcoded 'master'."""
        g = _GitRecorder(current="orchestrator/dev", rebase_rc=0)
        self.assertTrue(_run(g))
        self.assertEqual(g.current, "orchestrator/dev")

    def test_skips_when_current_branch_unknown(self):
        """Detached HEAD: refuse rather than check out with nowhere to return."""
        g = _GitRecorder(current="", rebase_rc=0)
        self.assertFalse(_run(g))
        self.assertEqual(g.checkouts(), [], "checked out with no way back")

    def test_skips_when_the_branch_query_itself_fails(self):
        class _Broken(_GitRecorder):
            def __call__(self, repo, *args, timeout=30):
                self.calls.append(args)
                if args[:2] == ("branch", "--show-current"):
                    return -1, "", "not a git repository"
                return 0, "", ""
        g = _Broken()
        self.assertFalse(_run(g))
        self.assertEqual(g.checkouts(), [])

    def test_no_rebase_when_target_branch_checkout_fails(self):
        g = _GitRecorder(current="master", checkout_fails_for=("agent/x",))
        self.assertFalse(_run(g))
        self.assertEqual(g.current, "master")
        self.assertNotIn(("rebase", "master"), g.calls,
                         "rebased without having reached the branch")

    def test_already_on_the_branch_does_not_check_out_at_all(self):
        """Nothing to restore, and no pointless checkout churn."""
        g = _GitRecorder(current="agent/x", rebase_rc=0)
        self.assertTrue(_run(g))
        self.assertEqual(g.checkouts(), [])
        self.assertEqual(g.current, "agent/x")


class TestTheRestoreIsStructural(unittest.TestCase):
    """The restore has to be in a `finally`. On the success path only, any
    exception between the checkout and the return re-opens the whole defect —
    which is how it came back the first time."""

    def test_auto_rebase_restores_in_a_finally(self):
        tree = ast.parse(open(brb.__file__, encoding="utf-8").read())
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_auto_rebase")
        tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and n.finalbody]
        self.assertTrue(tries, "_auto_rebase must restore the branch in a finally")
        restored = any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id == "_git"
            and any(isinstance(a, ast.Constant) and a.value == "checkout" for a in c.args)
            for t in tries for stmt in t.finalbody for c in ast.walk(stmt))
        self.assertTrue(restored, "the finally block must check the original branch back out")


if __name__ == "__main__":
    unittest.main()
