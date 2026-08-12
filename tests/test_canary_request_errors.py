#!/usr/bin/env python3
"""Tests for canary.py's 4xx/5xx handling (canary-gemini-25 slice).

Acceptance: mock `requests.post` to return a 403. Running the script must print
an error containing '403' and exit with code 5 (non-zero). No retries may be
attempted for a 403.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import canary  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, reason=None):
        self.status_code = status_code
        self.reason = reason


class FakeSession:
    """Stand-in for the `requests` module; counts POST attempts."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = 0

    def post(self, url, **_kwargs):
        self.calls += 1
        if not self._responses:
            raise AssertionError("FakeSession: unexpected extra request")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class IsRetryableTest(unittest.TestCase):
    def test_5xx_is_retryable(self):
        for code in (500, 502, 503, 504, 599):
            self.assertTrue(canary.is_retryable(code))

    def test_4xx_is_not_retryable(self):
        for code in (400, 401, 403, 404, 422, 429, 499):
            self.assertFalse(canary.is_retryable(code))

    def test_2xx_and_3xx_are_not_retryable(self):
        for code in (200, 201, 204, 301, 302):
            self.assertFalse(canary.is_retryable(code))

    def test_bad_input_is_fail_soft(self):
        for bad in (None, "x", object()):
            self.assertFalse(canary.is_retryable(bad))


class PerformRequestClientErrorTest(unittest.TestCase):
    """A 4xx must fail immediately with exit 5 and NO retries."""

    def test_403_exits_5_and_prints_status(self):
        session = FakeSession(FakeResponse(403, "Forbidden"))
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            code = canary.perform_request("https://example.test/canary", session=session)
        self.assertEqual(code, 5)
        self.assertIn("403", buffer.getvalue())

    def test_403_attempts_exactly_one_request(self):
        session = FakeSession(FakeResponse(403, "Forbidden"))
        with redirect_stderr(io.StringIO()):
            canary.perform_request("https://example.test/canary", session=session)
        self.assertEqual(session.calls, 1)

    def test_400_also_exits_5_without_retry(self):
        session = FakeSession(FakeResponse(400, "Bad Request"))
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            code = canary.perform_request("https://example.test/canary", session=session)
        self.assertEqual(code, 5)
        self.assertEqual(session.calls, 1)
        self.assertIn("400", buffer.getvalue())

    def test_401_and_429_exit_5(self):
        for status in (401, 429):
            session = FakeSession(FakeResponse(status))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(
                    canary.perform_request("https://example.test", session=session), 5
                )
            self.assertEqual(session.calls, 1)

    def test_reason_is_included_when_available(self):
        session = FakeSession(FakeResponse(403, "Forbidden"))
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            canary.perform_request("https://example.test", session=session)
        self.assertIn("Forbidden", buffer.getvalue())

    def test_reason_is_derived_when_absent(self):
        session = FakeSession(FakeResponse(403, None))
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            canary.perform_request("https://example.test", session=session)
        self.assertIn("403", buffer.getvalue())


class PerformRequestServerErrorTest(unittest.TestCase):
    """A 5xx is transient, so the retry loop still applies there."""

    def setUp(self):
        self._backoff = canary.ORCH_CANARY_BACKOFF_SECONDS
        canary.ORCH_CANARY_BACKOFF_SECONDS = 0.0

    def tearDown(self):
        canary.ORCH_CANARY_BACKOFF_SECONDS = self._backoff

    def test_500_is_retried_then_reports_transport_failure(self):
        session = FakeSession(FakeResponse(500), FakeResponse(500), FakeResponse(500))
        with redirect_stderr(io.StringIO()):
            code = canary.perform_request("https://example.test", session=session)
        self.assertEqual(code, 4)
        self.assertEqual(session.calls, 3)

    def test_500_then_success_returns_ok(self):
        session = FakeSession(FakeResponse(503), FakeResponse(200))
        self.assertEqual(canary.perform_request("https://example.test", session=session), 0)
        self.assertEqual(session.calls, 2)

    def test_transport_exception_is_retried(self):
        session = FakeSession(ConnectionError("boom"), FakeResponse(200))
        self.assertEqual(canary.perform_request("https://example.test", session=session), 0)
        self.assertEqual(session.calls, 2)

    def test_exhausted_transport_exceptions_return_4(self):
        session = FakeSession(*[ConnectionError("boom")] * 3)
        self.assertEqual(canary.perform_request("https://example.test", session=session), 4)


class PerformRequestSuccessTest(unittest.TestCase):
    def test_200_exits_0(self):
        session = FakeSession(FakeResponse(200))
        self.assertEqual(canary.perform_request("https://example.test", session=session), 0)
        self.assertEqual(session.calls, 1)

    def test_204_and_301_exit_0(self):
        for status in (204, 301):
            session = FakeSession(FakeResponse(status))
            self.assertEqual(canary.perform_request("https://example.test", session=session), 0)


class RequestOnlyCliTest(unittest.TestCase):
    """The `--request-only` path exits non-zero for a 4xx."""

    def test_request_only_403_exits_5(self):
        session = FakeSession(FakeResponse(403, "Forbidden"))
        original = canary.perform_request
        captured = {}

        def probe(url, payload=None, headers=None, session=None):
            captured["url"] = url
            return original(url, payload, headers, session or globals()["_session"])

        globals()["_session"] = session
        canary.perform_request = probe
        try:
            buffer = io.StringIO()
            with redirect_stderr(buffer):
                code = canary.main(["--request-only", "--url", "https://example.test"])
            self.assertEqual(code, 5)
            self.assertNotEqual(code, 0)
            self.assertIn("403", buffer.getvalue())
        finally:
            canary.perform_request = original

    def test_request_only_without_url_is_a_client_error(self):
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            self.assertEqual(canary.main(["--request-only"]), 5)

    def test_missing_requests_module_is_fail_soft(self):
        """No `session`, no `requests` installed -> transport failure, no raise."""
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def fake_import(name, *args, **kwargs):
            if name == "requests":
                raise ImportError("no requests")
            return real_import(name, *args, **kwargs)

        import builtins

        builtins.__import__ = fake_import
        try:
            self.assertEqual(canary.perform_request("https://example.test"), 4)
        finally:
            builtins.__import__ = real_import


class ValidationPathUnchangedTest(unittest.TestCase):
    """The pre-existing exit-code contract must not regress."""

    def test_marker_present_exits_0(self):
        self.assertEqual(canary.main(["this", "is", "a", "canary"]), 0)

    def test_marker_absent_exits_1(self):
        self.assertEqual(canary.main(["nothing", "here"]), 1)

    def test_validate_canary_still_works(self):
        self.assertTrue(canary.validate_canary("CANARY present"))
        self.assertFalse(canary.validate_canary("canaries are birds"))
        self.assertFalse(canary.validate_canary(None))


if __name__ == "__main__":
    unittest.main()
