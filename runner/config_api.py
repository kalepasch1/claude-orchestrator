#!/usr/bin/env python3
"""config_api.py - the RESTful layer over fleet configuration.

SCOPE (first independently mergeable slice). This is routing + the request/response
contract only: verb + path -> a `ConfigStore` operation -> a status code and a JSON-able
body. It binds to no web framework and opens no socket, exactly as `orchestration_api.py`
owns the task data contract while runner.py keeps owning execution. A later slice mounts
these handlers on a real server; nothing here changes when it does.

SLICE 2 (this patch) adds opt-in `?limit=&offset=` pagination to the collection read
and threads a query mapping through `dispatch`. The HTTP transport that mounts these
handlers is `config_api_wsgi.py`, added alongside; it owns authn on the mutating verbs,
body-size limits and error containment, and this module still opens no socket.

Later slices, deliberately NOT in this patch, so they stay discoverable:
  * PATCH/DELETE (both need a store-level delete that does not exist yet);
  * ETag/If-Match optimistic concurrency;
  * approval routing for guarded keys via config_approval_engine.

WHY THE GUARD RUNS ON READS TOO
-------------------------------
`fleet_config_guard` is enforced fail-closed on the *write* path (db.insert/upsert/update),
which is what stopped new credentials landing in the table after the 2026-08-02 incident
(four live plaintext credentials, GITHUB_PAT among them). It does nothing about rows that
predate the guard, and it never had to: until now nothing served that table over a network.

An HTTP GET is a brand-new egress path for exactly that residue, so every value leaving
through this layer is re-classified and redacted. The response still reports that the key
exists — hiding it would make a legacy secret look like a missing key and send an operator
hunting for it — but the material never crosses the boundary.
"""
import urllib.parse
from typing import Any, Dict, Optional, Tuple

import config_store
import fleet_config_guard

REDACTED = "[REDACTED: credential — read from the host env, not fleet_config]"

# Pagination bounds. Named rather than inlined so they are tunable without a code
# read, and so a caller cannot ask for an unbounded page by passing a huge integer.
MAX_LIST_LIMIT = 500
MAX_LIST_OFFSET = 1_000_000

# Response bodies are always dicts so a transport can json.dumps() unconditionally.
Response = Tuple[int, Dict[str, Any]]


