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


if __name__ == "__main__":
    unittest.main()
