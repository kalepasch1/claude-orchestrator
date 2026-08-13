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

Real HTTP against a real handler on an ephemeral port; only the store is injected.
"""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import config_store
import web_console


class FakeStore:
    def __init__(self, rows):
        self.rows = dict(rows)

    def get_config(self, key):
        return self.rows.get(key)

    def get_all(self):
        return list(self.rows.values())

    def update_config(self, key, value, note=None, updated_by=None):
        old = self.rows.get(key)
        self.rows[key] = {"key": key, "value": value}
        return old, self.rows[key]


STORE = FakeStore({
    "ORCH_MAX_PARALLEL": {"key": "ORCH_MAX_PARALLEL", "value": "8"},
    "GITHUB_PAT": {"key": "GITHUB_PAT", "value": "ghp_" + "a" * 30},
})


class TestConsoleConfigRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), web_console.ConsoleHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def _put(self, path, body):
        url = f"http://127.0.0.1:{self.port}{path}"
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="PUT",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def test_list_is_served(self):
        with patch.object(config_store, "get_store", return_value=STORE):
            status, body = self._get("/config")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 2)

    def test_single_key_is_served(self):
        with patch.object(config_store, "get_store", return_value=STORE):
            status, body = self._get("/config/ORCH_MAX_PARALLEL")
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["value"], "8")

    def test_missing_key_is_404(self):
        with patch.object(config_store, "get_store", return_value=STORE):
            status, _body = self._get("/config/NOPE")
        self.assertEqual(status, 404)

    def test_credentials_are_redacted_over_the_wire(self):
        # The console is the new egress path for pre-guard plaintext residue; the
        # redaction must survive serialization, not just exist in the library.
        with patch.object(config_store, "get_store", return_value=STORE):
            status, body = self._get("/config/GITHUB_PAT")
        self.assertEqual(status, 200)
        self.assertTrue(body["config"]["redacted"])
        self.assertNotIn("ghp_", json.dumps(body))

    def test_query_string_does_not_break_key_parsing(self):
        with patch.object(config_store, "get_store", return_value=STORE):
            status, body = self._get("/config/ORCH_MAX_PARALLEL?pretty=1")
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["key"], "ORCH_MAX_PARALLEL")

    def test_writes_are_refused_with_405_and_a_reason(self):
        status, body = self._put("/config/ORCH_MAX_PARALLEL", {"value": "99"})
        self.assertEqual(status, 405)
        self.assertIn("reason", body)
        self.assertEqual(body["allowed"], ["GET"])

    def test_a_refused_write_did_not_reach_the_store(self):
        before = dict(STORE.rows["ORCH_MAX_PARALLEL"])
        self._put("/config/ORCH_MAX_PARALLEL", {"value": "99"})
        self.assertEqual(STORE.rows["ORCH_MAX_PARALLEL"], before)

    def test_unrelated_routes_are_untouched(self):
        status, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_unknown_put_path_is_still_404(self):
        status, _body = self._put("/nope", {})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