def _redact(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a copy of `row` with a credential-shaped value replaced.

    Never mutates the caller's row: the same object is often the DAO's cached copy,
    and redacting in place would corrupt config for every in-process consumer.
    """
    if not isinstance(row, dict):
        return row
    secret, reason = fleet_config_guard.classify(row.get("key"), row.get("value"))
    if not secret:
        return dict(row)
    safe = dict(row)
    safe["value"] = REDACTED
    safe["redacted"] = True
    # `reason` is documented to never contain any part of the value.
    safe["redaction_reason"] = reason
    return safe


def get_config(key: str, store=None) -> Response:
    """GET /config/{key} -> 200 with the row, or 404."""
    if not key or not str(key).strip():
        return 400, {"error": "key is required"}
    store = store or config_store.get_store()
    row = store.get_config(key)
    if row is None:
        return 404, {"error": "not found", "key": key}
    return 200, {"config": _redact(row)}


def _coerce_bound(raw, name: str, minimum: int, maximum: int):
    """Parse one pagination bound. Returns (value, error_response_or_None).

    Rejects rather than clamps a malformed bound: silently serving page 0 for
    `?limit=abc` hides a broken client until it ships.
    """
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None, (400, {"error": f"{name} must be an integer", name: raw})
    if val < minimum:
        return None, (400, {"error": f"{name} must be >= {minimum}", name: val})
    if val > maximum:
        return None, (400, {"error": f"{name} must be <= {maximum}", name: val})
    return val, None


def list_config(store=None, query: Optional[Dict[str, Any]] = None) -> Response:
    """GET /config[?limit=&offset=] -> 200 with rows, each independently redacted.

    Pagination is opt-in: with no `limit` the whole table is returned, which is what
    every existing caller expects and is safe while the table is small and fleet-wide.
    Supplying `limit` switches on a stable offset window and adds a `page` block so a
    client can tell "that was everything" from "that was the first hundred" — the
    distinction an unpaginated list cannot express, and the reason a fleet-wide GET
    could previously return an unbounded body.

    Offset paging, not a cursor: rows are keyed by a stable primary key and the table
    does not churn under a reader. A cursor here would be ceremony without a payer.
    """
    query = query or {}
    store = store or config_store.get_store()
    rows = store.get_all() or []
    total = len(rows)

    limit = None
    offset = 0
    if query.get("offset") is not None:
        offset, err = _coerce_bound(query.get("offset"), "offset", 0, MAX_LIST_OFFSET)
        if err:
            return err
    if query.get("limit") is not None:
        limit, err = _coerce_bound(query.get("limit"), "limit", 1, MAX_LIST_LIMIT)
        if err:
            return err
        rows = rows[offset:offset + limit]
    elif offset:
        rows = rows[offset:]

    redacted = [_redact(r) for r in rows]
    body = {
        "config": redacted,
        "count": len(redacted),
        "redacted_count": sum(1 for r in redacted if isinstance(r, dict) and r.get("redacted")),
    }
    if limit is not None or offset:
        body["page"] = {
            "limit": limit,
            "offset": offset,
            "total": total,
            "has_more": offset + len(redacted) < total,
        }
    return 200, body


def put_config(key: str, body: Optional[Dict[str, Any]], store=None) -> Response:
    """PUT /config/{key} -> 200 (updated) / 201 (created) / 400 / 422.

    A credential is refused with 422, not 400: the request is well-formed, the
    *content* is inadmissible. The refusal reason names the key and the shape only.
    """
    if not key or not str(key).strip():
        return 400, {"error": "key is required"}
    if not isinstance(body, dict) or "value" not in body:
        return 400, {"error": "body must be a JSON object containing 'value'"}

    value = body.get("value")
    secret, reason = fleet_config_guard.classify(key, value)
    if secret:
        # Refuse before the store is touched: the write path would raise anyway, but
        # only after the value had been through its logging.
        return 422, {"error": "refused: credentials must not be stored in fleet_config",
                     "reason": reason, "key": key}

    store = store or config_store.get_store()
    existed = store.get_config(key) is not None
    try:
        _old, new = store.update_config(
            key, value, note=body.get("note"), updated_by=body.get("updated_by"))
    except ValueError as exc:
        # Fail-closed backstop: the guard is enforced at db.upsert as well, and a
        # future pattern addition must surface here rather than as a 500.
        return 422, {"error": str(exc), "key": key}
    if new is None:
        return 500, {"error": "write rejected by the store", "key": key}
    return (200 if existed else 201), {"config": _redact(new)}


# verb -> (handler, takes_key). A transport walks this instead of re-deriving routes,
# so the allowed verb set has exactly one definition.
ROUTES = {
    ("GET", "/config"): (list_config, False),
    ("GET", "/config/{key}"): (get_config, True),
    ("PUT", "/config/{key}"): (put_config, True),
}


def dispatch(method: str, path: str, body: Optional[Dict[str, Any]] = None,
             store=None, query: Optional[Dict[str, Any]] = None) -> Response:
    """Route one request. 404 for an unknown path, 405 for a known path/wrong verb.

    The 405-vs-404 split is deliberate: collapsing them makes a typo'd verb read as a
    missing endpoint, which is the harder of the two to debug from a client.

    `query` is optional and only reaches the collection handler; `path` may carry its
    own query string, which is parsed here so a transport that hands over a raw
    REQUEST_URI behaves the same as one that pre-parses.
    """
    method = (method or "").upper()
    raw = (path or "")
    if "?" in raw:
        raw, _, qs = raw.partition("?")
        if query is None:
            query = {k: v[-1] for k, v in urllib.parse.parse_qs(qs).items()}
    raw = raw.rstrip("/") or "/config"

    if raw == "/config":
        template, key = "/config", None
    elif raw.startswith("/config/"):
        template, key = "/config/{key}", raw[len("/config/"):]
    else:
        return 404, {"error": "no such endpoint", "path": path}

    handler_entry = ROUTES.get((method, template))
    if handler_entry is None:
        allowed = sorted({m for (m, t) in ROUTES if t == template})
        return 405, {"error": "method not allowed", "allowed": allowed}

    handler, takes_key = handler_entry
    if takes_key:
        if handler is put_config:
            return handler(key, body, store=store)
        return handler(key, store=store)
    return handler(store=store, query=query)
