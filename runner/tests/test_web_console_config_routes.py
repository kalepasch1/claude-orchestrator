#!/usr/bin/env python3
"""The config REST layer, mounted on the web console.

Slice 2 of the configuration work: `config_api` deliberately owns no transport, so until
something mounts it the endpoints exist only as a library. This mounts the READ half on
the existing console, mirroring how `/compliance/v1/` is dispatched to
`compliance_api_gateway.gateway.dispatch` a few lines above it.

The write half is deliberately absent and these tests pin that too. The console binds
127.0.0.1 with no authentication on its own routes, so mounting PUT would let any local
process rewrite fleet configuration — the compliance routes carry `compliance_auth`
exactly because they mutate. A 405 that names the reason is the honest interim answer.

TRANSPORT (rewritten 2026-08-24). This file used to stand a real `HTTPServer` on an
ephemeral port and drive it with `urllib.request`, and every test in it failed: the
suite's hermetic guard in runner/tests/conftest.py refuses AF_INET `connect()` and points
child/proxy traffic at the discard port, so the requests never reached the server that
was running inside the same process. Marking the class `allow_network` would have been a
lie about coverage — nothing here needs a socket. The requests are now fed to a real
`ConsoleHandler` over in-memory byte streams, so `do_GET`/`do_PUT`, the request-line and
header parsing, the body drain, the status line and the JSON body are all still the real
ones; only the kernel is out of the loop.
"""
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import config_store
import web_console


class FakeStore:
    """A ConfigStore stand-in that also records every write attempt."""

    def __init__(self, rows):
        self.rows = dict(rows)
        self.writes = []

    def get_config(self, key):
        return self.rows.get(key)

    def get_all(self):
        return list(self.rows.values())

    def update_config(self, key, value, note=None, updated_by=None):
        self.writes.append((key, value))
        old = self.rows.get(key)
        self.rows[key] = {"key": key, "value": value}
        return old, self.rows[key]


def _fresh_store():
    return FakeStore({
        "ORCH_MAX_PARALLEL": {"key": "ORCH_MAX_PARALLEL", "value": "8"},
        "GITHUB_PAT": {"key": "GITHUB_PAT", "value": "ghp_" + "a" * 30},
    })


class _OfflineHandler(web_console.ConsoleHandler):
    """A real ConsoleHandler wired to BytesIO instead of a socket.

    BaseHTTPRequestHandler.__init__ is skipped on purpose — it is the half that owns the
    connection. Everything below it (parse_request, do_GET/do_PUT, send_response,
    end_headers, wfile writes) runs exactly as it does in production.
    """

    def __init__(self, raw_request):
        self.rfile = io.BytesIO(raw_request)
        self.wfile = io.BytesIO()
        self.connection = None
        self.server = None
        self.client_address = ("127.0.0.1", 54321)
        self.handle_one_request()


def _request(method, path, body=None, headers=None):
    """Drive one request through the handler; return (status, parsed JSON body)."""
    payload = b"" if body is None else json.dumps(body).encode()
    lines = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1"]
    if body is not None:
        lines += ["Content-Type: application/json", f"Content-Length: {len(payload)}"]
    for name, value in (headers or {}).items():
        lines.append(f"{name}: {value}")
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode() + payload

    handler = _OfflineHandler(raw)
    head, _, wire_body = handler.wfile.getvalue().partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n")[0].split()[1])
    return status, json.loads(wire_body.decode()), handler


class TestConsoleConfigRoutes(unittest.TestCase):
    def setUp(self):
        self.store = _fresh_store()

    def _get(self, path):
        status, body, _handler = _request("GET", path)
        return status, body

    def _put(self, path, body):
        status, payload, handler = _request("PUT", path, body)
        return status, payload, handler

    def test_list_is_served(self):
        with patch.object(config_store, "get_store", return_value=self.store):
            status, body = self._get("/config")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 2)

    def test_single_key_is_served(self):
        with patch.object(config_store, "get_store", return_value=self.store):
            status, body = self._get("/config/ORCH_MAX_PARALLEL")
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["value"], "8")

    def test_missing_key_is_404(self):
        with patch.object(config_store, "get_store", return_value=self.store):
            status, _body = self._get("/config/NOPE")
        self.assertEqual(status, 404)

    def test_credentials_are_redacted_over_the_wire(self):
        # The console is the new egress path for pre-guard plaintext residue; the
        # redaction must survive serialization, not just exist in the library.
        with patch.object(config_store, "get_store", return_value=self.store):
            status, body = self._get("/config/GITHUB_PAT")
        self.assertEqual(status, 200)
        self.assertTrue(body["config"]["redacted"])
        self.assertNotIn("ghp_", json.dumps(body))

    def test_query_string_does_not_break_key_parsing(self):
        with patch.object(config_store, "get_store", return_value=self.store):
            status, body = self._get("/config/ORCH_MAX_PARALLEL?pretty=1")
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["key"], "ORCH_MAX_PARALLEL")

    def test_writes_are_refused_with_405_and_a_reason(self):
        status, body, _handler = self._put("/config/ORCH_MAX_PARALLEL", {"value": "99"})
        self.assertEqual(status, 405)
        self.assertIn("reason", body)
        self.assertEqual(body["allowed"], ["GET"])

    def test_a_refused_write_did_not_reach_the_store(self):
        # Was: snapshot a dict on the fake store and assert it is unchanged — which held
        # trivially, because no store was injected for the PUT at all. Now the store IS
        # injected for the duration of the request and records every update_config call,
        # so the assertion fails the moment a write path is mounted without auth.
        with patch.object(config_store, "get_store", return_value=self.store):
            self._put("/config/ORCH_MAX_PARALLEL", {"value": "99"})
        self.assertEqual(self.store.writes, [])
        self.assertEqual(self.store.rows["ORCH_MAX_PARALLEL"]["value"], "8")

    def test_refused_write_drains_its_body_before_answering(self):
        # Replying while the request body is still in flight makes the peer see a reset
        # instead of the 405; do_PUT drains it first. Checks the handler consumed the
        # declared bytes rather than leaving them in the stream.
        _status, _body, handler = self._put("/config/ORCH_MAX_PARALLEL", {"value": "99"})
        self.assertEqual(handler.rfile.read(), b"")

    def test_unrelated_routes_are_untouched(self):
        status, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_unknown_put_path_is_still_404(self):
        status, _body, _handler = self._put("/nope", {})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
