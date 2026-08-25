"""Tests for fail-soft error handling in _run_task_safe and _block_or_retry."""
import os, sys, unittest
from unittest.mock import MagicMock, patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_runner_entrypoint():
    """Load runner/runner.py by path, under a private module name.

    `import runner` is ambiguous here: runner/ is a package AND contains
    runner.py, so the bare name resolves to whichever comes first on sys.path.
    These tests patch set_state/_block_or_retry/agentic_repair, which live on the
    ENTRYPOINT; they used to reach it only because some earlier test module had
    left runner/ ahead of the repo root. conftest now keeps the root first so
    `from runner.X import Y` works suite-wide, so the entrypoint is loaded
    explicitly. Same fix as test_task_lifecycle and test_prompt_evolver_pipeline.
    """
    import importlib.util
    name = "runner_entrypoint_run_task_safe"
    if name in sys.modules:
        return sys.modules[name]
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


#: Loaded at import so the @patch("<name>.…") decorators below resolve to the
#: entrypoint rather than the package: a decorator written against the bare name
#: imports it, gets runner/__init__.py, and fails with "does not have the
#: attribute set_state".
_RUNNER = _load_runner_entrypoint()
_RUNNER_MOD = _RUNNER.__name__



class RunTaskSafeTest(unittest.TestCase):
    def _import_runner(self):
        runner = _load_runner_entrypoint()
        return runner

    @patch(f"{_RUNNER_MOD}.run_task", side_effect=RuntimeError("code execution boom"))
    @patch(f"{_RUNNER_MOD}._block_or_retry")
    @patch(f"{_RUNNER_MOD}.set_state")
    def test_exception_calls_block_or_retry(self, mock_set, mock_bor, mock_run):
        r = self._import_runner()
        r._run_task_safe({"id": "t-1", "slug": "s", "project_id": "p"})
        mock_bor.assert_called_once()
        self.assertIn("code execution boom", mock_bor.call_args[0][1])

    @patch(f"{_RUNNER_MOD}.run_task", side_effect=RuntimeError("boom"))
    @patch(f"{_RUNNER_MOD}._block_or_retry", side_effect=Exception("retry fails"))
    @patch(f"{_RUNNER_MOD}.set_state")
    def test_double_failure_does_not_raise(self, mock_set, mock_bor, mock_run):
        r = self._import_runner()
        r._run_task_safe({"id": "t-2", "slug": "s", "project_id": "p"})
        self.assertTrue(mock_set.called)

    @patch(f"{_RUNNER_MOD}.run_task")
    @patch(f"{_RUNNER_MOD}._block_or_retry")
    def test_success_no_block_or_retry(self, mock_bor, mock_run):
        r = self._import_runner()
        task = {"id": "t-3", "slug": "ok", "project_id": "p"}
        r._run_task_safe(task)
        mock_run.assert_called_once_with(task)
        mock_bor.assert_not_called()


class BlockOrRetryTest(unittest.TestCase):
    @patch(f"{_RUNNER_MOD}.set_state")
    @patch(f"{_RUNNER_MOD}.agentic_repair")
    @patch("retry_policy.decide", return_value={"action": "block", "note": "terminal", "transient_retries": 0})
    def test_terminal_failure_blocks(self, mock_decide, mock_ar, mock_set):
        runner = _load_runner_entrypoint()
        result = runner._block_or_retry({"id": "t-4", "slug": "bad", "transient_retries": 0}, "agent failed")
        self.assertEqual(result, "block")

    @patch(f"{_RUNNER_MOD}.time.sleep")
    @patch(f"{_RUNNER_MOD}.set_state")
    @patch(f"{_RUNNER_MOD}.agentic_repair")
    @patch("retry_policy.decide", return_value={"action": "requeue", "transient_retries": 1, "backoff_s": 5})
    def test_transient_requeues(self, mock_decide, mock_ar, mock_set, mock_sleep):
        runner = _load_runner_entrypoint()
        mock_ar.repair_patch.return_value = {"state": "QUEUED", "note": "requeued"}
        result = runner._block_or_retry({"id": "t-5", "slug": "retry", "transient_retries": 0}, "rate limit")
        self.assertEqual(result, "requeue")
        self.assertLessEqual(mock_sleep.call_args[0][0], 20)


if __name__ == "__main__":
    unittest.main()
