#!/usr/bin/env python3
"""Tests for second_coder_bridge.py -- remote coder bridge for Mac #2.

TRANSPORT. This file used to stand a real HTTPServer on an ephemeral port and
drive it with the bridge's own urllib client. Six of its eighteen tests failed:
the suite's hermetic guard in runner/tests/conftest.py refuses AF_INET
connect(), so the requests never reached the server running inside the same
process.

Marking the class allow_network would have been a lie about coverage — the same
call runner/tests/test_web_console_config_routes.py made when it hit this guard.
Nothing here needs a socket. What is under test is the CLIENT: which URL each
call builds, what body it sends, how it parses the reply, and how the registry,
job table and counters move as a result. (Contrast test_fleet_control's
WebSocket class, which is marked allow_network because half-open connection
detection genuinely has no in-memory equivalent.)

So urlopen is replaced with an in-process router carrying the same routes the
fake handler had. urllib.request.Request construction, the Content-Type header,
the request body and `json.loads(resp.read().decode())` are all still the real
ones; only the kernel is out of the loop. An address other than the fake
coder's raises URLError, which is what an unreachable host does — so
test_register_unreachable still exercises the failure path rather than relying
on the guard to produce it.
"""
import json, os, sys
import urllib.error
import urllib.parse
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import second_coder_bridge as bridge


# ---------------------------------------------------------------------------
# In-process stand-in for the remote coder HTTP API
# ---------------------------------------------------------------------------

class _Response:
    """The slice of an http.client.HTTPResponse that _http() actually uses."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeCoder:
    """Routes the remote coder's endpoints. `jobs` is the server-side state."""

    jobs = {}
    address = ("127.0.0.1", 8765)

    @classmethod
    def urlopen(cls, req, timeout=None):
        parsed = urllib.parse.urlparse(req.full_url)
        if (parsed.hostname, parsed.port) != cls.address:
            # What an unreachable host really does, so the bridge's own
            # except-arm is what turns it into "unhealthy".
            raise urllib.error.URLError("connection refused")

        path = parsed.path
        body = json.loads(req.data.decode()) if req.data else {}

        if req.data:
            if path == "/dispatch":
                job_id = body.get("job_id", "test-job")
                cls.jobs[job_id] = {"status": "running", "result": None}
                return _Response({"status": "accepted", "job_id": job_id})
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

        if path == "/health":
            return _Response({"ok": True, "name": "fake-mac2",
                              "capabilities": {"cap": 5}})
        if path.startswith("/status/"):
            job = cls.jobs.get(path.split("/status/", 1)[1], {})
            return _Response({"status": job.get("status", "running"),
                              "result": job.get("result")})
        if path.startswith("/result/"):
            job = cls.jobs.get(path.split("/result/", 1)[1], {})
            return _Response(job.get("result") or {
                "text": "done", "commit": "abc123", "diff_stats": "+10 -2",
                "test_results": {"passed": 3}, "cost_usd": 0.0, "returncode": 0})
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)


#: Kept under its old name so the test bodies below still read as "server state".
_FakeCoderHandler = _FakeCoder


@pytest.fixture(autouse=True)
def _clean_bridge():
    """Reset module singletons between tests."""
    bridge._registry.clear()
    bridge._jobs.clear()
    for k in bridge._stats:
        bridge._stats[k] = 0
    _FakeCoder.jobs = {}
    yield
    bridge._registry.clear()
    bridge._jobs.clear()


@pytest.fixture
def fake_server():
    """Route the bridge's HTTP calls in-process, and hand back its address."""
    with mock.patch("urllib.request.urlopen", _FakeCoder.urlopen):
        yield _FakeCoder.address


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_healthy(self, fake_server):
        host, port = fake_server
        ok = bridge.register_remote_coder("mac2", host, port, {"cap": 5})
        assert ok is True
        assert "mac2" in bridge._registry
        assert bridge._registry["mac2"]["healthy"] is True

    def test_register_unreachable(self):
        ok = bridge.register_remote_coder("ghost", "192.0.2.1", 1, {})
        assert ok is False
        assert bridge._registry["ghost"]["healthy"] is False


class TestDiscover:
    def test_discover_finds_server(self, fake_server):
        host, port = fake_server
        with mock.patch.dict(os.environ, {"ORCH_REMOTE_CODER_HOSTS": f"{host}:{port}"}):
            found = bridge.discover()
        assert len(found) == 1
        assert found[0]["name"] == "fake-mac2"
        assert bridge._stats["discovery_runs"] == 1

    def test_discover_empty_env(self):
        with mock.patch.dict(os.environ, {"ORCH_REMOTE_CODER_HOSTS": ""}):
            found = bridge.discover()
        assert found == []


class TestIsAvailable:
    def test_available_when_healthy(self, fake_server):
        host, port = fake_server
        bridge.register_remote_coder("mac2", host, port, {})
        assert bridge.is_available("mac2") is True

    def test_not_available_unknown(self):
        assert bridge.is_available("nope") is False

    def test_not_available_at_capacity(self, fake_server):
        host, port = fake_server
        bridge.register_remote_coder("mac2", host, port, {})
        bridge._registry["mac2"]["jobs_active"] = bridge._MAX_CONCURRENT
        assert bridge.is_available("mac2") is False


