import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import task_slicer


class ShouldSliceTest(unittest.TestCase):

    def test_short_prompt_not_sliced(self):
        task = {"slug": "my-task", "prompt": "Do a small thing.", "note": ""}
        self.assertFalse(task_slicer.should_slice(task))

    def test_long_prompt_triggers_slice(self):
        task = {"slug": "my-task", "prompt": "x" * (task_slicer.THRESHOLD + 1), "note": ""}
        self.assertTrue(task_slicer.should_slice(task))

    def test_many_bullets_triggers_slice(self):
        lines = ("\n- item" * 7)
        task = {"slug": "my-task", "prompt": lines, "note": ""}
        self.assertTrue(task_slicer.should_slice(task))

    def test_many_ands_triggers_slice(self):
        prompt = " and ".join(["step"] * 9)
        task = {"slug": "my-task", "prompt": prompt, "note": ""}
        self.assertTrue(task_slicer.should_slice(task))

    def test_already_sliced_not_resliced(self):
        task = {"slug": "my-task", "prompt": "x" * (task_slicer.THRESHOLD + 1),
                "note": task_slicer.MARK}
        self.assertFalse(task_slicer.should_slice(task))

    def test_protected_prefix_not_sliced(self):
        for prefix in task_slicer.PROTECTED_PREFIXES:
            task = {"slug": f"{prefix}something", "prompt": "x" * (task_slicer.THRESHOLD + 1),
                    "note": ""}
            self.assertFalse(
                task_slicer.should_slice(task),
                f"prefix {prefix!r} should be protected from slicing",
            )

    def test_disabled_via_env_false(self):
        task = {"slug": "my-task", "prompt": "x" * (task_slicer.THRESHOLD + 1), "note": ""}
        with patch.dict(os.environ, {"ORCH_AUTO_SLICE": "false"}):
            self.assertFalse(task_slicer.should_slice(task))

    def test_disabled_via_env_zero(self):
        task = {"slug": "my-task", "prompt": "x" * (task_slicer.THRESHOLD + 1), "note": ""}
        with patch.dict(os.environ, {"ORCH_AUTO_SLICE": "0"}):
            self.assertFalse(task_slicer.should_slice(task))

    def test_already_at_max_depth_not_resliced(self):
        # A slug that already contains MAX_DEPTH occurrences of "-slice-" should be protected.
        depth_slug = "my-task" + "-slice-1" * task_slicer.MAX_DEPTH
        task = {"slug": depth_slug, "prompt": "x" * (task_slicer.THRESHOLD + 1), "note": ""}
        self.assertFalse(task_slicer.should_slice(task))

    def test_non_dict_task_not_sliced(self):
        self.assertFalse(task_slicer.should_slice(None))
        self.assertFalse(task_slicer.should_slice("not a dict"))


class SliceTaskTest(unittest.TestCase):

    def test_returns_empty_for_single_sentence(self):
        task = {"slug": "my-task", "prompt": "Just one sentence with no natural splits."}
        self.assertEqual(task_slicer.slice_task(task), [])

    def test_produces_sequential_dep_chain(self):
        bullets = "\n".join(f"- Step {i}: perform important work" for i in range(8))
        task = {"slug": "parent-task", "prompt": bullets}
        parts = task_slicer.slice_task(task)
        self.assertGreater(len(parts), 1)
        for part in parts[1:]:
            self.assertTrue(
                len(part["deps"]) > 0,
                f"part {part['slug']!r} must have a dep on the previous part",
            )

    def test_first_part_has_no_deps(self):
        bullets = "\n".join(f"- step {i}" for i in range(8))
        task = {"slug": "parent-task", "prompt": bullets}
        parts = task_slicer.slice_task(task)
        self.assertEqual(parts[0]["deps"], [])

    def test_slugs_contain_parent_base(self):
        bullets = "\n".join(f"- item {i}" for i in range(8))
        task = {"slug": "parent-task", "prompt": bullets}
        parts = task_slicer.slice_task(task)
        for part in parts:
            self.assertIn("parent-task", part["slug"])

    def test_max_parts_respected(self):
        bullets = "\n".join(f"- item {i}" for i in range(30))
        task = {"slug": "big-task", "prompt": bullets}
        parts = task_slicer.slice_task(task)
        self.assertLessEqual(len(parts), task_slicer.MAX_PARTS)

    def test_parts_cover_all_content(self):
        steps = [f"step-{i}" for i in range(6)]
        bullets = "\n- ".join([""] + steps).lstrip("\n")
        task = {"slug": "cover-task", "prompt": bullets}
        parts = task_slicer.slice_task(task)
        combined = " ".join(p["prompt"] for p in parts)
        for step in steps:
            self.assertIn(step, combined, f"{step!r} was lost during slicing")


class PreAgentHookTest(unittest.TestCase):

    def _make_large_task(self):
        bullets = "\n".join(f"- Step {i}: do important work for component X" for i in range(8))
        return {
            "id": "task-123",
            "slug": "big-parent",
            "project_id": "proj-1",
            "kind": "build",
            "prompt": bullets,
            "base_branch": "main",
            "note": "",
        }

    def test_hook_returns_false_for_small_task(self):
        mock_db = MagicMock()
        old_db = task_slicer.db
        try:
            task_slicer.db = mock_db
            result = task_slicer.pre_agent_hook({"slug": "small", "prompt": "tiny", "note": ""})
        finally:
            task_slicer.db = old_db
        self.assertFalse(result)
        mock_db.insert.assert_not_called()

    def test_hook_inserts_subtasks_and_marks_parent_decomposed(self):
        mock_db = MagicMock()
        mock_db.insert.return_value = {"id": "new-subtask"}
        old_db = task_slicer.db
        try:
            task_slicer.db = mock_db
            result = task_slicer.pre_agent_hook(self._make_large_task())
        finally:
            task_slicer.db = old_db

        self.assertTrue(result)
        self.assertGreaterEqual(mock_db.insert.call_count, 2, "at least 2 sub-tasks should be inserted")
        decomposed_calls = [
            c for c in mock_db.update.call_args_list
            if c.args[2].get("state") == "DECOMPOSED"
        ]
        self.assertTrue(decomposed_calls, "parent task must be marked DECOMPOSED")

    def test_hook_returns_false_for_non_dict(self):
        self.assertFalse(task_slicer.pre_agent_hook(None))
        self.assertFalse(task_slicer.pre_agent_hook("not a dict"))

    def test_hook_includes_parent_slug_in_subtask_prompts(self):
        mock_db = MagicMock()
        mock_db.insert.return_value = {"id": "sub"}
        old_db = task_slicer.db
        inserted_rows = []
        mock_db.insert.side_effect = lambda table, row: inserted_rows.append(row) or {"id": "sub"}
        try:
            task_slicer.db = mock_db
            task_slicer.pre_agent_hook(self._make_large_task())
        finally:
            task_slicer.db = old_db

        for row in inserted_rows:
            self.assertIn("big-parent", row.get("prompt", ""),
                          "sub-task prompt should reference the parent slug")

    def test_hook_db_failure_returns_false(self):
        mock_db = MagicMock()
        mock_db.insert.side_effect = RuntimeError("DB down")
        old_db = task_slicer.db
        try:
            task_slicer.db = mock_db
            result = task_slicer.pre_agent_hook(self._make_large_task())
        finally:
            task_slicer.db = old_db
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
