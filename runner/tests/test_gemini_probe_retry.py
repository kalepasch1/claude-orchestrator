#!/usr/bin/env python3
"""Retry the provider's bad minute; never retry a dead key.

Recreation of the missing canary-gemini-25 request work (`request-retry-logic` +
`request-invalid-key-error`), which the family's branch lost.

Both halves matter and they pull against each other. A canary that runs every 5 minutes
and reports an outage on a single 503 gets ignored within a day. A canary that patiently
retries a revoked credential three times delays the one failure a human must fix
personally, and buries it under transport noise. So the split is explicit and pinned
here: 429/5xx/timeout are retried with backoff, 400/401/403 raise immediately.

`sleep` is injected throughout — these assert the backoff schedule without waiting for it.
"""
import io
import os
import sys
import unittest
import urllib.error
from contextlib import redirect_stderr
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import gemini_canary_probe as probe


def http_error(code):
    return urllib.error.HTTPError("url", code, "err", None, None)


class _Responder:
    """urlopen stand-in: raises the queued outcomes in order, then returns a good body."""

    def __init__(self, outcomes, body='{"candidates":[{"content":{"parts":[{"text":"canary"}]}}]}'):
        self.outcomes = list(outcomes)
        self.body = body
        self.calls = 0

    def __call__(self, *_args, **_kwargs):
        self.calls += 1
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        return self

    # context-manager protocol for `with urlopen(...) as r`
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self):
        return self.body.encode()


class TestRetryOnTransient(unittest.TestCase):
    def test_a_single_503_does_not_fail_the_canary(self):
        responder = _Responder([http_error(503)])
        with patch.object(probe.urllib.request, "urlopen", responder):
            self.assertEqual(probe.probe_gemini("k", sleep=lambda _s: None), "canary")
        self.assertEqual(responder.calls, 2)

    def test_every_retryable_status_is_retried(self):
        for status in sorted(probe.RETRYABLE_STATUSES):
            with self.subTest(status=status):
                responder = _Responder([http_error(status)])
                with patch.object(probe.urllib.request, "urlopen", responder):
                    self.assertEqual(probe.probe_gemini("k", sleep=lambda _s: None), "canary")
                self.assertEqual(responder.calls, 2)

    def test_transport_failures_are_retried(self):
        for error in (urllib.error.URLError("dns"), TimeoutError("slow"), OSError("reset")):
            with self.subTest(error=type(error).__name__):
                responder = _Responder([error])
                with patch.object(probe.urllib.request, "urlopen", responder):
                    self.assertEqual(probe.probe_gemini("k", sleep=lambda _s: None), "canary")

    def test_backoff_is_exponential(self):
        delays = []
        responder = _Responder([http_error(503), http_error(503)])
        with patch.object(probe.urllib.request, "urlopen", responder):
            probe.probe_gemini("k", attempts=3, sleep=delays.append)
        self.assertEqual(delays, [probe.BACKOFF_BASE_S, probe.BACKOFF_BASE_S * 2])

    def test_attempts_are_bounded(self):
        # A canary that retries forever never reports, which is the same as no canary.
        responder = _Responder([http_error(503)] * 10)
        with patch.object(probe.urllib.request, "urlopen", responder):
            with self.assertRaises(urllib.error.HTTPError):
                probe.probe_gemini("k", attempts=3, sleep=lambda _s: None)
        self.assertEqual(responder.calls, 3)

    def test_attempts_below_one_still_makes_one_call(self):
        responder = _Responder([])
        with patch.object(probe.urllib.request, "urlopen", responder):
            self.assertEqual(probe.probe_gemini("k", attempts=0, sleep=lambda _s: None),
                             "canary")
        self.assertEqual(responder.calls, 1)


class TestInvalidKeyIsNeverRetried(unittest.TestCase):
    def test_auth_failures_raise_immediately(self):
        for status in sorted(probe.AUTH_STATUSES):
            with self.subTest(status=status):
                responder = _Responder([http_error(status)])
                with patch.object(probe.urllib.request, "urlopen", responder):
                    with self.assertRaises(probe.InvalidKeyError):
                        probe.probe_gemini("bad-key", sleep=lambda _s: None)
                self.assertEqual(responder.calls, 1, "a dead key must not be retried")

    def test_no_backoff_is_spent_on_a_dead_key(self):
        delays = []
        responder = _Responder([http_error(403)])
        with patch.object(probe.urllib.request, "urlopen", responder):
            with self.assertRaises(probe.InvalidKeyError):
                probe.probe_gemini("bad-key", sleep=delays.append)
        self.assertEqual(delays, [])

    def test_the_message_names_the_credential_not_the_provider(self):
        responder = _Responder([http_error(401)])
        with patch.object(probe.urllib.request, "urlopen", responder):
            try:
                probe.probe_gemini("bad-key", sleep=lambda _s: None)
                self.fail("expected InvalidKeyError")
            except probe.InvalidKeyError as exc:
                self.assertIn("GEMINI_API_KEY", str(exc))
                self.assertIn("Not retried", str(exc))

    def test_main_reports_a_dead_key_distinctly(self):
        # Asserted on the log record, not raw stderr: the module logs through `logger`,
        # so a handler (pytest's, or an embedding app's) may own the stream.
        with patch.object(probe, "probe_gemini",
                          side_effect=probe.InvalidKeyError("GEMINI_API_KEY rejected")), \
             patch.dict(os.environ, {"GEMINI_API_KEY": "x"}), \
             self.assertLogs(probe.logger, level="ERROR") as captured:
            self.assertEqual(probe.main(), 1)
        self.assertTrue(any("GEMINI_API_KEY rejected" in line for line in captured.output),
                        captured.output)

    def test_a_non_retryable_non_auth_status_is_raised_as_is(self):
        # 404 is a wrong model name, not a transient fault and not a bad key. Guessing
        # either way is how a real fault gets absorbed.
        responder = _Responder([http_error(404)])
        with patch.object(probe.urllib.request, "urlopen", responder):
            with self.assertRaises(urllib.error.HTTPError):
                probe.probe_gemini("k", sleep=lambda _s: None)
        self.assertEqual(responder.calls, 1)


class TestClassification(unittest.TestCase):
    def test_retryable_and_auth_sets_do_not_overlap(self):
        self.assertFalse(probe.RETRYABLE_STATUSES & probe.AUTH_STATUSES,
                         "a status cannot be both retried and treated as a dead key")

    def test_is_retryable(self):
        self.assertTrue(probe.is_retryable(503))
        self.assertTrue(probe.is_retryable("429"))
        self.assertFalse(probe.is_retryable(403))
        self.assertFalse(probe.is_retryable(200))


if __name__ == "__main__":
    unittest.main(verbosity=2)
