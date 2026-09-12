#!/usr/bin/env python3
"""config_api_wsgi.py - the HTTP transport that mounts `config_api`.

`config_api` deliberately owns routing and the request/response contract and nothing
else. This module is the other half named in its docstring: it turns a WSGI environ
into a `dispatch()` call and a JSON response, and it owns the three concerns that only
exist once a socket is involved.

SECURITY
--------
* **The bearer token is read from the host environment, never from fleet_config.**
  That table is exactly what this API serves; sourcing the credential that guards it
  from the thing it guards would put a live secret back into the table the 2026-08-02
  incident purged. `ORCH_CONFIG_API_TOKEN` is a host env var and stays one.
* **Fail-closed on the mutating verbs.** No token configured means every PUT is
  refused with 503, not waved through. An unauthenticated write path to fleet-wide
  config is a fleet-wide remote code path.
* **Constant-time comparison** on the token, so response timing does not leak it.
* **Reads can be gated too** (`ORCH_CONFIG_API_REQUIRE_AUTH_READS`), off by default
  because `config_api` already redacts every credential-shaped value on the way out.
* **No internals in an error body.** An unexpected exception becomes a bare 500; the
  traceback goes to the server log where it belongs, not to the client.

ERROR HANDLING
--------------
Every failure is a JSON body with an `error` key, the same shape `config_api` returns,
so a client never has to branch on whether the transport or the handler refused it.
Fail-soft at the boundary: this app does not raise into the server.

PERFORMANCE
-----------
* Request bodies are capped (`ORCH_CONFIG_API_MAX_BODY`, 64 KiB) and read against the
  declared Content-Length, so an unbounded or lying body cannot exhaust memory.
* The store is the module-level singleton from `config_store`, so a request does not
  build a new DAO.
* Responses carry Content-Length and `Cache-Control: no-store` — config reads are
  cheap and staleness here is an operational hazard, not a saving.

Usage:
    from wsgiref.simple_server import make_server
    import config_api_wsgi
    make_server("127.0.0.1", 8099, config_api_wsgi.app).serve_forever()
"""
import hmac
import json
import os
import sys
import traceback
import urllib.parse
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config_api

# Verbs that change fleet-wide state. Everything here is authenticated fail-closed.
MUTATING_METHODS = frozenset({"PUT", "POST", "PATCH", "DELETE"})

MAX_BODY_BYTES = int(os.environ.get("ORCH_CONFIG_API_MAX_BODY", str(64 * 1024)))
REQUIRE_AUTH_READS = os.environ.get(
    "ORCH_CONFIG_API_REQUIRE_AUTH_READS", "false"
).lower() in ("1", "true", "yes")

_JSON = [("Content-Type", "application/json; charset=utf-8"),
         ("Cache-Control", "no-store"),
         ("X-Content-Type-Options", "nosniff")]


def _token() -> str:
    """The API bearer token, from the host environment only.

    Read per call rather than cached at import so an operator can rotate it without a
    restart, and so tests can set it with monkeypatch.
    """
    return os.environ.get("ORCH_CONFIG_API_TOKEN", "") or ""


def _authenticate(environ: Dict[str, Any], method: str) -> Optional[config_api.Response]:
    """Return an error response if the request must be refused, else None."""
    if method not in MUTATING_METHODS and not REQUIRE_AUTH_READS:
        return None

    expected = _token()
    if not expected:
        # Fail-closed. A missing token is a misconfigured deployment, and the honest
        # answer is "this endpoint is not available", not "help yourself".
        return 503, {"error": "config API is not configured for writes: "
                              "ORCH_CONFIG_API_TOKEN is unset on this host"}

    header = environ.get("HTTP_AUTHORIZATION", "") or ""
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return 401, {"error": "missing or malformed Authorization header",
                     "expected": "Authorization: Bearer <token>"}
    if not hmac.compare_digest(presented.strip(), expected):
        return 403, {"error": "invalid token"}
    return None


