#!/usr/bin/env python3
"""merge_train must not crashloop when the control plane is unreachable.

The db circuit breaker raises ControlPlaneDown by design: during an origin outage it
fails fast instead of paying a full timeout per call. Nothing in merge_train caught it,
so every 60s scheduler cycle exited with an unhandled traceback into
.runtime/logs/merge-train.err — 127 identical stacks, all of them the breaker working
correctly, with the real signal ("the origin is unreachable") buried underneath.

A pass cannot do anything without the project list, so an outage is a reported NON-RUN,
like a host pause — not a crash.

Proof: python3 -m pytest runner/tests/test_merge_train_control_plane_down.py -q
"""
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402


class TestBreakerOpenIsReadOnly(unittest.TestCase):
    """The probe must not consume the half-open election."""

    def setUp(self):
        self._saved = dict(db._BREAKER)
        self.addCleanup(lambda: db._BREAKER.update(self._saved))

    def _open(self, seconds=60.0):
        db._BREAKER.update(consecutive=8, open_until=time.monotonic() + seconds,
                           trips=1, probing=False)

    def _closed(self):
        db._BREAKER.update(consecutive=0, open_until=0.0, trips=0, probing=False)

    def test_reports_open_while_open(self):
        self._open()
        self.assertTrue(db.breaker_open())

    def test_reports_closed_when_closed(self):
        self._closed()
        self.assertFalse(db.breaker_open())

    def test_does_not_elect_itself_as_the_prober(self):
        self._open()
        db.breaker_open()
        self.assertFalse(db._BREAKER["probing"],
                         "breaker_open() consumed the half-open probe slot")

    def test_repeated_calls_do_not_mutate_state(self):
        self._open()
        before = dict(db._BREAKER)
        for _ in range(5):
            db.breaker_open()
        self.assertEqual(dict(db._BREAKER), before)

    def test_expired_cooldown_reads_as_closed_without_electing(self):
        db._BREAKER.update(consecutive=8, open_until=time.monotonic() - 1,
                           trips=1, probing=False)
        self.assertFalse(db.breaker_open())
        self.assertFalse(db._BREAKER["probing"])

    def test_disabled_breaker_is_never_open(self):
        self._open()
        with patch.object(db, "DB_BREAKER_ENABLED", False):
            self.assertFalse(db.breaker_open())

    def test_never_raises(self):
        with patch.object(db, "_BREAKER", None):
            self.assertFalse(db.breaker_open())


class TestTrainRunSkipsInsteadOfCrashing(unittest.TestCase):
    """The pass must convert the outage into a reported skip, not a traceback."""

    def _run(self, extra_patches=()):
        import merge_train
        import contextlib
        boom = db.ControlPlaneDown(
            "control plane circuit breaker open (8 consecutive unreachable)")
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(merge_train, "_train_run_unleased",
                                             side_effect=boom))
            stack.enter_context(patch.object(merge_train.paused_host_guard, "refuse",
                                             return_value=(True, "")))
            stack.enter_context(patch.object(merge_train.delivery_lease, "release_all",
                                             return_value=None))
            for ctx in extra_patches:
                stack.enter_context(ctx)
            return merge_train.train_run()

    def test_control_plane_down_returns_a_skip_not_an_exception(self):
        summary = self._run()
        self.assertIn("skipped", summary)
        self.assertIn("control plane unreachable", summary["skipped"])

    def test_the_skip_reports_whether_the_breaker_is_open(self):
        self.assertIn("breaker_open", self._run())

    def test_the_skip_is_reported_not_silent(self):
        """An outage and a wedged train must not produce the same empty result."""
        recorded = {}

        class _Report:
            def not_run(self, reason):
                recorded["reason"] = reason

            def persist(self):
                recorded["persisted"] = True

        fake = type("_M", (), {"PassReport": lambda **kw: _Report()})
        self._run([patch.dict(sys.modules, {"merge_train_report": fake})])
        self.assertIn("control-plane-down", recorded.get("reason", ""))
        self.assertTrue(recorded.get("persisted"))

    def test_a_host_pause_still_wins(self):
        """Ordering guard: a paused host must report the pause, not the outage."""
        import merge_train
        with patch.object(merge_train.paused_host_guard, "refuse",
                          return_value=(False, "operator paused")):
            summary = merge_train.train_run()
        self.assertEqual(summary["skipped"], "operator paused")

    def test_a_healthy_pass_is_untouched(self):
        """The handler must not swallow or reshape a normal result."""
        import merge_train
        with patch.object(merge_train, "_train_run_unleased",
                          return_value={"merged": 3}), \
             patch.object(merge_train.paused_host_guard, "refuse", return_value=(True, "")), \
             patch.object(merge_train.delivery_lease, "release_all", return_value=None):
            self.assertEqual(merge_train.train_run(), {"merged": 3})

    def test_other_exceptions_still_propagate(self):
        """Only the transient outage is absorbed; a real defect must still be loud."""
        import merge_train
        with patch.object(merge_train, "_train_run_unleased",
                          side_effect=ValueError("real bug")), \
             patch.object(merge_train.paused_host_guard, "refuse", return_value=(True, "")), \
             patch.object(merge_train.delivery_lease, "release_all", return_value=None):
            with self.assertRaises(ValueError):
                merge_train.train_run()


class TestEntrypointBackstop(unittest.TestCase):
    def test_entrypoint_catches_control_plane_down(self):
        """The pass that trips the breaker MID-flight must also exit cleanly."""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "merge_train.py")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        tail = source[source.index("print(json.dumps(train_run()"):]
        self.assertIn("except db.ControlPlaneDown", tail)
        self.assertIn("sys.exit(0)", tail)

    def test_control_plane_down_is_a_transient_error(self):
        """It is an outage, not a defect — the type says so, and the handling follows."""
        self.assertTrue(issubclass(db.ControlPlaneDown, db.TransientDBError))


if __name__ == "__main__":
    unittest.main()
