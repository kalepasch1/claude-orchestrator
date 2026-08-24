#!/usr/bin/env python3
"""
test_db_connectivity.py — Automated tests for database connectivity failure scenarios.

Covers:
- Network failures (connection refused, timeout, DNS resolution)
- Authentication errors (invalid credentials, expired tokens)
- Query execution timeouts
- Fail-soft error handling (graceful degradation, no crashes)

Acceptance criteria:
- Each failure scenario returns a well-structured error, never raises unhandled.
- Fail-soft paths log warnings but do not halt the orchestrator.
- No secrets or credentials appear in error messages or logs.
"""
import importlib
import io
import os
import sys
import urllib.error
import pytest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))

SERVICE_KEY = "test-service-key-placeholder"


def _db():
    """The db module, or skip. Imported per test so mock_env is already applied."""
    try:
        return importlib.import_module("db")
    except ImportError:  # pragma: no cover - environment without the runner on path
        pytest.skip("db module not importable")


@pytest.fixture
def fast_retries():
    """One attempt per call.

    db retries transport errors with an exponential backoff, so a test that
    drives a failure through the real request path would otherwise sit in
    time.sleep for seconds per case. The retry COUNT is asserted explicitly
    where it matters rather than being left to the default.
    """
    with mock.patch.dict(os.environ, {"ORCH_SUPABASE_RETRIES": "1"}):
        db = _db()
        # db reads SUPABASE_URL/KEY into module constants at IMPORT time, so setting
        # them in the environment from a fixture is too late: the request path
        # raises "set SUPABASE_URL and SUPABASE_SERVICE_KEY" before it ever reaches
        # urlopen. Patch the constants the module actually uses.
        with mock.patch.object(db, "HTTP_RETRIES", 1), \
             mock.patch.object(db, "URL", "https://test-project.supabase.co"), \
             mock.patch.object(db, "KEY", SERVICE_KEY):
            yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_env():
    """Minimal env with placeholder DB credentials."""
    env = {
        "SUPABASE_URL": "https://test-project.supabase.co",
        "SUPABASE_SERVICE_KEY": "test-service-key-placeholder",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        yield env

@pytest.fixture
def mock_db_module():
    """Import db module with mocked httpx/requests."""
    try:
        import db
        return db
    except ImportError:
        pytest.skip("db module not available in this checkout")


# ---------------------------------------------------------------------------
# Network failure scenarios
# ---------------------------------------------------------------------------
class TestNetworkFailures:
    """Verify graceful handling when the database is unreachable.

    These used to `mock.patch.object(db, "execute", ...)` and then call
    `db.execute(...)` -- patching a name db has never had, then asserting on the
    mock they had just installed. They tested nothing about db, and they errored
    with AttributeError rather than reporting that. They now drive the real
    request path by failing urlopen, which is where a real outage shows up.
    """

    def _urlopen_raises(self, db, exc):
        return mock.patch.object(db.urllib.request, "urlopen", side_effect=exc)

    def test_connection_refused(self, mock_env, fast_retries):
        db = _db()
        with self._urlopen_raises(db, urllib.error.URLError(ConnectionRefusedError("refused"))):
            with pytest.raises(Exception) as caught:
                db.select("tasks", {"select": "id", "limit": "1"})
        assert "refused" in str(caught.value).lower()

    def test_dns_resolution_failure(self, mock_env, fast_retries):
        db = _db()
        err = urllib.error.URLError(OSError("Name or service not known"))
        with self._urlopen_raises(db, err):
            with pytest.raises(Exception) as caught:
                db.select("tasks", {"select": "id", "limit": "1"})
        assert "name or service not known" in str(caught.value).lower()

    def test_timeout(self, mock_env, fast_retries):
        db = _db()
        with self._urlopen_raises(db, TimeoutError("Read timed out")):
            with pytest.raises(Exception) as caught:
                db.select("tasks", {"select": "id", "limit": "1"})
        assert "timed out" in str(caught.value).lower()

    def test_transport_failure_is_retried_then_surfaced(self, mock_env, fast_retries):
        """A transient transport error must be retried, not surfaced on sight."""
        db = _db()
        with mock.patch.object(db.urllib.request, "urlopen",
                               side_effect=TimeoutError("boom")) as opened:
            with pytest.raises(Exception):
                db.select("tasks", {"select": "id", "limit": "1"})
        assert opened.call_count > 1, "a transport error should be retried at least once"


# ---------------------------------------------------------------------------
# Authentication failures
# ---------------------------------------------------------------------------
class TestAuthFailures:
    """Verify auth errors are handled without leaking credentials.

    Same rewrite as above: the old versions raised an error they had constructed
    themselves and then checked that THAT string did not contain the service key,
    which it never could. These drive a real 401/403 through the request path and
    check what db actually puts in the exception.
    """

    def _http_error(self, code, body=b'{"message":"unauthorized"}'):
        return urllib.error.HTTPError(
            "https://test-project.supabase.co/rest/v1/tasks", code, "Unauthorized",
            {}, io.BytesIO(body))

    def test_invalid_credentials_no_secret_leak(self, mock_env, fast_retries):
        db = _db()
        with mock.patch.object(db.urllib.request, "urlopen",
                               side_effect=self._http_error(401)):
            with pytest.raises(Exception) as caught:
                db.select("tasks", {"select": "id", "limit": "1"})
        assert SERVICE_KEY not in str(caught.value), "service key leaked in the error"

    def test_expired_token_handling(self, mock_env, fast_retries):
        db = _db()
        with mock.patch.object(db.urllib.request, "urlopen",
                               side_effect=self._http_error(401, b'{"message":"JWT expired"}')):
            with pytest.raises(Exception) as caught:
                db.select("tasks", {"select": "id", "limit": "1"})
        assert SERVICE_KEY not in str(caught.value)

    def test_permanent_4xx_is_not_retried(self, mock_env, fast_retries):
        """A 401 cannot resolve by trying again; retrying it only burns time."""
        db = _db()
        with mock.patch.object(db.urllib.request, "urlopen",
                               side_effect=self._http_error(401)) as opened:
            with pytest.raises(Exception):
                db.select("tasks", {"select": "id", "limit": "1"})
        assert opened.call_count == 1


# ---------------------------------------------------------------------------
# Fail-soft behavior
# ---------------------------------------------------------------------------
class TestFailSoft:
    """The orchestrator must not halt on transient DB issues."""

    def test_agentic_repair_handles_db_failure(self, mock_env):
        """agentic_repair helpers should work even if DB is down."""
        import agentic_repair

        task = {"slug": "test-task", "prompt": "Fix something", "id": "abc-123"}
        # These should never raise regardless of DB state
        prompt = agentic_repair.in_session_prompt(task, "connection refused")
        assert "test-task" in prompt
        assert "connection refused" in prompt

    def test_repair_patch_no_db_dependency(self, mock_env):
        """repair_patch builds a patch dict without hitting the database.

        The fixture used attempt=0, which is the "never attempted" task. That
        takes the requeue-without-repair path, which deliberately carries NO
        remediation_count -- there is nothing to count yet -- so the assertion
        could not hold. A task that HAS been attempted is what exercises the
        repair path this test is about.
        """
        import agentic_repair

        task = {"slug": "test-task", "prompt": "Fix something", "attempt": 1,
                "note": "timeout error"}
        patch = agentic_repair.repair_patch(task, "timeout error")
        assert patch["state"] == "QUEUED"
        assert patch["remediation_count"] == 1
        assert "timeout error" in patch["prompt"]

    def test_never_attempted_task_is_requeued_without_a_repair_count(self, mock_env):
        """The other half of the contract, previously unasserted."""
        import agentic_repair

        task = {"slug": "test-task", "prompt": "Fix something", "attempt": 0}
        patch = agentic_repair.repair_patch(task, "timeout error")
        assert patch["state"] == "QUEUED"
        assert "remediation_count" not in patch
