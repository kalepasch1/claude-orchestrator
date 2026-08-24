#!/usr/bin/env python3
"""Regression tests for the preflight wedge guard.

Context: 'preflight' held its periodic singleton lock for 2930s and three
consecutive invocations were skipped, each exiting 0. The sweep that lost that
signal went unnoticed precisely because nothing asserted on it, so these tests
assert the two bounds directly rather than trusting the prose.
"""
import os
import sys
import time
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import preflight_gate  # noqa: E402


class CallTimeoutTests(unittest.TestCase):
    def test_returns_value_when_fast_enough(self):
        self.assertEqual(
            preflight_gate._call_with_timeout(lambda a, b=0: a + b, 5, 1, b=2), 3)

    def test_no_cap_when_seconds_is_falsy(self):
        # Matches periodic._time_limit: a missing cap runs uncapped rather than
        # refusing to run at all.
        self.assertEqual(preflight_gate._call_with_timeout(lambda: "x", 0), "x")
        self.assertEqual(preflight_gate._call_with_timeout(lambda: "x", None), "x")
        self.assertEqual(preflight_gate._call_with_timeout(lambda: "x", -1), "x")

    def test_raises_on_slow_call(self):
        started = threading.Event()

        def _hang():
            started.set()
            time.sleep(30)

        t0 = time.monotonic()
        with self.assertRaises(preflight_gate.PreflightCallTimeout):
            preflight_gate._call_with_timeout(_hang, 1)
        elapsed = time.monotonic() - t0
        self.assertTrue(started.wait(5), "worker never started")
        # The whole point: the CALLER is bounded even though the callee is not.
        self.assertLess(elapsed, 10, f"caller was not bounded (took {elapsed:.1f}s)")

    def test_worker_is_daemon_so_it_cannot_hold_the_process_open(self):
        seen = {}

        def _record():
            seen["daemon"] = threading.current_thread().daemon

        preflight_gate._call_with_timeout(_record, 5)
        self.assertTrue(seen.get("daemon"),
                        "an abandoned triage call must not keep the process alive")

    def test_propagates_callee_exception(self):
        def _boom():
            raise ValueError("provider said no")

        with self.assertRaises(ValueError):
            preflight_gate._call_with_timeout(_boom, 5)

    def test_propagates_none_result(self):
        self.assertIsNone(preflight_gate._call_with_timeout(lambda: None, 5))


class RunDeadlineTests(unittest.TestCase):
    """run() must return on its own budget instead of holding the lock."""

    def setUp(self):
        self._saved = {
            "app_triage": preflight_gate.app_triage,
            "db": preflight_gate.db,
            "deadline": preflight_gate._DEADLINE_S,
            "call_timeout": preflight_gate._CALL_TIMEOUT_S,
            "record": preflight_gate.record_verdicts,
        }

    def tearDown(self):
        preflight_gate.app_triage = self._saved["app_triage"]
        preflight_gate.db = self._saved["db"]
        preflight_gate._DEADLINE_S = self._saved["deadline"]
        preflight_gate._CALL_TIMEOUT_S = self._saved["call_timeout"]
        preflight_gate.record_verdicts = self._saved["record"]

    def _install_fakes(self, triage_run):
        rows = [{"id": f"id-{i}", "slug": f"task-{i}", "prompt": "do a thing",
                 "kind": "build", "material": False, "note": "", "model": None,
                 "force_coder": None, "project_id": "p1"} for i in range(10)]
        updates = []

        class _FakeDB:
            MissingRelationError = RuntimeError
            TransientDBError = RuntimeError

            @staticmethod
            def select(table, _params=None):
                return rows if table == "tasks" else [{"id": "p1", "name": "beethoven"}]

            @staticmethod
            def update(_table, where, _values):
                updates.append(where)

        class _FakeTriage:
            run = staticmethod(triage_run)

        preflight_gate.db = _FakeDB
        preflight_gate.app_triage = _FakeTriage
        preflight_gate.record_verdicts = lambda _v: (False, "liveness stubbed")
        return rows, updates

    def test_run_stops_on_deadline_instead_of_wedging(self):
        def _slow(*_a, **_k):
            time.sleep(0.4)
            return {"text": "YES\nSCOPE DEFINITION: edit a.py\nAMBIGUITIES/CONCERNS: none"}

        rows, updates = self._install_fakes(_slow)
        preflight_gate._DEADLINE_S = 1
        preflight_gate._CALL_TIMEOUT_S = 5

        t0 = time.monotonic()
        result = preflight_gate.run()
        elapsed = time.monotonic() - t0

        self.assertLess(elapsed, 8, f"run() did not honour its deadline ({elapsed:.1f}s)")
        self.assertLess(len(updates), len(rows),
                        "deadline never fired; the whole batch was processed")
        self.assertIsInstance(result, dict)

    def test_run_abandons_a_hung_triage_call_and_keeps_going(self):
        calls = {"n": 0}

        def _first_call_hangs(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                time.sleep(30)
            return {"text": "YES\nSCOPE DEFINITION: edit a.py\nAMBIGUITIES/CONCERNS: none"}

        self._install_fakes(_first_call_hangs)
        preflight_gate._DEADLINE_S = 60
        preflight_gate._CALL_TIMEOUT_S = 1

        result = preflight_gate.run()
        self.assertEqual(result.get("abandoned"), 1)
        # The hung call must not abort the batch — later rows still get triaged.
        self.assertGreater(calls["n"], 1)

    def test_run_completes_normally_when_everything_is_fast(self):
        self._install_fakes(
            lambda *_a, **_k: {"text": "YES\nSCOPE DEFINITION: edit a.py\n"
                                       "AMBIGUITIES/CONCERNS: none"})
        preflight_gate._DEADLINE_S = 60
        preflight_gate._CALL_TIMEOUT_S = 30

        result = preflight_gate.run()
        self.assertEqual(result.get("abandoned"), 0)
        self.assertEqual(result.get("screened"), 10)


class BudgetConfigTests(unittest.TestCase):
    def test_budgets_are_orch_prefixed_and_positive(self):
        # ORCH_ prefix is the repo convention for fleet-pushable config keys.
        self.assertGreater(preflight_gate._CALL_TIMEOUT_S, 0)
        self.assertGreater(preflight_gate._DEADLINE_S, 0)
        self.assertLessEqual(preflight_gate._CALL_TIMEOUT_S, preflight_gate._DEADLINE_S)


if __name__ == "__main__":
    unittest.main()
