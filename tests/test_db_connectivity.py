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
import os
import socket
import sys
import urllib.error

import pytest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runner_modules  # noqa: E402


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
        return runner_modules.load("db")
    except ImportError:
        pytest.skip("db module not available in this checkout")


SERVICE_KEY = "test-service-key-placeholder"


@pytest.fixture
def db_module(mock_env):
    """`db` with placeholder credentials installed on the module itself.

    db.py resolves SUPABASE_URL/SUPABASE_SERVICE_KEY at import time, so patching
    os.environ alone leaves the real values in place. Overriding the module
    attributes keeps the transport tests hermetic and lets the secret-leak
    assertions check a key we control.

    This is a PRIVATE copy of db, not the shared one. db pins the endpoint that
    last answered in module globals, so pointing the shared instance at a
    placeholder host leaked out of this file and left later tests in the same
    session dialling `test-project.supabase.co` until they timed out.
    """
    try:
        db = runner_modules.load_isolated("db")
    except ImportError:
        pytest.skip("db module not importable")

    with mock.patch.object(db, "URL", "https://test-project.supabase.co"), \
            mock.patch.object(db, "KEY", SERVICE_KEY), \
            mock.patch.object(db, "_save_active_base", lambda *a, **k: None):
        db._ACTIVE_BASE["url"] = None
        yield db


def _assert_fail_soft(db, exc):
    """A transport failure must surface cleanly and never echo the service key.

    `db.select` either degrades to a structured result or raises — both are
    acceptable. What is never acceptable is a credential in the error text.
    """
    with mock.patch.object(db, "_req_one", side_effect=exc):
        try:
            result = db.select("tasks")
        except Exception as raised:          # noqa: BLE001 — any transport error is in scope
            assert SERVICE_KEY not in str(raised), "Service key leaked in error message"
            assert SERVICE_KEY not in repr(raised), "Service key leaked in error repr"
        else:
            assert result is None or isinstance(result, (list, dict))
            assert SERVICE_KEY not in repr(result), "Service key leaked in result"


# ---------------------------------------------------------------------------
# Network failure scenarios
# ---------------------------------------------------------------------------
class TestNetworkFailures:
    """Verify graceful handling when the database is unreachable."""

    def test_connection_refused(self, db_module):
        """Simulate connection refused — surfaces cleanly, never crashes mid-write."""
        _assert_fail_soft(db_module, ConnectionRefusedError("Connection refused"))

    def test_dns_resolution_failure(self, db_module):
        """DNS failure should not crash the orchestrator."""
        _assert_fail_soft(
            db_module, urllib.error.URLError(socket.gaierror("Name or service not known"))
        )

    def test_timeout(self, db_module):
        """Query timeout should degrade gracefully."""
        _assert_fail_soft(db_module, socket.timeout("Read timed out"))

    def test_transport_failure_is_not_swallowed_silently(self, db_module):
        """Failing over every endpoint must still surface the last error.

        A silent `None` here would look identical to "the table is empty", which
        is how a dead database once read as a drained queue.
        """
        with mock.patch.object(db_module, "_req_one", side_effect=socket.timeout("down")):
            with pytest.raises(Exception):
                db_module.select("tasks")


# ---------------------------------------------------------------------------
# Authentication failures
# ---------------------------------------------------------------------------
class TestAuthFailures:
    """Verify auth errors are handled without leaking credentials."""

    def _http_error(self, code, reason):
        return urllib.error.HTTPError(
            url="https://test-project.supabase.co/rest/v1/tasks",
            code=code, msg=reason, hdrs=None, fp=None,
        )

    def test_invalid_credentials_no_secret_leak(self, db_module):
        """Error messages must not contain the service key."""
        _assert_fail_soft(db_module, self._http_error(401, "Unauthorized"))

    def test_expired_token_handling(self, db_module):
        """Expired JWT should produce a clear error, not a crash."""
        _assert_fail_soft(db_module, self._http_error(401, "JWT expired"))

    def test_redact_secrets_strips_the_service_key(self, db_module):
        """The redactor is the last line of defence before anything is logged."""
        leaked = f"auth failed with apikey={SERVICE_KEY} against tasks"
        assert SERVICE_KEY not in db_module.redact_secrets(leaked)


# ---------------------------------------------------------------------------
# Fail-soft behavior
# ---------------------------------------------------------------------------
class TestFailSoft:
    """The orchestrator must not halt on transient DB issues."""

    def test_agentic_repair_handles_db_failure(self, mock_env):
        """agentic_repair helpers should work even if DB is down."""
        agentic_repair = runner_modules.load("agentic_repair")

        task = {"slug": "test-task", "prompt": "Fix something", "id": "abc-123"}
        # These should never raise regardless of DB state
        prompt = agentic_repair.in_session_prompt(task, "connection refused")
        assert "test-task" in prompt
        assert "connection refused" in prompt

    def test_repair_patch_no_db_dependency(self, mock_env):
        """repair_patch builds a patch dict without hitting the database.

        `attempt` is 1, not 0: a task that has never run takes the deliberate
        never-ran path in repair_patch, which requeues WITHOUT advancing
        remediation_count so a task that was never given a chance cannot inflate
        its way to the repair ceiling. This case is the ordinary repair.

        `choose_coder` is the one step on this path that reads fleet config, so
        it is stubbed — otherwise the test would sit in db.py's retry backoff
        rather than proving the patch is assembled locally.
        """
        agentic_repair = runner_modules.load("agentic_repair")

        task = {"slug": "test-task", "prompt": "Fix something", "attempt": 1}
        with mock.patch.object(agentic_repair, "choose_coder", return_value="claude"):
            patch = agentic_repair.repair_patch(task, "timeout error")
        assert patch["state"] == "QUEUED"
        assert patch["remediation_count"] == 1
        assert "timeout error" in patch["prompt"]

    def test_repair_patch_never_ran_task_does_not_burn_a_remediation(self, mock_env):
        """A task with attempt=0 is requeued without spending its repair budget."""
        agentic_repair = runner_modules.load("agentic_repair")

        task = {"slug": "test-task", "prompt": "Fix something", "attempt": 0}
        patch = agentic_repair.repair_patch(task, "timeout error")
        assert patch["state"] == "QUEUED"
        assert patch.get("remediation_count") in (None, 0)
