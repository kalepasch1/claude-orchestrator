import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import task_slicer


def _sliceable_task(**over):
    prompt = "Do step one. " * 250  # > ORCH_SLICE_PROMPT_CHARS default 2400
    t = {"id": "t1", "slug": "improve-something-big", "project_id": "p1",
         "state": "QUEUED", "kind": "build", "prompt": prompt, "note": "",
         "base_branch": "master"}
    t.update(over)
    return t


class AiSliceTaskTest(unittest.TestCase):

    def _task(self):
        return _sliceable_task()

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "false"}):
            self.assertIsNone(task_slicer.ai_slice_task(self._task()))

    def test_returns_none_when_claude_cli_missing(self):
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.dict(sys.modules, {"claude_cli": None}):
                result = task_slicer.ai_slice_task(self._task())
        self.assertIsNone(result)

    def test_parses_valid_json_response(self):
        fake_claude = MagicMock()
        payload = json.dumps([
            {"title": "setup", "prompt": "Set up environment."},
            {"title": "implement", "prompt": "Write the implementation."},
            {"title": "test", "prompt": "Run the tests."},
        ])
        fake_claude.run.return_value = {"text": payload}
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                parts = task_slicer.ai_slice_task(self._task())
        self.assertIsNotNone(parts)
        self.assertGreaterEqual(len(parts), 2)
        self.assertTrue(parts[0]["slug"].endswith("-slice-1"))
        self.assertEqual(parts[0]["deps"], [])
        self.assertEqual(parts[1]["deps"], [parts[0]["slug"]])

    def test_sequential_deps_chain(self):
        fake_claude = MagicMock()
        payload = json.dumps([
            {"title": "a", "prompt": "Step A."},
            {"title": "b", "prompt": "Step B."},
            {"title": "c", "prompt": "Step C."},
        ])
        fake_claude.run.return_value = {"text": payload}
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                parts = task_slicer.ai_slice_task(self._task())
        self.assertEqual(parts[2]["deps"], [parts[1]["slug"]])

    def test_returns_none_on_empty_response(self):
        fake_claude = MagicMock()
        fake_claude.run.return_value = {"text": ""}
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                result = task_slicer.ai_slice_task(self._task())
        self.assertIsNone(result)

    def test_returns_none_on_bad_json(self):
        fake_claude = MagicMock()
        fake_claude.run.return_value = {"text": "Here is the plan: step1, step2"}
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                result = task_slicer.ai_slice_task(self._task())
        self.assertIsNone(result)

    def test_returns_none_when_claude_raises(self):
        fake_claude = MagicMock()
        fake_claude.run.side_effect = RuntimeError("circuit open")
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                result = task_slicer.ai_slice_task(self._task())
        self.assertIsNone(result)

    def test_returns_none_for_single_item_response(self):
        fake_claude = MagicMock()
        payload = json.dumps([{"title": "only-one", "prompt": "Just one step."}])
        fake_claude.run.return_value = {"text": payload}
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                result = task_slicer.ai_slice_task(self._task())
        self.assertIsNone(result)

    def test_model_from_env_var(self):
        """AI_SLICE_MODEL can be overridden — no hardcoded keys."""
        fake_claude = MagicMock()
        payload = json.dumps([
            {"title": "a", "prompt": "Step A."},
            {"title": "b", "prompt": "Step B."},
        ])
        fake_claude.run.return_value = {"text": payload}
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}), \
             patch.object(task_slicer, "AI_SLICE_MODEL", "test-model"), \
             patch.dict(sys.modules, {"claude_cli": fake_claude}):
            task_slicer.ai_slice_task(self._task())
        call_args = fake_claude.run.call_args[0]
        self.assertIn("test-model", call_args)


class PreAgentHookAiIntegrationTest(unittest.TestCase):

    def test_uses_ai_when_enabled(self):
        fake_db = MagicMock()
        fake_db.select.return_value = []
        payload = json.dumps([
            {"title": "part-a", "prompt": "Do part A."},
            {"title": "part-b", "prompt": "Do part B."},
        ])
        fake_claude = MagicMock()
        fake_claude.run.return_value = {"text": payload}
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.object(task_slicer, "db", fake_db):
                with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                    out = task_slicer.pre_agent_hook(_sliceable_task())
        self.assertTrue(out)
        fake_claude.run.assert_called_once()

    def test_falls_back_to_heuristic_when_ai_fails(self):
        fake_db = MagicMock()
        fake_db.select.return_value = []
        fake_claude = MagicMock()
        fake_claude.run.side_effect = RuntimeError("api down")
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.object(task_slicer, "db", fake_db):
                with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                    out = task_slicer.pre_agent_hook(_sliceable_task())
        self.assertTrue(out)
        fake_db.insert.assert_called()

    def test_non_sliceable_never_calls_claude(self):
        fake_claude = MagicMock()
        fake_db = MagicMock()
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.object(task_slicer, "db", fake_db):
                with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                    out = task_slicer.pre_agent_hook(_sliceable_task(prompt="short"))
        self.assertFalse(out)
        fake_claude.run.assert_not_called()

    def test_protected_prefix_skipped(self):
        fake_db = MagicMock()
        fake_claude = MagicMock()
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.object(task_slicer, "db", fake_db):
                with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                    out = task_slicer.pre_agent_hook(
                        _sliceable_task(slug="qafix-something-important")
                    )
        self.assertFalse(out)
        fake_claude.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
