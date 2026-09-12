"""A network blip inside a periodic job must skip that job, not kill the cycle.

_is_transient_net_error() was written for _invoke_job() and then never wired up — it sat in
periodic.py with no caller anywhere in the repo. The consequence was that db.TransientDBError
(which db raises only for the failures it recognises and wraps) was handled, while a bare
urllib.error.URLError from a Supabase read that merely timed out escaped _invoke_job entirely
and took down the whole periodic cycle: every job scheduled after the one that blipped simply
never ran.

These tests pin both halves of the wiring — the skip for transient network errors, and the
re-raise for everything the predicate rejects, which is what keeps genuine job bugs loud.
"""
import contextlib
import io
import os
import socket
import sys
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import periodic  # noqa: E402


class _Boom:
    """A callable JOBS entry that raises whatever it was handed."""

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise self.exc


class InvokeJobTransientNetTest(unittest.TestCase):
    JOB = "_test_transient_net_job"

    def _invoke(self, exc):
        job = _Boom(exc)
        with patch.dict(periodic.JOBS, {self.JOB: job}, clear=False):
            result = periodic._invoke_job(self.JOB)
        self.assertEqual(job.calls, 1)
        return result

    def _expect_raise(self, exc):
        job = _Boom(exc)
        with patch.dict(periodic.JOBS, {self.JOB: job}, clear=False):
            with self.assertRaises(type(exc)):
                periodic._invoke_job(self.JOB)

    def test_urlerror_skips_the_cycle_instead_of_crashing_it(self):
        self.assertIsNone(self._invoke(urllib.error.URLError(socket.timeout("timed out"))))

    def test_socket_timeout_skips(self):
        self.assertIsNone(self._invoke(socket.timeout("timed out")))

    def test_connection_reset_skips(self):
        self.assertIsNone(self._invoke(ConnectionResetError("peer reset")))

    def test_http_5xx_skips(self):
        self.assertIsNone(
            self._invoke(urllib.error.HTTPError("http://x", 503, "Service Unavailable", {}, None)))

    def test_http_429_skips(self):
        self.assertIsNone(
            self._invoke(urllib.error.HTTPError("http://x", 429, "Too Many Requests", {}, None)))

    def test_http_400_still_raises(self):
        """A 4xx means we reached the server and sent it something wrong. That is a client
        bug and must stay as loud as it was before this handler existed."""
        self._expect_raise(
            urllib.error.HTTPError("http://x", 400, "Bad Request", {}, None))

    def test_a_programming_error_still_raises(self):
        """The handler must not become a blanket `except Exception: return`. A ValueError in
        a job body is a real defect; swallowing it into a 'skipped' dict would hide it for as
        long as the job keeps running."""
        self._expect_raise(ValueError("bad value in job body"))

    def test_an_attribute_error_still_raises(self):
        self._expect_raise(AttributeError("NoneType has no attribute 'get'"))

    def test_the_skip_is_announced_on_stdout(self):
        """The return value carries nothing an operator can read — __main__ only checks for
        _Skipped and exits 0 either way — so the printed line IS the observability. Without
        it a job that skipped every cycle for an hour would look identical to one that ran."""
        job = _Boom(urllib.error.URLError("connection refused"))
        buf = io.StringIO()
        with patch.dict(periodic.JOBS, {self.JOB: job}, clear=False), \
             contextlib.redirect_stdout(buf):
            periodic._invoke_job(self.JOB)
        printed = buf.getvalue()
        self.assertIn(self.JOB, printed)
        self.assertIn("transient network error", printed)
        self.assertIn("URLError", printed)

    def test_a_transient_net_error_does_not_disable_the_job(self):
        """Disabling on a network blip would take a healthy job offline for the whole
        outage — the opposite of what a skip is for."""
        job = _Boom(urllib.error.URLError("timed out"))
        with patch.dict(periodic.JOBS, {self.JOB: job}, clear=False), \
             patch.object(periodic, "_disable_job") as disable:
            periodic._invoke_job(self.JOB)
        disable.assert_not_called()


if __name__ == "__main__":
    unittest.main()
