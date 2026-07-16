"""Regression tests for sentinel.checkout_guard.

Pins the 2026-07-16 incident: checkout_guard used `git stash push -u`, which sweeps
untracked files. Every intake drop that landed in the ~2min window before a sentinel
tick was stashed and silently lost (282 sentinel-drift stashes over 8 days). These
tests fail if anyone reintroduces -u, or removes the escalation on a wedged checkout.

Stdlib + unittest.mock only (runner convention; no dependency manifest exists).
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sentinel


class _R:
    """Stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _guard(git_impl, st=None):
    """Run checkout_guard with git mocked; return (calls, state)."""
    calls = []

    def fake_git(*args, **kw):
        calls.append(args)
        return git_impl(*args)

    st = {} if st is None else st
    with mock.patch.object(sentinel, "git", side_effect=fake_git), \
         mock.patch.object(sentinel, "log"), \
         mock.patch.object(sentinel, "emit"), \
         mock.patch.object(os.path, "isdir", return_value=False):
        sentinel.checkout_guard(st)
    return calls, st


class TestNeverStashesUntracked(unittest.TestCase):
    def test_no_stash_uses_dash_u_when_checkout_blocked(self):
        """THE regression: -u must never appear in a stash invocation."""
        def git_impl(*args):
            if args[:2] == ("branch", "--show-current"):
                return _R(stdout="agent/some-branch\n")
            if args[0] == "checkout":
                return _R(returncode=1, stderr="error: local changes")
            if args[0] == "status":
                return _R(stdout=" M runner/db.py\n")
            return _R()

        calls, _ = _guard(git_impl)
        stashes = [c for c in calls if c and c[0] == "stash"]
        self.assertTrue(stashes, "expected a stash attempt when checkout is blocked")
        for c in stashes:
            self.assertNotIn("-u", c, f"stash must never sweep untracked files: {c}")
            self.assertNotIn("--include-untracked", c)

    def test_status_check_excludes_untracked(self):
        """Dirty-check must ignore untracked files, or it stashes for no reason."""
        def git_impl(*args):
            if args[:2] == ("branch", "--show-current"):
                return _R(stdout="agent/x\n")
            if args[0] == "checkout":
                return _R(returncode=1, stderr="blocked")
            if args[0] == "status":
                return _R(stdout="")
            return _R()

        calls, _ = _guard(git_impl)
        status = [c for c in calls if c and c[0] == "status"]
        self.assertTrue(status)
        for c in status:
            self.assertIn("--untracked-files=no", c)

    def test_clean_switch_does_not_stash_at_all(self):
        """If checkout succeeds outright, nothing should be stashed."""
        def git_impl(*args):
            if args[:2] == ("branch", "--show-current"):
                return _R(stdout="agent/x\n")
            return _R()

        calls, _ = _guard(git_impl)
        self.assertEqual([c for c in calls if c and c[0] == "stash"], [])


class TestEscalation(unittest.TestCase):
    def test_wedged_checkout_escalates_after_threshold(self):
        def git_impl(*args):
            if args[:2] == ("branch", "--show-current"):
                return _R(stdout="agent/wedged\n")
            if args[0] == "checkout":
                return _R(returncode=1, stderr="cannot switch")
            if args[0] == "status":
                return _R(stdout="")
            return _R()

        st = {}
        for _ in range(sentinel.DRIFT_ALERT_AFTER):
            _guard(git_impl, st)
        self.assertEqual(st["drift_fail_count"], sentinel.DRIFT_ALERT_AFTER)
        self.assertEqual(st["drift_branch"], "agent/wedged")

    def test_counter_resets_once_back_on_base(self):
        def stuck(*args):
            if args[:2] == ("branch", "--show-current"):
                return _R(stdout="agent/wedged\n")
            if args[0] == "checkout":
                return _R(returncode=1, stderr="no")
            if args[0] == "status":
                return _R(stdout="")
            return _R()

        def healthy(*args):
            if args[:2] == ("branch", "--show-current"):
                return _R(stdout=sentinel.BASE_BRANCH + "\n")
            return _R()

        st = {}
        _guard(stuck, st)
        self.assertEqual(st["drift_fail_count"], 1)
        _guard(healthy, st)
        self.assertNotIn("drift_fail_count", st)

    def test_no_action_while_rebase_in_progress(self):
        calls = []

        def fake_git(*args, **kw):
            calls.append(args)
            return _R()

        with mock.patch.object(sentinel, "git", side_effect=fake_git), \
             mock.patch.object(sentinel, "log"), \
             mock.patch.object(os.path, "isdir", return_value=True):
            sentinel.checkout_guard({})
        self.assertEqual(calls, [], "must not interfere with an in-progress rebase")


if __name__ == "__main__":
    unittest.main()
