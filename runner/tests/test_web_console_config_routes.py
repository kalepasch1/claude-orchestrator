#!/usr/bin/env python3
"""The config REST layer, mounted on the web console.

`config_api` deliberately owns no transport, so until something mounts it the endpoints
exist only as a library. This mounts them on the existing console, mirroring how
`/compliance/v1/` is dispatched to `compliance_api_gateway.gateway.dispatch` a few lines
above it.

TWO THINGS CHANGED HERE, both deliberately.

1. WRITES ARE NOW MOUNTED. The previous slice answered 405 and these tests pinned that,
   with the reason: the console binds 127.0.0.1 with no auth on its own routes, so an
   unguarded PUT would let any local process rewrite fleet configuration. Slice 2 mounts
   the write path together with the authentication, so the 405 assertions are replaced by
   assertions that an UNAUTHENTICATED write is refused — the property that actually
   mattered. The auth behaviour itself is pinned in test_web_console_config_write.py.

2. NO REAL SOCKET. This suite used to stand up an HTTPServer on an ephemeral port and
   drive it with urllib. The hermetic test guard blocks that, so ALL NINE tests had been
   failing on master — silently, since a red suite in a repo with other red suites reads
   as background noise. The handler is now driven in-process with stubbed rfile/response,
   which tests exactly the same dispatch logic without depending on a socket.
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


def _store():
    return FakeStore({
        "ORCH_MAX_PARALLEL": {"key": "ORCH_MAX_PARALLEL", "value": "8"},
        "GITHUB_PAT": {"key": "GITHUB_PAT", "value": "ghp_" + "a" * 30},
    })


class _Handler(web_console.ConsoleHandler):
    """The real handler, with transport stubbed out. No socket, no server."""

    def __init__(self, path, body=b"", headers=None):
        self.path = path
        self.rfile = io.BytesIO(body)
        self.headers = dict(headers or {})
        self.headers.setdefault("Content-Length", str(len(body)))
        self.client_address = ("127.0.0.1", 5555)
        self.close_connection = False
        self.sent = []

    def _send_json(self, status, payload, extra_headers=None):
        # Round-trip through JSON: a redaction that only exists in the library and not on
        # the wire is not a redaction, and that is the whole point of one of these tests.
        self.sent.append((status, json.loads(json.dumps(payload, default=str))))
        return None


class TestConsoleConfigRoutes(unittest.TestCase):
    def setUp(self):
        self.store = _store()
        # No token adapter configured: this is the default posture, and the one under
        # which an unauthenticated write must be refused.
        self._saved = os.environ.pop("ORCH_COMPLIANCE_API_TOKENS", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["ORCH_COMPLIANCE_API_TOKENS"] = self._saved

    def _get(self, path):
        handler = _Handler(path)
        with patch.object(config_store, "get_store", return_value=self.store):
            handler.do_GET()
        return handler.sent[0]

    def _put(self, path, body):
        handler = _Handler(path, json.dumps(body).encode())
        with patch.object(config_store, "get_store", return_value=self.store):
            handler.do_PUT()
        return handler.sent[0]

    def test_list_is_served(self):
        status, body = self._get("/config")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 2)

    def test_single_key_is_served(self):
        status, body = self._get("/config/ORCH_MAX_PARALLEL")
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["value"], "8")

    def test_missing_key_is_404(self):
        status, _body = self._get("/config/NOPE")
        self.assertEqual(status, 404)

    def test_credentials_are_redacted_over_the_wire(self):
        # The console is the new egress path for pre-guard plaintext residue; the
        # redaction must survive serialization, not just exist in the library.
        status, body = self._get("/config/GITHUB_PAT")
        self.assertEqual(status, 200)
        self.assertTrue(body["config"]["redacted"])
        self.assertNotIn("ghp_", json.dumps(body))

    def test_query_string_does_not_break_key_parsing(self):
        status, body = self._get("/config/ORCH_MAX_PARALLEL?pretty=1")
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["key"], "ORCH_MAX_PARALLEL")

    def test_unauthenticated_writes_are_refused_with_a_reason(self):
        """Replaces the old 405 assertion. Writes are mounted now; what must hold is
        that loopback alone cannot rewrite fleet configuration."""
        status, body = self._put("/config/ORCH_MAX_PARALLEL", {"value": "99"})
        self.assertEqual(status, 403)
        self.assertIn("error", body)
        self.assertIn("ORCH_COMPLIANCE_API_TOKENS", body["error"])

    def test_a_refused_write_did_not_reach_the_store(self):
        before = dict(self.store.rows["ORCH_MAX_PARALLEL"])
        self._put("/config/ORCH_MAX_PARALLEL", {"value": "99"})
        self.assertEqual(self.store.rows["ORCH_MAX_PARALLEL"], before)

    def test_unrelated_routes_are_untouched(self):
        status, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_unknown_put_path_is_still_404(self):
        status, _body = self._put("/nope", {})
        self.assertEqual(status, 404)

    def test_the_suite_needs_no_network(self):
        """Guard the fix: if someone reintroduces a real server here, the hermetic guard
        will fail the whole suite again and this test explains why.

        Checked over the AST rather than the raw text — a substring search matches its
        own assertion literal, which is how a guard like this quietly becomes a tautology.
        """
        import ast
        with open(__file__, encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add((node.module or "").split(".")[0])
        for networked in ("urllib", "http", "socket", "requests", "threading"):
            self.assertNotIn(networked, imported,
                             f"{networked} is back; this suite must stay hermetic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
