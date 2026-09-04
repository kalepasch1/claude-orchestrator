#!/usr/bin/env python3
"""Regression tests for runner/task_state_machine.py.

Four defects are pinned here, all of them the kind that only show up at 3am:

1. Importing the module raised ValueError when ORCH_MAX_AUTO_RETRIES held garbage,
   taking down every importer of the module that is supposed to keep the runner moving.
2. The retry ceiling was frozen at import, so a fleet_control push of the key did
   nothing until every runner restarted.
3. QUARANTINED and SUPERSEDED were unreachable targets, so the state machine rejected
   transitions the executors perform nightly — and callers routed around it with force=True.
4. `auto_requeue_on_transient(task_id, None)` died on `None.lower()`, and the EAGAIN /
   ECONNRESET patterns were spelled uppercase while matched against a lowercased string,
   so those two could never fire.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import types
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

# A stub `db` so importing the state machine never needs a live database.
if "db" not in sys.modules:  # pragma: no cover - depends on test ordering
    _stub = types.ModuleType("db")
    _stub.select = lambda table, params=None: []
    _stub.update = lambda table, patch, **kw: None
    sys.modules["db"] = _stub

import task_state_machine as tsm  # noqa: E402


class FakeDB:
    """Minimal db seam: one task row, recording every update."""

    def __init__(self, row=None, select_raises=False):
        self.row = row
        self.select_raises = select_raises
        self.updates = []

    def select(self, table, params=None):
        if self.select_raises:
            raise RuntimeError("postgrest unreachable")
        return [self.row] if self.row else []

    def update(self, table, match, patch):
        # Mirrors db.update(table, match, patch) exactly. The recorded tuple
        # keeps the patch first so a drifting signature fails here, at the
        # seam, rather than silently in every assertion below.
        self.updates.append((patch, match))
        return patch


class StateMachineTestCase(unittest.TestCase):
    def setUp(self):
        self._saved_db = tsm.db
        self._saved_env = os.environ.get("ORCH_MAX_AUTO_RETRIES")
        os.environ.pop("ORCH_MAX_AUTO_RETRIES", None)

    def tearDown(self):
        tsm.db = self._saved_db
        if self._saved_env is None:
            os.environ.pop("ORCH_MAX_AUTO_RETRIES", None)
        else:
            os.environ["ORCH_MAX_AUTO_RETRIES"] = self._saved_env

    def _install(self, **kwargs):
        fake = FakeDB(**kwargs)
        tsm.db = fake
        return fake


class ReachableStatesTest(StateMachineTestCase):
    def test_running_can_be_quarantined(self):
        self.assertTrue(tsm.is_valid_transition("RUNNING", "QUARANTINED"))

    def test_running_can_be_superseded(self):
        self.assertTrue(tsm.is_valid_transition("RUNNING", "SUPERSEDED"))

    def test_queued_can_be_quarantined(self):
        self.assertTrue(tsm.is_valid_transition("QUEUED", "QUARANTINED"))

    def test_superseded_is_terminal(self):
        self.assertEqual(tsm.VALID_TRANSITIONS["SUPERSEDED"], set())

    def test_every_target_state_is_also_a_source_key(self):
        """No state may be reachable-but-undefined; that is how tasks get stuck."""
        targets = set()
        for allowed in tsm.VALID_TRANSITIONS.values():
            targets |= allowed
        self.assertEqual(targets - set(tsm.VALID_TRANSITIONS), set())

    def test_previously_valid_transitions_still_hold(self):
        for src, dst in (("QUEUED", "RUNNING"), ("RUNNING", "DONE"), ("DONE", "MERGED"),
                         ("BLOCKED", "QUEUED"), ("TESTFAIL", "SHELVED"),
                         ("QUARANTINED", "QUEUED")):
            self.assertTrue(tsm.is_valid_transition(src, dst), f"{src} -> {dst}")

    def test_invalid_transitions_are_still_rejected(self):
        for src, dst in (("MERGED", "QUEUED"), ("SUPERSEDED", "RUNNING"),
                         ("QUEUED", "DONE"), ("DONE", "RUNNING")):
            self.assertFalse(tsm.is_valid_transition(src, dst), f"{src} -> {dst}")

    def test_is_valid_transition_never_raises(self):
        for src, dst in ((None, None), (1, 2), ([], {}), ("QUEUED", None)):
            self.assertFalse(tsm.is_valid_transition(src, dst))


class RetryCeilingTest(StateMachineTestCase):
    def test_import_survives_a_garbage_env_value(self):
        env = dict(os.environ, ORCH_MAX_AUTO_RETRIES="not-a-number")
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r);"
             "import types; m=types.ModuleType('db');"
             "m.select=lambda *a, **k: []; m.update=lambda *a, **k: None;"
             "sys.modules['db']=m;"
             "import task_state_machine as t; print(t.MAX_AUTO_RETRIES)" % RUNNER_DIR],
            env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(tsm.DEFAULT_MAX_AUTO_RETRIES))

    def test_a_pushed_value_takes_effect_without_a_restart(self):
        os.environ["ORCH_MAX_AUTO_RETRIES"] = "7"
        self.assertEqual(tsm._max_auto_retries(), 7)
        os.environ["ORCH_MAX_AUTO_RETRIES"] = "1"
        self.assertEqual(tsm._max_auto_retries(), 1)

    def test_garbage_and_negative_values_fall_back(self):
        for bad in ("abc", "-1", "  ", ""):
            os.environ["ORCH_MAX_AUTO_RETRIES"] = bad
            self.assertEqual(tsm._max_auto_retries(), tsm.MAX_AUTO_RETRIES, bad)

    def test_absent_value_uses_the_module_constant(self):
        os.environ.pop("ORCH_MAX_AUTO_RETRIES", None)
        self.assertEqual(tsm._max_auto_retries(), tsm.MAX_AUTO_RETRIES)


class FailSoftDatabaseTest(StateMachineTestCase):
    def test_transition_reports_failure_when_the_db_is_down(self):
        self._install(select_raises=True)
        ok, msg = tsm.transition("t1", "DONE")
        self.assertFalse(ok)
        self.assertIn("not found", msg)

    def test_history_returns_empty_when_the_db_is_down(self):
        self._install(select_raises=True)
        self.assertEqual(tsm.get_transition_history("t1"), [])

    def test_auto_requeue_reports_missing_task_when_the_db_is_down(self):
        self._install(select_raises=True)
        self.assertEqual(tsm.auto_requeue_on_transient("t1", "timeout"), "task not found")


class AutoRequeueTest(StateMachineTestCase):
    ROW = {"id": "t1", "slug": "demo", "state": "RUNNING", "note": ""}

    def test_none_error_message_does_not_explode(self):
        fake = self._install(row=dict(self.ROW))
        self.assertEqual(tsm.auto_requeue_on_transient("t1", None), "blocked (non-transient)")
        self.assertEqual(fake.updates[0][0]["state"], "BLOCKED")

    def test_econnreset_is_recognised_as_transient(self):
        fake = self._install(row=dict(self.ROW))
        result = tsm.auto_requeue_on_transient("t1", "ECONNRESET while pushing")
        self.assertTrue(result.startswith("requeued"), result)
        self.assertEqual(fake.updates[0][0]["state"], "QUEUED")

    def test_eagain_is_recognised_as_transient(self):
        fake = self._install(row=dict(self.ROW))
        self.assertTrue(tsm.auto_requeue_on_transient("t1", "EAGAIN").startswith("requeued"))
        self.assertEqual(fake.updates[0][0]["state"], "QUEUED")

    def test_timeout_is_still_transient(self):
        self._install(row=dict(self.ROW))
        self.assertTrue(tsm.auto_requeue_on_transient("t1", "Timeout").startswith("requeued"))

    def test_exhausted_retries_block(self):
        row = dict(self.ROW, note="auto-requeue | auto-requeue | auto-requeue")
        fake = self._install(row=row)
        result = tsm.auto_requeue_on_transient("t1", "timeout")
        self.assertIn("retries exhausted", result)
        self.assertEqual(fake.updates[0][0]["state"], "BLOCKED")

    def test_pushed_ceiling_changes_the_blocking_point(self):
        row = dict(self.ROW, note="auto-requeue")
        self._install(row=row)
        os.environ["ORCH_MAX_AUTO_RETRIES"] = "5"
        self.assertTrue(tsm.auto_requeue_on_transient("t1", "timeout").startswith("requeued"))
        os.environ["ORCH_MAX_AUTO_RETRIES"] = "1"
        self.assertIn("retries exhausted", tsm.auto_requeue_on_transient("t1", "timeout"))


class TransitionBehaviourTest(StateMachineTestCase):
    def test_valid_transition_writes_the_new_state(self):
        fake = self._install(row={"id": "t1", "slug": "demo", "state": "RUNNING", "note": ""})
        ok, msg = tsm.transition("t1", "DONE")
        self.assertTrue(ok, msg)
        self.assertEqual(fake.updates[0][0]["state"], "DONE")

    def test_invalid_transition_writes_nothing(self):
        fake = self._install(row={"id": "t1", "slug": "demo", "state": "MERGED", "note": ""})
        ok, msg = tsm.transition("t1", "RUNNING")
        self.assertFalse(ok)
        self.assertEqual(fake.updates, [])
        self.assertIn("invalid transition", msg)

    def test_force_bypasses_validation(self):
        fake = self._install(row={"id": "t1", "slug": "demo", "state": "MERGED", "note": ""})
        ok, _ = tsm.transition("t1", "RUNNING", force=True)
        self.assertTrue(ok)
        self.assertEqual(fake.updates[0][0]["state"], "RUNNING")

    def test_note_suffix_is_appended_not_replaced(self):
        fake = self._install(row={"id": "t1", "slug": "d", "state": "RUNNING", "note": "old"})
        tsm.transition("t1", "DONE", note_suffix="new")
        self.assertEqual(fake.updates[0][0]["note"], "old | new")


if __name__ == "__main__":
    unittest.main()
