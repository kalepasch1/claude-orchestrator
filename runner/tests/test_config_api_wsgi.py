#!/usr/bin/env python3
"""Tests for the config API HTTP transport and the slice-2 pagination.

Every endpoint is exercised end to end through the WSGI callable: auth
(fail-closed, malformed header, wrong token, right token), body handling (size
cap, lying Content-Length, non-JSON, non-object), routing, pagination bounds,
and the guarantee that an unexpected exception never leaks internals.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_api  # noqa: E402
import config_api_wsgi  # noqa: E402

TOKEN = "test-token-not-a-real-credential"


class FakeStore:
    """Minimal in-memory ConfigStore. No DB, no network."""

    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    def get_config(self, key):
        val = self.rows.get(key)
        return {"key": key, "value": val} if val is not None else None

    def get_all(self):
        return [{"key": k, "value": v} for k, v in sorted(self.rows.items())]

    def update_config(self, key, value, note=None, updated_by=None):
        old = self.get_config(key)
        self.rows[key] = value
        return old, {"key": key, "value": value}


def env(method="GET", path="/config", query="", body=None, token=None,
        content_length=None, auth_header=None):
    raw = b"" if body is None else json.dumps(body).encode()
    e = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(raw),
        "wsgi.errors": io.StringIO(),
        "CONTENT_LENGTH": str(len(raw)) if content_length is None else str(content_length),
    }
    if auth_header is not None:
        e["HTTP_AUTHORIZATION"] = auth_header
    elif token:
        e["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return e


@pytest.fixture
def store():
    return FakeStore({"ORCH_A": "1", "ORCH_B": "2", "ORCH_C": "3"})


@pytest.fixture(autouse=True)
def _token_env(monkeypatch):
    monkeypatch.setenv("ORCH_CONFIG_API_TOKEN", TOKEN)
    monkeypatch.setattr(config_api_wsgi, "REQUIRE_AUTH_READS", False)
    yield


# ----------------------------------------------------------------- auth


def test_read_needs_no_token_by_default(store):
    status, body = config_api_wsgi.handle(env("GET", "/config"), store=store)
    assert status == 200
    assert body["count"] == 3


def test_read_can_be_gated(monkeypatch, store):
    monkeypatch.setattr(config_api_wsgi, "REQUIRE_AUTH_READS", True)
    status, _ = config_api_wsgi.handle(env("GET", "/config"), store=store)
    assert status == 401


def test_write_without_token_is_401(store):
    status, body = config_api_wsgi.handle(
        env("PUT", "/config/ORCH_A", body={"value": "9"}), store=store)
    assert status == 401
    assert "Authorization" in body["error"]


def test_write_with_wrong_token_is_403(store):
    status, _ = config_api_wsgi.handle(
        env("PUT", "/config/ORCH_A", body={"value": "9"}, token="wrong"), store=store)
    assert status == 403


def test_write_with_malformed_scheme_is_401(store):
    status, _ = config_api_wsgi.handle(
        env("PUT", "/config/ORCH_A", body={"value": "9"},
            auth_header=f"Basic {TOKEN}"), store=store)
    assert status == 401


def test_unconfigured_token_fails_closed_not_open(monkeypatch, store):
    monkeypatch.delenv("ORCH_CONFIG_API_TOKEN", raising=False)
    status, body = config_api_wsgi.handle(
        env("PUT", "/config/ORCH_A", body={"value": "9"}, token=TOKEN), store=store)
    assert status == 503
    assert store.rows["ORCH_A"] == "1"  # unchanged
    assert "ORCH_CONFIG_API_TOKEN" in body["error"]


def test_token_is_never_read_from_fleet_config(monkeypatch, store):
    """The credential guarding this table must not come from the table."""
    monkeypatch.delenv("ORCH_CONFIG_API_TOKEN", raising=False)
    store.rows["ORCH_CONFIG_API_TOKEN"] = TOKEN
    status, _ = config_api_wsgi.handle(
        env("PUT", "/config/ORCH_A", body={"value": "9"}, token=TOKEN), store=store)
    assert status == 503


def test_valid_token_allows_write(store):
    status, body = config_api_wsgi.handle(
        env("PUT", "/config/ORCH_A", body={"value": "9"}, token=TOKEN), store=store)
    assert status == 200
    assert store.rows["ORCH_A"] == "9"


def test_valid_token_creates_with_201(store):
    status, _ = config_api_wsgi.handle(
        env("PUT", "/config/ORCH_NEW", body={"value": "x"}, token=TOKEN), store=store)
    assert status == 201


# ------------------------------------------------------------ body handling


def test_body_over_cap_is_413(monkeypatch, store):
    monkeypatch.setattr(config_api_wsgi, "MAX_BODY_BYTES", 32)
    status, _ = config_api_wsgi.handle(
        env("PUT", "/config/ORCH_A", body={"value": "y" * 500}, token=TOKEN), store=store)
    assert status == 413


def test_lying_content_length_is_caught(monkeypatch, store):
    """A short declared length must not let an oversized stream through."""
    monkeypatch.setattr(config_api_wsgi, "MAX_BODY_BYTES", 16)
    e = env("PUT", "/config/ORCH_A", token=TOKEN)
    e["wsgi.input"] = io.BytesIO(b"z" * 4096)
    e["CONTENT_LENGTH"] = "999999"
    assert config_api_wsgi.handle(e, store=store)[0] == 413


def test_non_integer_content_length_is_400(store):
    status, _ = config_api_wsgi.handle(
        env("PUT", "/config/ORCH_A", body={"value": "1"}, token=TOKEN,
            content_length="banana"), store=store)
    assert status == 400


def test_non_json_body_is_400(store):
    e = env("PUT", "/config/ORCH_A", token=TOKEN)
    e["wsgi.input"] = io.BytesIO(b"not json at all")
    e["CONTENT_LENGTH"] = "15"
    assert config_api_wsgi.handle(e, store=store)[0] == 400


def test_json_array_body_is_400(store):
    e = env("PUT", "/config/ORCH_A", token=TOKEN)
    payload = b'["value"]'
    e["wsgi.input"] = io.BytesIO(payload)
    e["CONTENT_LENGTH"] = str(len(payload))
    assert config_api_wsgi.handle(e, store=store)[0] == 400


def test_empty_body_reaches_handler_as_400(store):
    status, body = config_api_wsgi.handle(
        env("PUT", "/config/ORCH_A", token=TOKEN), store=store)
    assert status == 400
    assert "value" in body["error"]


# ---------------------------------------------------------------- routing


def test_unknown_path_is_404(store):
    assert config_api_wsgi.handle(env("GET", "/nope"), store=store)[0] == 404


def test_wrong_verb_is_405_with_allow(store):
    status, body = config_api_wsgi.handle(
        env("DELETE", "/config/ORCH_A", token=TOKEN), store=store)
    assert status == 405
    assert body["allowed"] == ["GET", "PUT"]


def test_missing_key_is_404(store):
    assert config_api_wsgi.handle(env("GET", "/config/NOPE"), store=store)[0] == 404


def test_single_key_read(store):
    status, body = config_api_wsgi.handle(env("GET", "/config/ORCH_B"), store=store)
    assert status == 200
    assert body["config"]["value"] == "2"


# ------------------------------------------------------------- pagination


def test_list_unpaginated_by_default(store):
    status, body = config_api.list_config(store=store)
    assert status == 200
    assert body["count"] == 3
    assert "page" not in body


def test_limit_windows_the_result(store):
    status, body = config_api.list_config(store=store, query={"limit": 2})
    assert status == 200
    assert [r["key"] for r in body["config"]] == ["ORCH_A", "ORCH_B"]
    assert body["page"] == {"limit": 2, "offset": 0, "total": 3, "has_more": True}


def test_offset_advances_the_window(store):
    _, body = config_api.list_config(store=store, query={"limit": 2, "offset": 2})
    assert [r["key"] for r in body["config"]] == ["ORCH_C"]
    assert body["page"]["has_more"] is False


def test_offset_alone_skips_without_limiting(store):
    _, body = config_api.list_config(store=store, query={"offset": 1})
    assert body["count"] == 2
    assert body["page"]["limit"] is None


def test_offset_past_end_is_empty_not_an_error(store):
    status, body = config_api.list_config(store=store, query={"limit": 5, "offset": 99})
    assert status == 200
    assert body["config"] == []


@pytest.mark.parametrize("bad", ["abc", "", "1.5", []])
def test_non_integer_limit_is_rejected(store, bad):
    assert config_api.list_config(store=store, query={"limit": bad})[0] == 400


def test_explicit_none_limit_means_not_supplied(store):
    """None is absence, not a malformed value — a caller passing through a
    dict with every key present must not get a 400 for the ones it left unset."""
    status, body = config_api.list_config(store=store, query={"limit": None,
                                                              "offset": None})
    assert status == 200
    assert "page" not in body


def test_zero_limit_is_rejected(store):
    assert config_api.list_config(store=store, query={"limit": 0})[0] == 400


def test_negative_offset_is_rejected(store):
    assert config_api.list_config(store=store, query={"offset": -1})[0] == 400


def test_limit_above_cap_is_rejected(store):
    over = config_api.MAX_LIST_LIMIT + 1
    assert config_api.list_config(store=store, query={"limit": over})[0] == 400


def test_query_string_reaches_the_handler_via_wsgi(store):
    status, body = config_api_wsgi.handle(
        env("GET", "/config", query="limit=1"), store=store)
    assert status == 200
    assert body["count"] == 1


def test_dispatch_parses_a_query_string_in_the_path(store):
    status, body = config_api.dispatch("GET", "/config?limit=1", store=store)
    assert status == 200
    assert body["count"] == 1


def test_dispatch_without_query_is_unchanged(store):
    status, body = config_api.dispatch("GET", "/config", store=store)
    assert status == 200
    assert body["count"] == 3


# ------------------------------------------------- error containment + app


def test_unexpected_exception_becomes_a_bare_500(store, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("secret-bearing internal detail")

    monkeypatch.setattr(config_api, "dispatch", _boom)
    e = env("GET", "/config")
    status, body = config_api_wsgi.handle(e, store=store)
    assert status == 500
    assert body == {"error": "internal error"}
    assert "secret-bearing" not in json.dumps(body)
    assert "secret-bearing" in e["wsgi.errors"].getvalue()


def test_app_returns_json_bytes_and_headers(store, monkeypatch):
    monkeypatch.setattr(config_api, "dispatch",
                        lambda *a, **k: (200, {"config": [], "count": 0}))
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    out = config_api_wsgi.app(env("GET", "/config"), start_response)
    assert captured["status"] == "200 OK"
    assert captured["headers"]["Content-Type"].startswith("application/json")
    assert captured["headers"]["Cache-Control"] == "no-store"
    assert captured["headers"]["X-Content-Type-Options"] == "nosniff"
    assert captured["headers"]["Content-Length"] == str(len(out[0]))
    assert json.loads(out[0]) == {"config": [], "count": 0}


def test_app_sets_www_authenticate_on_401(monkeypatch):
    monkeypatch.setattr(config_api_wsgi, "REQUIRE_AUTH_READS", True)
    captured = {}
    config_api_wsgi.app(
        env("GET", "/config"),
        lambda s, h: captured.update(status=s, headers=dict(h)))
    assert captured["status"] == "401 Unauthorized"
    assert captured["headers"]["WWW-Authenticate"].startswith("Bearer")


def test_app_sets_allow_header_on_405(monkeypatch):
    monkeypatch.setenv("ORCH_CONFIG_API_TOKEN", TOKEN)
    captured = {}
    config_api_wsgi.app(
        env("DELETE", "/config/ORCH_A", token=TOKEN),
        lambda s, h: captured.update(status=s, headers=dict(h)))
    assert captured["status"] == "405 Method Not Allowed"
    assert captured["headers"]["Allow"] == "GET, PUT"


def test_mutating_methods_set_is_complete():
    assert config_api_wsgi.MUTATING_METHODS >= {"PUT", "POST", "PATCH", "DELETE"}
