#!/usr/bin/env python3
"""Tests for queue_groom deduplication fix."""
import sys, os, types, unittest
from unittest.mock import MagicMock

# Stub db module before importing queue_groom
db_stub = types.ModuleType('db')
db_stub.rpc = MagicMock(return_value=0)
db_stub.sql = MagicMock(return_value=[])
sys.modules['db'] = db_stub

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import queue_groom


class TestGuardDuplicateEnqueue(unittest.TestCase):

    def setUp(self):
        db_stub.sql.reset_mock()

    def test_returns_false_when_no_existing_task(self):
        db_stub.sql.return_value = []
        result = queue_groom.guard_duplicate_enqueue('proj-1', 'my-task')
        self.assertFalse(result)
        db_stub.sql.assert_called_once()
        call_args = db_stub.sql.call_args
        self.assertIn('QUEUED', call_args[0][0])
        self.assertIn('RUNNING', call_args[0][0])

    def test_returns_true_when_queued_exists(self):
        db_stub.sql.return_value = [{'id': 'abc-123'}]
        result = queue_groom.guard_duplicate_enqueue('proj-1', 'my-task')
        self.assertTrue(result)

    def test_returns_true_when_running_exists(self):
        db_stub.sql.return_value = [{'id': 'def-456'}]
        result = queue_groom.guard_duplicate_enqueue('proj-1', 'running-task')
        self.assertTrue(result)

    def test_passes_correct_params(self):
        db_stub.sql.return_value = []
        queue_groom.guard_duplicate_enqueue('proj-X', 'slug-Y')
        call_args = db_stub.sql.call_args
        self.assertEqual(call_args[0][1], ['proj-X', 'slug-Y'])


class TestGroomRun(unittest.TestCase):

    def setUp(self):
        db_stub.rpc.reset_mock()

    def test_run_calls_both_rpcs(self):
        db_stub.rpc.return_value = 0
        queue_groom.run()
        calls = [c[0][0] for c in db_stub.rpc.call_args_list]
        self.assertIn('groom_task_queue', calls)
        self.assertIn('dedup_task_queue', calls)

    def test_run_handles_groom_error(self):
        db_stub.rpc.side_effect = [Exception('groom fail'), 0]
        queue_groom.run()

    def test_run_handles_dedup_error(self):
        db_stub.rpc.side_effect = [0, Exception('dedup fail')]
        queue_groom.run()


if __name__ == '__main__':
    unittest.main()
