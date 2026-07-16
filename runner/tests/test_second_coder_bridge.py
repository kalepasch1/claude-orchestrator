#!/usr/bin/env python3
"""Tests for second_coder_bridge.py -- remote coder bridge for Mac #2."""
import json, os, sys, threading, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import second_coder_bridge as bridge


# ---------------------------------------------------------------------------
# Fake remote coder HTTP server
# ---------------------------------------------------------------------------

class _FakeCoderHandler(BaseHTTPRequestHandler):
    """Minimal mock of the remote coder HTTP API."""

    # class-level state shared across requests
    jobs = {}

    def log_message(self, *a):
        pass  # silence logs during tests

    def do_GET(self):
        if self.path == "/health":
            self._json({"ok": True, "name": "fake-mac2", "capabilities": {"cap": 5}})
        elif self.path.startswith("/status/"):
            job_id = self.path.split("/status/")[1]
            job = self.jobs.get(job_id, {})
            self._json({"status": job.get("status", "running"), "result": job.get("result")})
        elif self.path.startswith("/result/"):
            job_id = self.path.split("/result/")[1]
            job = self.jobs.get(job_id, {})
            self._json(job.get("result") or {"text": "done", "commit": "abc123",
                        "diff_stats": "+10 -2", "test_results": {"passed": 3},
                        "cost_usd": 0.0, "returncode": 0})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if self.path == "/dispatch":
            job_id = body.get("job_id", "test-job")
            self.jobs[job_id] = {"status": "running", "result": None}
            self._json({"status": "accepted", "job_id": job_id})
        else:
            self.send_error(404)

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


@pytest.fixture(autouse=True)
def _clean_bridge():
    """Reset module singletons between tests."""
    bridge._registry.clear()
    bridge._jobs.clear()
    for k in bridge._stats:
        bridge._stats[k] = 0
    _FakeCoderHandler.jobs = {}
    yield
    bridge._registry.clear()
    bridge._jobs.clear()


@pytest.fixture(scope="module")
def fake_server():
    """Start a fake coder HTTP server on a random port for the test module."""
    server = HTTPServer(("127.0.0.1", 0), _FakeCoderHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield ("127.0.0.1", port)
    server.shutdown()


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
        status = bridge.pool_status()
        assert "mac2" in status["remote"]
        assert status["remote"]["mac2"]["free_slots"] == bridge._MAX_CONCURRENT
        assert "local" in status


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
