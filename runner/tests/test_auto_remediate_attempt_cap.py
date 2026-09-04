#!/usr/bin/env python3
"""A task must not be able to recycle forever with remediation_count pinned at 0.

DIAGNOSIS
---------
`dropbox-pareto-life-goal-autonomy-stack-p5-intergenerational-mesh` was filed as "stuck
in SHELVED". It was not: by the time it was looked at it was QUEUED, at **attempt 24**,
with **remediation_count = 0** and note "agentic-repair:rework". Its proof command
(`npm --prefix packages/darwin-kernel run test`) is green — 276 pass, 0 fail — so there
was no build failure to find.

The actual defect is that the terminal ceiling counts the wrong thing. HARD_CAP reads
`remediation_count`, but `agentic_repair.repair_patch` re-queues a task without
incrementing it, so a task looping through that path never approaches the cap no matter
how many lanes it burns. Fleet-wide at the time: 49 tasks at attempt >= 6 with
remediation_count = 0, and a maximum `attempt` of 272.

`over_attempt_cap` is the backstop. It is set far above HARD_CAP on purpose — a task
whose remediation_count is maintained correctly must always hit HARD_CAP first and never
reach this at all.
"""
from __future__ import annotations

import os
import sys
import types
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

if "db" not in sys.modules:  # pragma: no cover - depends on test ordering
    _stub = types.ModuleType("db")
    _stub.select = lambda *a, **k: []
    _stub.update = lambda *a, **k: None
    _stub.insert = lambda *a, **k: None
    sys.modules["db"] = _stub

import auto_remediate as ar  # noqa: E402

KEY = "ORCH_ATTEMPT_HARD_CAP"


class AttemptCapTestCase(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(KEY)
        os.environ.pop(KEY, None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(KEY, None)
        else:
            os.environ[KEY] = self._saved


class OverAttemptCapTest(AttemptCapTestCase):
    def test_the_reported_task_shape_is_over_the_cap(self):
        """attempt 24 / remediation_count 0 — invisible to HARD_CAP, caught here."""
        os.environ[KEY] = "20"
        self.assertTrue(ar.over_attempt_cap({"attempt": 24, "remediation_count": 0}))

    def test_a_normal_task_is_not_over_the_cap(self):
        self.assertFalse(ar.over_attempt_cap({"attempt": 2, "remediation_count": 1}))

    def test_the_boundary_is_inclusive(self):
        os.environ[KEY] = "5"
        self.assertTrue(ar.over_attempt_cap({"attempt": 5}))
        self.assertFalse(ar.over_attempt_cap({"attempt": 4}))

    def test_zero_disables_the_backstop(self):
        os.environ[KEY] = "0"
        self.assertFalse(ar.over_attempt_cap({"attempt": 9999}))

    def test_a_pushed_cap_takes_effect_without_a_restart(self):
        task = {"attempt": 10}
        os.environ[KEY] = "50"
        self.assertFalse(ar.over_attempt_cap(task))
        os.environ[KEY] = "5"
        self.assertTrue(ar.over_attempt_cap(task))

    def test_the_default_sits_well_above_the_remediation_hard_cap(self):
        self.assertGreater(ar._attempt_hard_cap(), ar.HARD_CAP,
                           "the backstop must never fire before HARD_CAP does")

    def test_garbage_and_negative_caps_fall_back_to_the_default(self):
        for bad in ("abc", "-3", "   ", ""):
            os.environ[KEY] = bad
            self.assertEqual(ar._attempt_hard_cap(), 25, bad)

    def test_it_never_raises_on_a_malformed_row(self):
        for task in ({}, {"attempt": None}, {"attempt": "many"}, {"attempt": []},
                     None, "not-a-task"):
            try:
                result = ar.over_attempt_cap(task if isinstance(task, dict) else {})
            except Exception as exc:  # noqa: BLE001 — the assertion IS "no exception"
                self.fail(f"over_attempt_cap raised {type(exc).__name__}: {exc}")
            self.assertIsInstance(result, bool)

    def test_a_malformed_attempt_is_treated_as_under_the_cap(self):
        """Fail open: a bad row must never cause a wrongful terminal shelve."""
        os.environ[KEY] = "1"
        self.assertFalse(ar.over_attempt_cap({"attempt": "many"}))


class GuardWiringTest(unittest.TestCase):
    def _source(self):
        with open(os.path.join(RUNNER, "auto_remediate.py"), "r",
                  encoding="utf-8", errors="replace") as handle:
            return handle.read()

    def test_the_guard_is_actually_called_in_run(self):
        self.assertIn("over_attempt_cap(t)", self._source())

    def test_the_guard_respects_human_holds(self):
        source = self._source()
        index = source.index("over_attempt_cap(t)")
        window = source[index:index + 400]
        self.assertIn("_requires_human_hold", window,
                      "a legal/material hold must outrank the attempt backstop")

    def test_the_guard_defers_to_hard_cap(self):
        source = self._source()
        index = source.index("over_attempt_cap(t)")
        self.assertIn("rc < HARD_CAP", source[index:index + 200],
                      "HARD_CAP owns the decompose-or-shelve decision; this is only a backstop")

    def test_the_shelve_write_releases_the_lane(self):
        source = self._source()
        index = source.index("over_attempt_cap(t)")
        window = source[index:index + 600]
        self.assertIn('"state": "SHELVED"', window)
        self.assertIn('"account": None', window)


if __name__ == "__main__":
    unittest.main()
