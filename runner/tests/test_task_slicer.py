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


class TaskSlicerIdempotencyTest(unittest.TestCase):
    """Regression: pre_agent_hook used to flip the parent to DECOMPOSED only AFTER the
    slice inserts, so a failed flip left a QUEUED parent that re-inserted the same slice
    slugs on every re-claim (sentinel-dedupe storm of 2026-07-09/10)."""

    def test_parent_flipped_before_inserts(self):
        fake_db = MagicMock()
        fake_db.select.return_value = []  # no pre-existing slices
        calls = []
        fake_db.update.side_effect = lambda *a, **k: calls.append("update")
        fake_db.insert.side_effect = lambda *a, **k: calls.append("insert")
        with patch.object(task_slicer, "db", fake_db):
            out = task_slicer.pre_agent_hook(_sliceable_task())
        self.assertTrue(out)
        self.assertTrue(calls, "expected db calls")
        self.assertEqual(calls[0], "update", "parent must flip to DECOMPOSED before inserts")
        self.assertIn("insert", calls)
        first_update = fake_db.update.call_args_list[0].args[2]
        self.assertEqual(first_update["state"], "DECOMPOSED")

    def test_existing_slices_are_not_reinserted(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [{"id": "existing"}]  # slices already present
        with patch.object(task_slicer, "db", fake_db):
            out = task_slicer.pre_agent_hook(_sliceable_task())
        self.assertTrue(out)
        fake_db.insert.assert_not_called()
        patch_row = fake_db.update.call_args.args[2]
        self.assertEqual(patch_row["state"], "DECOMPOSED")

    def test_failed_flip_aborts_without_inserts(self):
        fake_db = MagicMock()
        fake_db.select.return_value = []
        fake_db.update.side_effect = RuntimeError("db down")
        with patch.object(task_slicer, "db", fake_db):
            out = task_slicer.pre_agent_hook(_sliceable_task())
        self.assertFalse(out)
        fake_db.insert.assert_not_called()

    def test_all_inserts_failing_restores_parent(self):
        fake_db = MagicMock()
        fake_db.select.return_value = []
        fake_db.insert.side_effect = RuntimeError("insert failed")
        with patch.object(task_slicer, "db", fake_db):
            out = task_slicer.pre_agent_hook(_sliceable_task())
        self.assertFalse(out)
        last_update = fake_db.update.call_args_list[-1].args[2]
        self.assertEqual(last_update["state"], "QUEUED")

    def test_non_sliceable_untouched(self):
        fake_db = MagicMock()
        with patch.object(task_slicer, "db", fake_db):
            out = task_slicer.pre_agent_hook(_sliceable_task(prompt="short"))
        self.assertFalse(out)
        fake_db.insert.assert_not_called()
        fake_db.update.assert_not_called()


class AiSliceTaskTest(unittest.TestCase):
    """Unit tests for ai_slice_task — verifies parse/fallback logic without live Claude calls."""

    def _task(self):
        return {"id": "t2", "slug": "improve-big-feature", "project_id": "p1",
                "prompt": "Do A and B and C. " * 300}

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

    def test_pre_agent_hook_uses_ai_when_enabled(self):
        fake_db = MagicMock()
        fake_db.select.return_value = []
        fake_db.update.return_value = None
        fake_db.insert.return_value = None
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

    def test_pre_agent_hook_falls_back_to_heuristic_when_ai_fails(self):
        fake_db = MagicMock()
        fake_db.select.return_value = []
        fake_claude = MagicMock()
        fake_claude.run.side_effect = RuntimeError("api down")
        with patch.dict(os.environ, {"ORCH_AI_SLICE": "true"}):
            with patch.object(task_slicer, "db", fake_db):
                with patch.dict(sys.modules, {"claude_cli": fake_claude}):
                    out = task_slicer.pre_agent_hook(_sliceable_task())
        self.assertTrue(out)
        fake_db.insert.assert_called()  # heuristic slices inserted


if __name__ == "__main__":
    unittest.main()