def _read_body(environ: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]],
                                                 Optional[config_api.Response]]:
    """Read and parse a JSON body. Returns (body, error_response)."""
    raw_len = environ.get("CONTENT_LENGTH", "") or "0"
    try:
        declared = int(raw_len)
    except (TypeError, ValueError):
        return None, (400, {"error": "invalid Content-Length"})
    if declared < 0:
        return None, (400, {"error": "invalid Content-Length"})
    if declared > MAX_BODY_BYTES:
        return None, (413, {"error": "request body too large",
                            "max_bytes": MAX_BODY_BYTES})
    if declared == 0:
        return None, None

    stream = environ.get("wsgi.input")
    if stream is None:
        return None, (400, {"error": "no request body"})
    # Read one byte past the cap so a lying Content-Length is caught rather than
    # trusted; never read to EOF on an untrusted stream.
    data = stream.read(min(declared, MAX_BODY_BYTES) + 1)
    if len(data) > MAX_BODY_BYTES:
        return None, (413, {"error": "request body too large",
                            "max_bytes": MAX_BODY_BYTES})
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, (400, {"error": "body must be valid UTF-8 JSON"})
    if not isinstance(parsed, dict):
        return None, (400, {"error": "body must be a JSON object"})
    return parsed, None


def handle(environ: Dict[str, Any], store=None) -> config_api.Response:
    """Turn one WSGI environ into a (status, body) pair. Never raises."""
    try:
        method = (environ.get("REQUEST_METHOD") or "").upper()
        path = environ.get("PATH_INFO") or "/config"
        query = {
            k: v[-1]
            for k, v in urllib.parse.parse_qs(environ.get("QUERY_STRING") or "").items()
        }

        refusal = _authenticate(environ, method)
        if refusal:
            return refusal

        body = None
        if method in MUTATING_METHODS:
            body, err = _read_body(environ)
            if err:
                return err

        return config_api.dispatch(method, path, body=body, store=store, query=query)
    except Exception:
        # Broad by convention (fail-soft), but never silent, and never leaked: the
        # traceback goes to the server log, the client gets a bare 500.
        traceback.print_exc(file=environ.get("wsgi.errors", sys.stderr))
        return 500, {"error": "internal error"}


_STATUS_TEXT = {
    200: "200 OK", 201: "201 Created", 400: "400 Bad Request",
    401: "401 Unauthorized", 403: "403 Forbidden", 404: "404 Not Found",
    405: "405 Method Not Allowed", 413: "413 Payload Too Large",
    422: "422 Unprocessable Entity", 500: "500 Internal Server Error",
    503: "503 Service Unavailable",
}


def app(environ, start_response):
    """WSGI entry point."""
    status, body = handle(environ)
    payload = json.dumps(body, default=str).encode("utf-8")
    headers = list(_JSON) + [("Content-Length", str(len(payload)))]
    if status == 401:
        headers.append(("WWW-Authenticate", 'Bearer realm="fleet-config"'))
    if status == 405 and isinstance(body, dict) and body.get("allowed"):
        headers.append(("Allow", ", ".join(body["allowed"])))
    start_response(_STATUS_TEXT.get(status, f"{status} Error"), headers)
    return [payload]


def serve(host: str = "127.0.0.1", port: int = 0):
    """Bind a stdlib WSGI server. Loopback by default — this is an operator endpoint.

    Returns the server so a caller (or a test) owns its lifetime.
    """
    from wsgiref.simple_server import make_server

    return make_server(host, port, app)


if __name__ == "__main__":
    _port = int(os.environ.get("ORCH_CONFIG_API_PORT", "8099"))
    _srv = serve(os.environ.get("ORCH_CONFIG_API_HOST", "127.0.0.1"), _port)
    sys.stderr.write(f"config_api_wsgi listening on {_srv.server_address}\n")
    _srv.serve_forever()
