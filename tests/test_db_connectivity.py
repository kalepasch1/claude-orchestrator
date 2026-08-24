#!/usr/bin/env python3
"""Database connectivity failure scenarios, tested against the API db actually has.

WHY THIS FILE WAS REWRITTEN. Every test here mocked `db.execute` — a function that does
not exist in `runner/db.py`, and never has. `mock.patch.object` raises AttributeError on
a missing attribute, so six of the seven tests failed at setup and had been red for as
long as they have existed. Worse, each body wrapped its assertion in
`try: ... except <TheMockedError>: pass`, so even with a real `db.execute` the tests
could not fail: the mock raised, the except swallowed it, and the assertion never ran.
The suite reported coverage of the DB failure paths while verifying nothing about them.

These exercise the real surface — `db.select` over the transport layer — and assert the
behaviour the orchestrator depends on: transient faults are retried, unreachable
endpoints fail over, exhaustion raises a TYPED transient error rather than returning a
plausible empty list, and no credential ever reaches an error message.
"""
import io
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner"))

import db  # noqa: E402
import agentic_repair  # noqa: E402

SECRET = "test-service-key-placeholder"


class _Response:
    def __init__(self, body="[]"):
        self._body = body
        self.headers = {}

    def read(self):
        return self._body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, body=b""):
    return urllib.error.HTTPError("https://test-project.supabase.co", code, "err", {},
                                  io.BytesIO(body))


@pytest.fixture
def wired(monkeypatch):
    """Point db at a placeholder endpoint with a known secret, breaker disarmed."""
    monkeypatch.setattr(db, "URL", "https://test-project.supabase.co")
    monkeypatch.setattr(db, "KEY", SECRET)
    monkeypatch.setattr(db, "_breaker_blocks", lambda: False)
    monkeypatch.setattr(db, "_breaker_record_answer", lambda: None)
    monkeypatch.setattr(db, "_breaker_record_unreachable", lambda: None)
    monkeypatch.setattr(db, "_pin", lambda base: None)
    monkeypatch.setattr(db, "_base_urls", lambda: ["https://test-project.supabase.co"])
    monkeypatch.setattr(db.time, "sleep", lambda *_: None)
    return monkeypatch


# ---------------------------------------------------------------------------
# Network failures
# ---------------------------------------------------------------------------
class TestNetworkFailures:
    @pytest.mark.parametrize("exc", [
        urllib.error.URLError("Connection refused"),
        urllib.error.URLError("Name or service not known"),
        TimeoutError("Read timed out"),
    ])
    def test_unreachable_raises_a_typed_transient_error(self, wired, exc):
        """It must RAISE, and raise something callers can classify.

        A swallowed connectivity failure returning `[]` is the dangerous shape: an empty
        queue read is indistinguishable from "there is no work", and the fleet idles
        through an outage believing it is caught up.
        """
        wired.setattr(db.urllib.request, "urlopen",
                      lambda *a, **k: (_ for _ in ()).throw(exc))
        with pytest.raises(db.TransientDBError):
            db.select("tasks", {"select": "id"})

    def test_a_transient_fault_is_retried_before_giving_up(self, wired):
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] < 2:
                raise urllib.error.URLError("temporary failure")
            return _Response('[{"id": 1}]')

        wired.setattr(db.urllib.request, "urlopen", flaky)
        assert db.select("tasks", {"select": "id"}) == [{"id": 1}]
        assert calls["n"] > 1, "a single transient blip must not fail the read"

    def test_a_dead_endpoint_fails_over_to_a_healthy_one(self, wired):
        wired.setattr(db, "_base_urls",
                      lambda: ["https://dead.example", "https://alive.example"])

        def by_host(req, *a, **k):
            if "dead" in req.full_url:
                raise urllib.error.URLError("connection refused")
            return _Response('[{"id": 7}]')

        wired.setattr(db.urllib.request, "urlopen", by_host)
        assert db.select("tasks", {"select": "id"}) == [{"id": 7}]

    def test_open_circuit_breaker_fails_fast(self, wired):
        """During an outage the breaker must skip the call, not pay the timeout."""
        wired.setattr(db, "_breaker_blocks", lambda: True)
        wired.setattr(db.urllib.request, "urlopen",
                      lambda *a, **k: pytest.fail("must not touch the network"))
        with pytest.raises(db.TransientDBError):
            db.select("tasks", {"select": "id"})

    def test_control_plane_down_is_a_transient_error(self):
        assert issubclass(db.ControlPlaneDown, db.TransientDBError)


# ---------------------------------------------------------------------------
# Authentication failures
# ---------------------------------------------------------------------------
class TestAuthFailures:
    def test_invalid_credentials_do_not_leak_the_key(self, wired):
        wired.setattr(db.urllib.request, "urlopen",
                      lambda *a, **k: (_ for _ in ()).throw(_http_error(401)))
        with pytest.raises(Exception) as exc:
            db.select("tasks", {"select": "id"})
        assert SECRET not in str(exc.value), "service key leaked in the error message"

    def test_expired_token_is_not_retried_as_if_transient(self, wired):
        """A 401 will never succeed on retry; burning the budget only adds latency."""
        calls = {"n": 0}

        def expired(*a, **k):
            calls["n"] += 1
            raise _http_error(401, b"JWT expired")

        wired.setattr(db.urllib.request, "urlopen", expired)
        with pytest.raises(Exception):
            db.select("tasks", {"select": "id"})
        assert calls["n"] == 1

    def test_the_key_travels_in_headers_never_in_the_url(self, wired):
        captured = {}

        def capture(req, *a, **k):
            captured["url"] = req.full_url
            return _Response()

        wired.setattr(db.urllib.request, "urlopen", capture)
        db.select("tasks", {"select": "id"})
        assert SECRET not in captured["url"], "a key in the URL leaks into every log"


# ---------------------------------------------------------------------------
# Fail-soft behaviour
# ---------------------------------------------------------------------------
class TestFailSoft:
    def test_in_session_prompt_needs_no_database(self):
        task = {"slug": "test-task", "prompt": "Fix something", "id": "abc-123"}
        prompt = agentic_repair.in_session_prompt(task, "connection refused")
        assert "test-task" in prompt
        assert "connection refused" in prompt

    def test_repair_patch_needs_no_database(self):
        """An attempted task is requeued for repair, with the reason carried forward."""
        patch = agentic_repair.repair_patch(
            {"slug": "test-task", "prompt": "Fix something", "attempt": 2}, "timeout error")
        assert patch["state"] == "QUEUED"
        assert patch["remediation_count"] == 1
        assert "timeout error" in patch["prompt"]

    def test_a_never_attempted_task_is_requeued_not_counted_as_remediation(self):
        """Nothing ran, so there is nothing to have remediated — and no count to bump."""
        patch = agentic_repair.repair_patch(
            {"slug": "test-task", "prompt": "Fix something", "attempt": 0}, "timeout error")
        assert patch["state"] == "QUEUED"
        assert "remediation_count" not in patch