class TestDispatchAndPoll:
    def test_dispatch_success(self, fake_server):
        host, port = fake_server
        bridge.register_remote_coder("mac2", host, port, {})
        task = {"slug": "fix-bug", "description": "fix the thing", "prompt": "fix it"}
        result = bridge.dispatch(task, "mac2")
        assert result["status"] == "dispatched"
        assert result["job_id"] is not None
        assert result["branch"] == "agent/fix-bug-remote"
        assert bridge._stats["dispatched"] == 1

    def test_dispatch_unknown_coder(self):
        result = bridge.dispatch({"slug": "x"}, "nobody")
        assert result["status"] == "error"

    def test_poll_unknown_job(self):
        result = bridge.poll_result("no-such-id")
        assert result["status"] == "unknown"

    def test_poll_running_then_done(self, fake_server):
        host, port = fake_server
        bridge.register_remote_coder("mac2", host, port, {})
        task = {"slug": "t", "prompt": "do it"}
        handle = bridge.dispatch(task, "mac2")
        job_id = handle["job_id"]

        # Initially running
        poll = bridge.poll_result(job_id)
        assert poll["status"] == "running"

        # Mark done on the fake server
        _FakeCoderHandler.jobs[job_id] = {
            "status": "done",
            "result": {"text": "fixed", "commit": "def456", "cost_usd": 0.0},
        }
        poll = bridge.poll_result(job_id)
        assert poll["status"] == "done"
        assert bridge._stats["completed"] == 1


class TestCollectResult:
    def test_collect_done_job(self, fake_server):
        host, port = fake_server
        bridge.register_remote_coder("mac2", host, port, {})
        task = {"slug": "feat", "prompt": "add feature"}
        handle = bridge.dispatch(task, "mac2")
        job_id = handle["job_id"]

        # Mark done
        _FakeCoderHandler.jobs[job_id] = {
            "status": "done",
            "result": {"text": "done", "commit": "abc123", "diff_stats": "+5 -1",
                       "test_results": {"passed": 2}, "cost_usd": 0.0, "returncode": 0},
        }
        bridge.poll_result(job_id)  # update local status

        result = bridge.collect_result(job_id)
        assert result["status"] == "done"
        assert result["commit"] == "abc123"
        assert result["remote"] is True
        assert result["coder"] == "mac2"
        assert result["branch"] == "agent/feat-remote"

    def test_collect_unknown_job(self):
        result = bridge.collect_result("nope")
        assert result["status"] == "error"


class TestPoolStatus:
    def test_includes_remote(self, fake_server):
        host, port = fake_server
        bridge.register_remote_coder("mac2", host, port, {"cap": 5})
        # pool_status() calls agentic_coders.available(), which probes the local
        # coder CLIs with subprocesses — 8.5 of this file's 9.5 seconds, for a
        # value this test only asserts the presence of. The remote half is what
        # is under test.
        import agentic_coders
        with mock.patch.object(agentic_coders, "available", return_value=["local-1"]):
            status = bridge.pool_status()
        assert "mac2" in status["remote"]
        assert status["remote"]["mac2"]["free_slots"] == bridge._MAX_CONCURRENT
        assert status["local"] == ["local-1"]

    def test_free_slots_shrink_as_jobs_are_taken(self, fake_server):
        host, port = fake_server
        bridge.register_remote_coder("mac2", host, port, {})
        bridge._registry["mac2"]["jobs_active"] = 1
        import agentic_coders
        with mock.patch.object(agentic_coders, "available", return_value=[]):
            status = bridge.pool_status()
        assert status["remote"]["mac2"]["free_slots"] == bridge._MAX_CONCURRENT - 1
        assert status["total_remote_busy"] == 1

    def test_a_local_coder_probe_failure_does_not_break_the_status(self):
        """The local half is best-effort; the remote half must still report."""
        import agentic_coders
        with mock.patch.object(agentic_coders, "available",
                               side_effect=RuntimeError("no CLI")):
            status = bridge.pool_status()
        assert status["local"] == []
        assert status["remote"] == {}


class TestStats:
    def test_stats_shape(self):
        s = bridge.stats()
        assert "dispatched" in s
        assert "completed" in s
        assert "failed" in s
        assert "registered_coders" in s
        assert "healthy_coders" in s
        assert "active_jobs" in s


class TestParseHosts:
    def test_parse_multiple(self):
        with mock.patch.dict(os.environ, {"ORCH_REMOTE_CODER_HOSTS": "10.0.0.1:8000, 10.0.0.2:9000"}):
            pairs = bridge._parse_hosts()
        assert pairs == [("10.0.0.1", 8000), ("10.0.0.2", 9000)]

    def test_default_port(self):
        with mock.patch.dict(os.environ, {"ORCH_REMOTE_CODER_HOSTS": "myhost"}):
            pairs = bridge._parse_hosts()
        assert pairs == [("myhost", 7819)]

    def test_empty(self):
        with mock.patch.dict(os.environ, {"ORCH_REMOTE_CODER_HOSTS": ""}):
            assert bridge._parse_hosts() == []
