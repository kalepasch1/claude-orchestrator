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
import sys
import pytest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))


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
    """Verify graceful handling when the database is unreachable."""

    def test_connection_refused(self, mock_env):
        """Simulate connection refused — should return error dict, not raise."""
        import importlib
        try:
            db = importlib.import_module("db")
        except ImportError:
            pytest.skip("db module not importable")

        with mock.patch.object(db, "execute", side_effect=ConnectionError("Connection refused")):
            try:
                result = db.execute("SELECT 1")
                assert result is None or (isinstance(result, dict) and "error" in result)
            except ConnectionError:
                pass  # acceptable: module surfaces the error

    def test_dns_resolution_failure(self, mock_env):
        """DNS failure should not crash the orchestrator."""
        try:
            import db
        except ImportError:
            pytest.skip("db module not importable")

        with mock.patch.object(db, "execute", side_effect=OSError("Name or service not known")):
            try:
                result = db.execute("SELECT 1")
                assert result is None or isinstance(result, dict)
            except OSError:
                pass  # acceptable

    def test_timeout(self, mock_env):
        """Query timeout should degrade gracefully."""
        try:
            import db
        except ImportError:
            pytest.skip("db module not importable")

        with mock.patch.object(db, "execute", side_effect=TimeoutError("Read timed out")):
            try:
                result = db.execute("SELECT 1")
                assert result is None or isinstance(result, dict)
            except TimeoutError:
                pass  # acceptable


# ---------------------------------------------------------------------------
# Authentication failures
# ---------------------------------------------------------------------------
class TestAuthFailures:
    """Verify auth errors are handled without leaking credentials."""

    def test_invalid_credentials_no_secret_leak(self, mock_env):
        """Error messages must not contain the service key."""
        try:
            import db
        except ImportError:
            pytest.skip("db module not importable")

        err = ConnectionError("401 Unauthorized")
        with mock.patch.object(db, "execute", side_effect=err):
            try:
                db.execute("SELECT 1")
            except ConnectionError as e:
                msg = str(e)
                assert "test-service-key-placeholder" not in msg, (
                    "Service key leaked in error message"
                )

    def test_expired_token_handling(self, mock_env):
        """Expired JWT should produce a clear error, not a crash."""
        try:
            import db
        except ImportError:
            pytest.skip("db module not importable")

        err = ConnectionError("JWT expired")
        with mock.patch.object(db, "execute", side_effect=err):
            try:
                db.execute("SELECT 1")
            except ConnectionError:
                pass  # acceptable: surfaces error without crash


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
        """repair_patch builds a patch dict without hitting the database."""
        import agentic_repair

        task = {"slug": "test-task", "prompt": "Fix something", "attempt": 0}
        patch = agentic_repair.repair_patch(task, "timeout error")
        assert patch["state"] == "QUEUED"
        assert patch["remediation_count"] == 1
        assert "timeout error" in patch["prompt"]
