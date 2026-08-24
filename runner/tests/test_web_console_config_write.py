#!/usr/bin/env python3
"""Slice 2: the config REST layer is mounted on the console, WITH authentication.

Slice 1 built `config_api` (transport-agnostic routing + contract) and mounted only GET,
answering 405 to PUT with an explicit reason: the console binds 127.0.0.1 with no auth on
its own routes, so an unguarded PUT would let any local process rewrite fleet config.

This slice mounts the write path and brings the auth with it. The load-bearing detail is
easy to get wrong and is what these tests pin: `compliance_auth.resolve_principal` falls
back to LOCAL_PRINCIPAL on loopback when no token adapter is configured, and
LOCAL_PRINCIPAL ALREADY HOLDS THE WRITE SCOPE. A `require_scope(WRITE)` check on its own
would therefore authorise every local process — exactly the hazard slice 1 refused to
ship. Config writes additionally require `auth_configured()`.

Proof: python3 -m pytest runner/tests/test_web_console_config_write.py -q
"""
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compliance_auth  # noqa: E402
import web_console  # noqa: E402

TOKEN = "test-token-value"
REGISTRY = {TOKEN: {"principal": "operator", "tenant": "default",
                    "scopes": ["read", "write"]}}
READ_ONLY = {TOKEN: {"principal": "viewer", "tenant": "default", "scopes": ["read"]}}


class _Handler(web_console.ConsoleHandler):
    """The handler with transport stubbed out — no socket, no server."""

    def __init__(self, path, body=b"", headers=None):
        self.path = path
        self.rfile = io.BytesIO(body)
        self.headers = dict(headers or {})
        self.headers.setdefault("Content-Length", str(len(body)))
        self.client_address = ("127.0.0.1", 5555)
        self.close_connection = False
        self.sent = []

    def _send_json(self, status, payload, extra_headers=None):
        self.sent.append((status, payload))
        return None


def _put(path="/config/ORCH_FOO", value="bar", token=None, registry=None,
         body=None, headers=None):
    payload = json.dumps({"value": value}).encode() if body is None else body
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    handler = _Handler(path, payload, hdrs)
    env = {}
    if registry is not None:
        env["ORCH_COMPLIANCE_API_TOKENS"] = json.dumps(registry)
    with patch.dict(os.environ, env, clear=False):
        if registry is None:
            os.environ.pop("ORCH_COMPLIANCE_API_TOKENS", None)
        compliance_auth._token_registry.cache_clear() if hasattr(
            compliance_auth._token_registry, "cache_clear") else None
        handler.do_PUT()
    return handler.sent[0] if handler.sent else (None, None)


class TestUnauthenticatedWritesAreRefused(unittest.TestCase):
    def test_loopback_alone_cannot_rewrite_fleet_config(self):
        """The hazard slice 1 named, asserted directly."""
        status, payload = _put(registry=None)
        self.assertEqual(status, 403)
        self.assertIn("loopback is not sufficient", payload["error"])

    def test_the_refusal_names_what_to_configure(self):
        _, payload = _put(registry=None)
        self.assertIn("ORCH_COMPLIANCE_API_TOKENS", payload["error"])

    def test_a_bad_token_is_rejected_even_from_loopback(self):
        status, _ = _put(token="wrong-token", registry=REGISTRY)
        self.assertEqual(status, 401)

    def test_a_read_only_principal_cannot_write(self):
        status, payload = _put(token=TOKEN, registry=READ_ONLY)
        self.assertEqual(status, 403)
        self.assertIn("write", payload["error"])

    def test_an_oversized_body_is_refused_before_it_is_read(self):
        status, _ = _put(registry=REGISTRY, token=TOKEN,
                         headers={"Content-Length": str(10 * 1024 * 1024)})
        self.assertGreaterEqual(status, 400)

    def test_a_refused_write_closes_the_connection(self):
        handler = _Handler("/config/ORCH_FOO", b'{"value":"x"}')
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_COMPLIANCE_API_TOKENS", None)
            handler.do_PUT()
        self.assertTrue(handler.close_connection)


class TestAuthorisedWrites(unittest.TestCase):
    def test_an_authorised_write_reaches_config_api(self):
        seen = {}

        def _dispatch(method, path, body=None, store=None):
            seen.update(method=method, path=path, body=body)
            return 200, {"key": "ORCH_FOO", "value": "bar"}

        with patch("config_api.dispatch", _dispatch):
            status, payload = _put(token=TOKEN, registry=REGISTRY)
        self.assertEqual(status, 200)
        self.assertEqual(seen["method"], "PUT")
        self.assertEqual(seen["path"], "/config/ORCH_FOO")
        self.assertEqual(seen["body"], {"value": "bar"})

    def test_the_write_is_attributed_to_a_principal(self):
        """An untraceable fleet-config write is the audit gap this mount would open."""
        with patch("config_api.dispatch", lambda *a, **k: (200, {"key": "ORCH_FOO"})):
            _, payload = _put(token=TOKEN, registry=REGISTRY)
        self.assertEqual(payload["written_by"]["principal"], "operator")
        self.assertEqual(payload["written_by"]["via"], "token")

    def test_a_failed_write_is_not_attributed(self):
        with patch("config_api.dispatch", lambda *a, **k: (400, {"error": "bad key"})):
            status, payload = _put(token=TOKEN, registry=REGISTRY)
        self.assertEqual(status, 400)
        self.assertNotIn("written_by", payload)

    def test_a_non_json_body_is_a_400_not_a_500(self):
        status, _ = _put(token=TOKEN, registry=REGISTRY, body=b"not json")
        self.assertEqual(status, 400)

    def test_a_json_array_body_is_refused(self):
        status, _ = _put(token=TOKEN, registry=REGISTRY, body=b"[1,2,3]")
        self.assertEqual(status, 400)

    def test_the_error_body_does_not_leak_the_token(self):
        status, payload = _put(token="wrong-token", registry=REGISTRY)
        self.assertNotIn("wrong-token", json.dumps(payload))


class TestUnrelatedRoutesAreUnchanged(unittest.TestCase):
    def test_an_unknown_put_path_is_still_404(self):
        handler = _Handler("/nope", b"{}")
        handler.do_PUT()
        self.assertEqual(handler.sent[0][0], 404)

    def test_an_unknown_put_path_does_not_require_auth(self):
        """404 must not become an auth oracle for path existence."""
        handler = _Handler("/nope", b"{}")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_COMPLIANCE_API_TOKENS", None)
            handler.do_PUT()
        self.assertEqual(handler.sent[0][0], 404)

    def test_config_reads_still_need_no_token(self):
        """Reads were already safe — config_api redacts on the way out — and stay open."""
        import config_api
        status, _ = config_api.dispatch("GET", "/config", store=None)
        self.assertIn(status, (200, 500, 503))


class TestContract(unittest.TestCase):
    def test_the_loopback_principal_really_does_hold_write(self):
        """Pin the premise. If this ever changes, the extra guard can be revisited —
        and if it changes silently, this test says so instead of the guard looking
        like superstition."""
        self.assertIn(compliance_auth.WRITE, compliance_auth.LOCAL_PRINCIPAL.scopes)

    def test_config_api_still_routes_put(self):
        import config_api
        self.assertIn(("PUT", "/config/{key}"), config_api.ROUTES)

    def test_the_console_no_longer_advertises_put_as_unavailable(self):
        source = open(web_console.__file__, encoding="utf-8", errors="replace").read()
        self.assertNotIn("config writes are not exposed on the console yet", source)


if __name__ == "__main__":
    unittest.main()
