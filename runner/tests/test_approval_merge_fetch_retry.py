import os
import sys
import unittest
from unittest.mock import patch, call, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import approval_merge as am


def _proc(returncode=0):
    p = MagicMock()
    p.returncode = returncode
    return p


REPO = "/fake/repo"
BRANCH = "agent/my-task"


class FetchAndCheckBranchTest(unittest.TestCase):
    def test_returns_true_when_fetch_succeeds_and_branch_exists(self):
        rev_parse_ok = _proc(0)
        fetch_ok = _proc(0)
        with patch("subprocess.run", side_effect=[fetch_ok, rev_parse_ok]):
            self.assertTrue(am._fetch_and_check_branch(REPO, BRANCH))

    def test_returns_false_when_fetch_succeeds_but_branch_still_absent(self):
        with patch("subprocess.run", side_effect=[_proc(0), _proc(1)]):
            self.assertFalse(am._fetch_and_check_branch(REPO, BRANCH))

    def test_retries_on_fetch_failure_and_succeeds_on_second_attempt(self):
        # First fetch fails, second fetch succeeds, branch then found.
        side_effects = [_proc(1), _proc(0), _proc(0)]
        with patch("subprocess.run", side_effect=side_effects) as mock_run, \
             patch("time.sleep") as mock_sleep:
            result = am._fetch_and_check_branch(REPO, BRANCH)

        self.assertTrue(result)
        fetch_calls = [c for c in mock_run.call_args_list
                       if c.args[0][:2] == ["git", "fetch"]]
        self.assertEqual(len(fetch_calls), 2)
        mock_sleep.assert_called_once_with(am.FETCH_BACKOFF_SECONDS)

    def test_all_retries_exhausted_returns_false(self):
        with patch("subprocess.run", return_value=_proc(1)) as mock_run, \
             patch("time.sleep") as mock_sleep:
            result = am._fetch_and_check_branch(REPO, BRANCH)

        self.assertFalse(result)
        fetch_calls = [c for c in mock_run.call_args_list
                       if c.args[0][:2] == ["git", "fetch"]]
        self.assertEqual(len(fetch_calls), am.MAX_FETCH_RETRIES)
        self.assertEqual(mock_sleep.call_count, am.MAX_FETCH_RETRIES - 1)

    def test_no_sleep_after_final_attempt(self):
        # Sleep should only happen between retries, not after the last one.
        with patch("subprocess.run", return_value=_proc(1)), \
             patch("time.sleep") as mock_sleep:
            am._fetch_and_check_branch(REPO, BRANCH)
        self.assertEqual(mock_sleep.call_count, am.MAX_FETCH_RETRIES - 1)

    def test_exception_during_fetch_is_swallowed_and_retried(self):
        side_effects = [OSError("network down"), _proc(0), _proc(0)]
        with patch("subprocess.run", side_effect=side_effects), \
             patch("time.sleep"):
            result = am._fetch_and_check_branch(REPO, BRANCH)
        self.assertTrue(result)

    def test_total_wall_time_under_five_seconds(self):
        """Validate that 2 retries * 1.5s backoff = 3s sleep < 5s limit."""
        total_sleep = (am.MAX_FETCH_RETRIES - 1) * am.FETCH_BACKOFF_SECONDS
        self.assertLess(total_sleep, 5.0)

    def test_branch_found_after_one_failed_fetch_simulates_lag(self):
        """Branch appears after transient lag: fail once, succeed on retry."""
        side_effects = [_proc(1), _proc(0), _proc(0)]
        with patch("subprocess.run", side_effect=side_effects), \
             patch("time.sleep") as mock_sleep:
            found = am._fetch_and_check_branch(REPO, BRANCH)

        self.assertTrue(found)
        mock_sleep.assert_called_once_with(1.5)

    def test_uses_origin_remote_by_default(self):
        with patch("subprocess.run", side_effect=[_proc(0), _proc(0)]) as mock_run:
            am._fetch_and_check_branch(REPO, BRANCH)
        fetch_call = mock_run.call_args_list[0]
        self.assertEqual(fetch_call.args[0], ["git", "fetch", "origin"])

    def test_custom_remote_is_passed_through(self):
        with patch("subprocess.run", side_effect=[_proc(0), _proc(0)]) as mock_run:
            am._fetch_and_check_branch(REPO, BRANCH, remote="upstream")
        fetch_call = mock_run.call_args_list[0]
        self.assertEqual(fetch_call.args[0], ["git", "fetch", "upstream"])


if __name__ == "__main__":
    unittest.main()
