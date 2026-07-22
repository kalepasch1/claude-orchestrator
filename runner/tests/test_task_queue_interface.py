import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import task_queue_interface


def _make_supabase_queue(mock_db):
    """Create a SupabaseTaskQueue without importing the real db module."""
    q = object.__new__(task_queue_interface.SupabaseTaskQueue)
    q._db = mock_db
    return q


class SupabaseTaskQueueTest(unittest.TestCase):

    def setUp(self):
        task_queue_interface.reset_queue()
        self.mock_db = MagicMock()

    def tearDown(self):
        task_queue_interface.reset_queue()

    def test_enqueue_inserts_into_tasks_table(self):
        self.mock_db.insert.return_value = {"id": "t1"}
        q = _make_supabase_queue(self.mock_db)
        result = q.enqueue({"slug": "my-task", "state": "QUEUED"})
        self.mock_db.insert.assert_called_once_with("tasks", {"slug": "my-task", "state": "QUEUED"})
        self.assertEqual(result, {"id": "t1"})

    def test_enqueue_returns_empty_dict_when_db_returns_none(self):
        self.mock_db.insert.return_value = None
        q = _make_supabase_queue(self.mock_db)
        result = q.enqueue({"slug": "x"})
        self.assertEqual(result, {})

    def test_dequeue_calls_claim_task(self):
        self.mock_db.claim_task.return_value = {"id": "t1", "slug": "my-task"}
        q = _make_supabase_queue(self.mock_db)
        result = q.dequeue("runner-1")
        self.mock_db.claim_task.assert_called_once_with("runner-1")
        self.assertEqual(result["slug"], "my-task")

    def test_dequeue_returns_none_when_queue_empty(self):
        self.mock_db.claim_task.return_value = None
        q = _make_supabase_queue(self.mock_db)
        result = q.dequeue("runner-1")
        self.assertIsNone(result)

    def test_update_status_patches_state_and_note(self):
        q = _make_supabase_queue(self.mock_db)
        ok = q.update_status("t1", "DONE", note="finished")
        self.assertTrue(ok)
        call_args = self.mock_db.update.call_args
        self.assertEqual(call_args.args[0], "tasks")
        self.assertEqual(call_args.args[1], {"id": "t1"})
        self.assertEqual(call_args.args[2]["state"], "DONE")
        self.assertEqual(call_args.args[2]["note"], "finished")

    def test_update_status_omits_note_when_empty(self):
        q = _make_supabase_queue(self.mock_db)
        q.update_status("t1", "DONE")
        patch = self.mock_db.update.call_args.args[2]
        self.assertNotIn("note", patch)

    def test_update_status_returns_false_on_db_error(self):
        self.mock_db.update.side_effect = RuntimeError("DB down")
        q = _make_supabase_queue(self.mock_db)
        ok = q.update_status("t1", "DONE")
        self.assertFalse(ok)

    def test_get_status_returns_state_string(self):
        self.mock_db.select.return_value = [{"state": "RUNNING"}]
        q = _make_supabase_queue(self.mock_db)
        self.assertEqual(q.get_status("t1"), "RUNNING")

    def test_get_status_returns_none_for_unknown_id(self):
        self.mock_db.select.return_value = []
        q = _make_supabase_queue(self.mock_db)
        self.assertIsNone(q.get_status("unknown-id"))

    def test_get_status_returns_none_when_db_returns_none(self):
        self.mock_db.select.return_value = None
        q = _make_supabase_queue(self.mock_db)
        self.assertIsNone(q.get_status("t1"))

    def test_update_status_includes_updated_at(self):
        q = _make_supabase_queue(self.mock_db)
        q.update_status("t1", "DONE")
        patch = self.mock_db.update.call_args.args[2]
        self.assertIn("updated_at", patch)


class GetQueueFactoryTest(unittest.TestCase):

    def setUp(self):
        task_queue_interface.reset_queue()

    def tearDown(self):
        task_queue_interface.reset_queue()

    def test_default_backend_is_supabase(self):
        mock_db = MagicMock()
        env = {k: v for k, v in os.environ.items() if k != "ORCH_QUEUE_BACKEND"}
        with patch.dict(os.environ, env, clear=True), \
             patch.dict(sys.modules, {"db": mock_db}):
            q = task_queue_interface.get_queue()
        self.assertIsInstance(q, task_queue_interface.SupabaseTaskQueue)

    def test_explicit_supabase_backend(self):
        mock_db = MagicMock()
        with patch.dict(os.environ, {"ORCH_QUEUE_BACKEND": "supabase"}), \
             patch.dict(sys.modules, {"db": mock_db}):
            task_queue_interface.reset_queue()
            q = task_queue_interface.get_queue()
        self.assertIsInstance(q, task_queue_interface.SupabaseTaskQueue)

    def test_unknown_backend_raises_value_error(self):
        with patch.dict(os.environ, {"ORCH_QUEUE_BACKEND": "badbackend"}):
            task_queue_interface.reset_queue()
            with self.assertRaises(ValueError) as ctx:
                task_queue_interface.get_queue()
        self.assertIn("badbackend", str(ctx.exception))

    def test_get_queue_returns_singleton(self):
        mock_db = MagicMock()
        with patch.dict(sys.modules, {"db": mock_db}):
            task_queue_interface.reset_queue()
            q1 = task_queue_interface.get_queue()
            q2 = task_queue_interface.get_queue()
        self.assertIs(q1, q2)

    def test_reset_queue_clears_singleton(self):
        mock_db = MagicMock()
        with patch.dict(sys.modules, {"db": mock_db}):
            q1 = task_queue_interface.get_queue()
            task_queue_interface.reset_queue()
            q2 = task_queue_interface.get_queue()
        self.assertIsNot(q1, q2)


class TaskQueueInterfaceAbstractTest(unittest.TestCase):

    def test_cannot_instantiate_abstract_class(self):
        with self.assertRaises(TypeError):
            task_queue_interface.TaskQueueInterface()

    def test_supabase_queue_is_concrete(self):
        mock_db = MagicMock()
        q = _make_supabase_queue(mock_db)
        self.assertIsInstance(q, task_queue_interface.TaskQueueInterface)


if __name__ == "__main__":
    unittest.main()
