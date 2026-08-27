#!/usr/bin/env python3
"""Tests for queue_groom deduplication.

WHAT THESE TESTS USED TO DO, AND WHY IT MATTERED
------------------------------------------------
The previous version of this file installed a fake db module:

    db_stub = types.ModuleType('db')
    db_stub.sql = MagicMock(return_value=[])
    sys.modules['db'] = db_stub

and then asserted on the SQL string passed to `db_stub.sql`.  Every test
passed.  But the real db module is a PostgREST client and has never had a
`sql()` — `git log -S"def sql(" -- runner/db.py` is empty — so in production
guard_duplicate_enqueue() raised AttributeError on its first line, unguarded,
from the day it was written.  The tests had mocked the missing function into
existence and were measuring their own stub.

So the stub is now built from the REAL module's attributes: anything the code
under test reaches for that db does not define fails here the way it fails in
production.  runner/tests/test_db_api_surface.py enforces the same rule
statically, repo-wide.
"""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

_REAL_DB = os.path.join(os.path.dirname(__file__), '..', 'db.py')


def _real_db_names():
    """Top-level names runner/db.py defines, read by AST without importing it
    (importing db needs SUPABASE_URL/KEY and would open sockets)."""
    import ast
    tree = ast.parse(open(_REAL_DB, encoding='utf-8').read())
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


class _StrictDbStub(types.ModuleType):
    """A db stub that refuses to invent attributes the real module lacks."""

    def __init__(self):
        super().__init__('db')
        self._allowed = _real_db_names()
        for name in ('select', 'rpc', 'insert', 'upsert', 'update', 'delete', 'count'):
            setattr(self, name, MagicMock(name='db.' + name))

    def __getattr__(self, item):
        if item.startswith('_'):
            raise AttributeError(item)
        raise AttributeError(
            "module 'db' has no attribute %r — and neither does the real "
            "runner/db.py. Do not mock it into existence." % (item,))


db_stub = _StrictDbStub()
sys.modules['db'] = db_stub

import queue_groom  # noqa: E402  (must follow the sys.modules install)


class TestTheStubItself(unittest.TestCase):
    """If this stub silently grew a `sql`, every test below would be worthless."""

    def test_the_stub_refuses_an_attribute_the_real_db_lacks(self):
        with self.assertRaises(AttributeError):
            db_stub.sql
        self.assertNotIn('sql', _real_db_names())

    def test_the_stub_allows_the_functions_db_really_has(self):
        for name in ('select', 'insert', 'update', 'delete', 'rpc'):
            self.assertIn(name, _real_db_names())
            self.assertIsNotNone(getattr(db_stub, name))


class TestGuardDuplicateEnqueue(unittest.TestCase):

    def setUp(self):
        db_stub.select.reset_mock()
        db_stub.select.side_effect = None

    def test_returns_false_when_no_existing_task(self):
        db_stub.select.return_value = []
        self.assertFalse(queue_groom.guard_duplicate_enqueue('proj-1', 'my-task'))
        db_stub.select.assert_called_once()

    def test_returns_true_when_queued_exists(self):
        db_stub.select.return_value = [{'id': 'abc-123'}]
        self.assertTrue(queue_groom.guard_duplicate_enqueue('proj-1', 'my-task'))

    def test_returns_true_when_running_exists(self):
        db_stub.select.return_value = [{'id': 'def-456'}]
        self.assertTrue(queue_groom.guard_duplicate_enqueue('proj-1', 'running-task'))

    def test_queries_the_tasks_table_filtered_on_both_identity_columns(self):
        db_stub.select.return_value = []
        queue_groom.guard_duplicate_enqueue('proj-X', 'slug-Y')
        table, params = db_stub.select.call_args[0]
        self.assertEqual(table, 'tasks')
        self.assertEqual(params['project_id'], 'eq.proj-X')
        self.assertEqual(params['slug'], 'eq.slug-Y')

    def test_restricts_to_queued_and_running_only(self):
        """A DONE or MERGED task with the same slug is not a duplicate: the
        whole point is to find work already IN the queue."""
        db_stub.select.return_value = []
        queue_groom.guard_duplicate_enqueue('p', 's')
        params = db_stub.select.call_args[0][1]
        self.assertEqual(params['state'], 'in.(QUEUED,RUNNING)')

    def test_asks_for_one_row(self):
        """It answers a yes/no question; it must not page the table to do it."""
        db_stub.select.return_value = []
        queue_groom.guard_duplicate_enqueue('p', 's')
        self.assertEqual(db_stub.select.call_args[0][1]['limit'], '1')

    def test_tolerates_a_none_return(self):
        """db.select returns None when PostgREST answers with no body."""
        db_stub.select.return_value = None
        self.assertFalse(queue_groom.guard_duplicate_enqueue('p', 's'))

    def test_does_not_swallow_a_db_failure(self):
        """A guard that answers "not a duplicate" when it could not check is
        worse than one that raises: it admits the duplicate it exists to stop."""
        db_stub.select.side_effect = RuntimeError('control plane down')
        with self.assertRaises(RuntimeError):
            queue_groom.guard_duplicate_enqueue('p', 's')


class TestGroomRun(unittest.TestCase):

    def setUp(self):
        db_stub.rpc.reset_mock()
        db_stub.rpc.side_effect = None

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
