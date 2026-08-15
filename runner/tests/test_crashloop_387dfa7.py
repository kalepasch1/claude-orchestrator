#!/usr/bin/env python3
"""Regression guards for the three silent crash loops in backlog batch 387dfa7.

Shared shape across all three jobs: an exception escaped the scheduled entrypoint,
so the job died and rewrote the same traceback every cycle — 4970 for preflight,
4670 for merge-train, 1642 for quarantine (the last with zero successful runs ever).
Volume made them invisible rather than obvious.

Two distinct root causes, two guards:
  1. merge-train — release_train.py referenced `release_manifest` in a function that
     never imported it. The call sat inside `except Exception: pass`, so the
     NameError was swallowed and the gate silently went unrecorded; static_sanity
     flagged the undefined name as CRITICAL and aborted merge_train at startup.
  2. preflight / quarantine — _invoke_job caught only MissingRelationError, so a
     Supabase timeout escaped as an unhandled URLError.
"""
import os
import socket
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMergeTrainStaticGate(unittest.TestCase):
    """merge_train aborts at startup if static_sanity finds a CRITICAL undefined name."""

    def test_static_gate_passes_for_merge_train(self):
        import static_sanity
        try:
            static_sanity.assert_critical("merge_train")
        except RuntimeError as e:
            self.fail(f"merge_train static gate still failing: {e}")

    def test_release_manifest_resolves_in_its_using_scope(self):
        import inspect
        import release_train
        src = inspect.getsource(release_train._integrate_regate_and_push)
        self.assertIn("import release_manifest", src,
                      "the function using release_manifest must import it")

    def test_manifest_recording_is_guarded_on_the_module(self):
        import inspect
        import release_train
        src = inspect.getsource(release_train._integrate_regate_and_push)
        self.assertIn("release_manifest is not None", src,
                      "a missing release_manifest must degrade, not raise")


class TestPeriodicTransientErrors(unittest.TestCase):
    """A network blip must not kill a scheduled job or emit a traceback."""

    def setUp(self):
        import periodic
        self.periodic = periodic

    def _run_job_raising(self, exc):
        with mock.patch.dict(self.periodic.JOBS, {"_probe": mock.Mock(side_effect=exc)}):
            with mock.patch.object(self.periodic, "_disabled_jobs", return_value={}):
                return self.periodic._invoke_job("_probe")

    def test_urlerror_timeout_is_absorbed(self):
        # The literal error from preflight.err / quarantine.err.
        self.assertIsNone(self._run_job_raising(urllib.error.URLError("timed out")))

    def test_socket_timeout_is_absorbed(self):
        self.assertIsNone(self._run_job_raising(socket.timeout("timed out")))

    def test_connection_error_is_absorbed(self):
        self.assertIsNone(self._run_job_raising(ConnectionResetError("reset by peer")))

    def test_http_5xx_is_absorbed(self):
        err = urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None)
        self.assertIsNone(self._run_job_raising(err))

    def test_http_429_is_absorbed(self):
        err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        self.assertIsNone(self._run_job_raising(err))

    def test_http_4xx_still_raises(self):
        # A 400 is a client bug. Absorbing it would hide a real defect.
        err = urllib.error.HTTPError("u", 400, "Bad Request", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            self._run_job_raising(err)

    def test_genuine_code_errors_still_raise(self):
        for exc in (ValueError("bad value"), KeyError("k"), TypeError("t"),
                    AttributeError("a"), NameError("n")):
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(type(exc)):
                    self._run_job_raising(exc)

    def test_transient_does_not_disable_the_job(self):
        # Disabling on a timeout would take a healthy job offline permanently.
        with mock.patch.object(self.periodic, "_disable_job") as dis:
            self._run_job_raising(urllib.error.URLError("timed out"))
            dis.assert_not_called()

    def test_missing_relation_still_disables(self):
        import db
        with mock.patch.object(self.periodic, "_disable_job") as dis:
            self._run_job_raising(db.MissingRelationError("no such table"))
            dis.assert_called_once()

    def test_successful_job_result_passes_through(self):
        with mock.patch.dict(self.periodic.JOBS, {"_probe": lambda: {"ok": True}}):
            with mock.patch.object(self.periodic, "_disabled_jobs", return_value={}):
                self.assertEqual(self.periodic._invoke_job("_probe"), {"ok": True})


if __name__ == "__main__":
    unittest.main()
