"""Regression tests: auto-rebase must never park the primary checkout on an agent branch.

conflict_auto_resolve.attempt_auto_rebase runs against projects.repo_path — the PRIMARY
checkout. It used to `git checkout <agent branch>` and never return, leaving the primary
tree parked there (1001 checkout-drift events by 2026-07-16). That drift is load-bearing:
while parked on an agent branch the repo runs THAT branch's code and honours THAT branch's
.gitignore, so fixes committed to master go inert precisely when they matter. It is the
upstream cause of the intake-drop losses.

Stdlib + unittest.mock only (runner convention).
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import conflict_auto_resolve as car


class _GitRecorder:
    """Records git calls and simulates the checked-out branch."""

    def __init__(self, current="master", rebase_rc=0, checkout_fails_for=()):
        self.current = current
        self.rebase_rc = rebase_rc
        self.checkout_fails_for = set(checkout_fails_for)
        self.calls = []

    def __call__(self, *args, cwd=None, timeout=60):
        self.calls.append(args)
        if args[:2] == ("branch", "--show-current"):
            return 0, self.current
        if args[0] == "checkout":
            target = args[1]
            if target in self.checkout_fails_for:
                return 1, ""
            self.current = target
            return 0, ""
        if args[0] == "rebase":
            if len(args) > 1 and args[1] == "--abort":
                return 0, ""
            return self.rebase_rc, "" if self.rebase_rc == 0 else "CONFLICT"
        return 0, ""


def _run(recorder, branch="agent/x", base="master", repo="/repo"):
    with mock.patch.object(car, "_git", side_effect=recorder), \
         mock.patch.object(car, "ENABLED", True), \
         mock.patch.object(os.path, "isdir", return_value=True), \
         mock.patch.object(car, "log"):
        return car.attempt_auto_rebase(branch, base, repo)


class TestNoDrift(unittest.TestCase):
    def test_returns_to_original_branch_on_success(self):
        g = _GitRecorder(current="master", rebase_rc=0)
        self.assertTrue(_run(g))
        self.assertEqual(g.current, "master", "primary checkout was left drifted after success")

    def test_returns_to_original_branch_on_rebase_failure(self):
        g = _GitRecorder(current="master", rebase_rc=1)
        self.assertFalse(_run(g))
        self.assertEqual(g.current, "master", "primary checkout was left drifted after failure")

    def test_returns_to_non_master_original_branch(self):
        """Whatever branch we found, we put back — not a hardcoded 'master'."""
        g = _GitRecorder(current="release/v2", rebase_rc=0)
        self.assertTrue(_run(g))
        self.assertEqual(g.current, "release/v2")

    def test_restores_even_if_rebase_raises(self):
        """A crash mid-rebase must not strand the primary checkout."""
        calls = []

        def boom(*args, cwd=None, timeout=60):
            calls.append(args)
            if args[:2] == ("branch", "--show-current"):
                return 0, "master"
            if args[0] == "checkout":
                return 0, ""
            if args[0] == "rebase":
                raise RuntimeError("git exploded")
            return 0, ""

        with mock.patch.object(car, "_git", side_effect=boom), \
             mock.patch.object(car, "ENABLED", True), \
             mock.patch.object(os.path, "isdir", return_value=True), \
             mock.patch.object(car, "log"):
            with self.assertRaises(RuntimeError):
                car.attempt_auto_rebase("agent/x", "master", "/repo")

        # the finally block must still have issued a restoring checkout
        self.assertEqual(calls[-1], ("checkout", "master"))

    def test_skips_when_current_branch_unknown(self):
        """Detached HEAD: we cannot promise restoration, so don't move it at all."""

        def detached(*args, cwd=None, timeout=60):
            if args[:2] == ("branch", "--show-current"):
                return 0, ""
            raise AssertionError(f"must not run git {args} when HEAD is detached")

        with mock.patch.object(car, "_git", side_effect=detached), \
             mock.patch.object(car, "ENABLED", True), \
             mock.patch.object(os.path, "isdir", return_value=True), \
             mock.patch.object(car, "log"):
            self.assertFalse(car.attempt_auto_rebase("agent/x", "master", "/repo"))

    def test_no_checkout_when_target_branch_checkout_fails(self):
        g = _GitRecorder(current="master", checkout_fails_for={"agent/x"})
        self.assertFalse(_run(g))
        self.assertEqual(g.current, "master")


if __name__ == "__main__":
    unittest.main()
