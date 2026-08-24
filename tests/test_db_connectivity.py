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

        self._assert_fails_soft(db, ConnectionError("Connection refused"))

    def test_dns_resolution_failure(self, mock_env):
        """DNS failure should not crash the orchestrator."""
        try:
            import db
        except ImportError:
            pytest.skip("db module not importable")

        self._assert_fails_soft(db, OSError("Name or service not known"))

    def test_timeout(self, mock_env):
        """Query timeout should degrade gracefully."""
        try:
            import db
        except ImportError:
            pytest.skip("db module not importable")

        self._assert_fails_soft(db, TimeoutError("Read timed out"))

    @staticmethod
    def _assert_fails_soft(db, error):
        """Drive db.select with the transport broken and assert it degrades.

        THE SEAM MATTERS. These three tests used to patch `db.execute` — a function that
        does not exist on this module — so mock.patch.object raised AttributeError and all
        three had been red. Worse, had the name existed the test would have mocked the very
        call it then invoked and asserted the mock raised: it exercised no db code at all.

        The real transport is urllib.request.urlopen inside db._req_one, so that is what is
        broken here. Retries are pinned to 1 and the timeout to 1s so the assertion is about
        behaviour, not about waiting out the production backoff schedule.

        db.URL/db.KEY are patched too, not just os.environ: db reads them once at import,
        so a fixture that only sets the environment leaves them empty and _req short-circuits
        with RuntimeError("set SUPABASE_URL...") before any transport is touched — the test
        would then be asserting on config validation, not on connectivity handling.
        """
        env = {"ORCH_SUPABASE_RETRIES": "1", "ORCH_SUPABASE_TIMEOUT": "1"}
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(db, "URL", "https://test-project.supabase.co"), \
                mock.patch.object(db, "KEY", "test-service-key-placeholder"), \
                mock.patch.object(db.urllib.request, "urlopen", side_effect=error):
            try:
                result = db.select("tasks", {"select": "id", "limit": "1"})
            except Exception as exc:  # a TYPED failure is the other acceptable outcome
                assert isinstance(exc, (db.TransientDBError, ConnectionError, OSError)), (
                    f"unreachable DB surfaced as {type(exc).__name__}: {exc}")
                assert "test-service-key-placeholder" not in str(exc), "key leaked"
            else:
                assert result in (None, []) or isinstance(result, (list, dict)), result


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

        # db.redact_secrets is the real guard every write path runs text through, so
        # assert on IT rather than on a mock that was never going to contain the key.
        leaky = ("401 Unauthorized calling https://test-project.supabase.co with "
                 "apikey=test-service-key-placeholder")
        redacted = db.redact_secrets(leaky)
        assert "test-service-key-placeholder" not in redacted, (
            "service key survived redaction")
        assert "[REDACTED]" in redacted

    def test_redact_secrets_is_fail_soft_on_non_text(self, mock_env):
        """It sits in front of writes; it must never be the thing that raises."""
        try:
            import db
        except ImportError:
            pytest.skip("db module not importable")

        for value in (None, "", 42, [], {}):
            assert db.redact_secrets(value) == value

    def test_expired_token_handling(self, mock_env):
        """An expired JWT is an ANSWER from the endpoint, not a connectivity failure.

        Pinned because the distinction is load-bearing in db.py: GATEWAY_STATUSES exists
        precisely so a proxy-level failure fails over while a real 4xx from PostgREST does
        not. A 401 must never be classified as a gateway error, or a bad key would silently
        rotate the fleet onto another endpoint instead of surfacing.
        """
        try:
            import db
        except ImportError:
            pytest.skip("db module not importable")

        assert 401 not in db.GATEWAY_STATUSES
        assert 401 not in db.HTTP_RETRY_STATUSES, "an auth failure must not be retried"


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

        A task at attempt=0 with no failure evidence has NEVER RUN, so the patch is a
        plain requeue: original prompt, no repair directive, no remediation_count. This
        assertion used to demand `remediation_count == 1` here and had been failing since
        the 2026-08-03 fix (69% of repairs in a measured window were applied to tasks that
        had never run, each one stacking a false "continue your prior work" directive onto
        a task with no prior work). The test was pinning the bug; it now pins the fix.
        """
        import agentic_repair

        task = {"slug": "test-task", "prompt": "Fix something", "attempt": 0}
        patch = agentic_repair.repair_patch(task, "timeout error")
        assert patch["state"] == "QUEUED"
        assert patch["account"] is None
        assert "remediation_count" not in patch, "a never-run task must not be counted"
        assert patch["prompt"] == "Fix something", "the original prompt must survive"
        assert "timeout error" not in patch["prompt"]

    def test_repair_patch_counts_a_task_that_actually_ran(self, mock_env):
        """The other half of the contract: real evidence -> counted, directive applied."""
        import agentic_repair

        task = {"slug": "test-task", "prompt": "Fix something", "attempt": 2,
                "remediation_count": 0}
        patch = agentic_repair.repair_patch(task, "timeout error")
        assert patch["state"] == "QUEUED"
        assert patch["remediation_count"] == 1
        assert patch["attempt"] == 3
        assert "timeout error" in patch["prompt"]

    def test_repair_patch_leaves_the_prompt_alone_when_the_caller_did_not_select_it(self, mock_env):
        """A sweep querying a narrow column set must not have the spec overwritten with
        in_session_prompt()'s "Complete the task '<slug>'." fallback."""
        import agentic_repair

        patch = agentic_repair.repair_patch(
            {"slug": "test-task", "attempt": 2, "remediation_count": 0}, "timeout error")
        assert "prompt" not in patch

    def test_repair_patch_never_consumes_an_operator_decision(self, mock_env):
        """Escalations are records, not work: released but never repaired or rewritten."""
        import agentic_repair

        prefix = agentic_repair.OPERATOR_DECISION_PREFIXES
        slug = (prefix[0] if isinstance(prefix, tuple) else prefix) + "something"
        patch = agentic_repair.repair_patch(
            {"slug": slug, "prompt": "Decide something", "attempt": 4}, "timeout error")
        assert patch["state"] == "QUEUED"
        assert "remediation_count" not in patch
        assert "prompt" not in patch
