"""Tests for fail-soft error handling in _run_task_safe and _block_or_retry."""
import os, sys, unittest
from unittest.mock import MagicMock, patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RunTaskSafeTest(unittest.TestCase):
    def _import_runner(self):
        import runner
        return runner

    @patch("runner.run_task", side_effect=RuntimeError("code execution boom"))
    @patch("runner._block_or_retry")
    @patch("runner.set_state")
    def test_exception_calls_block_or_retry(self, mock_set, mock_bor, mock_run):
        r = self._import_runner()
        r._run_task_safe({"id": "t-1", "slug": "s", "project_id": "p"})
        mock_bor.assert_called_once()
        self.assertIn("code execution boom", mock_bor.call_args[0][1])

    @patch("runner.run_task", side_effect=RuntimeError("boom"))
    @patch("runner._block_or_retry", side_effect=Exception("retry fails"))
    @patch("runner.set_state")
    def test_double_failure_does_not_raise(self, mock_set, mock_bor, mock_run):
        r = self._import_runner()
        r._run_task_safe({"id": "t-2", "slug": "s", "project_id": "p"})
        self.assertTrue(mock_set.called)

    @patch("runner.run_task")
    @patch("runner._block_or_retry")
    def test_success_no_block_or_retry(self, mock_bor, mock_run):
        r = self._import_runner()
        task = {"id": "t-3", "slug": "ok", "project_id": "p"}
        r._run_task_safe(task)
        mock_run.assert_called_once_with(task)
        mock_bor.assert_not_called()


class BlockOrRetryTest(unittest.TestCase):
    @patch("runner.set_state")
    @patch("runner.agentic_repair")
    @patch("retry_policy.decide", return_value={"action": "block", "note": "terminal", "transient_retries": 0})
    def test_terminal_failure_blocks(self, mock_decide, mock_ar, mock_set):
        import runner
        result = runner._block_or_retry({"id": "t-4", "slug": "bad", "transient_retries": 0}, "agent failed")
        self.assertEqual(result, "block")

    @patch("runner.time.sleep")
    @patch("runner.set_state")
    @patch("runner.agentic_repair")
    @patch("retry_policy.decide", return_value={"action": "requeue", "transient_retries": 1, "backoff_s": 5})
    def test_transient_requeues(self, mock_decide, mock_ar, mock_set, mock_sleep):
        import runner
        mock_ar.repair_patch.return_value = {"state": "QUEUED", "note": "requeued"}
        result = runner._block_or_retry({"id": "t-5", "slug": "retry", "transient_retries": 0}, "rate limit")
        self.assertEqual(result, "requeue")
        self.assertLessEqual(mock_sleep.call_args[0][0], 20)


if __name__ == "__main__":
    unittest.main()
