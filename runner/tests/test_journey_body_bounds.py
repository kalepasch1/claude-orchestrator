"""The two defects a real production run found in the http probe.

Both were invisible to the existing suite because every test injected its own
`http` double, so `_default_http` — where both bugs lived — was never exercised,
and no test ever set the truncation flag.
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import production_journey as pj


class _FakeResponse(io.BytesIO):
    def __init__(self, body, headers, status=200):
        super().__init__(body)
        self.status = status
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_returning(body, headers, monkeypatch, status=200):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(body, headers, status))


# --------------------------------------------------------------- header lookup

def test_header_lookup_is_case_insensitive(monkeypatch):
    """`dict(r.headers)` keeps urllib's canonical casing; lookups used lower case."""
    _urlopen_returning(b"hello", {"Content-Type": "text/html; charset=utf-8"}, monkeypatch)
    _, _, headers = pj._default_http("https://example.test/")
    assert headers.get("content-type") == "text/html; charset=utf-8"
    assert headers.get("Content-Type") == "text/html; charset=utf-8"
    assert headers.get("CONTENT-TYPE") == "text/html; charset=utf-8"
    assert headers.get("x-absent") is None


def test_expect_header_passes_against_canonical_cased_response(monkeypatch):
    _urlopen_returning(b"hello", {"Content-Type": "text/html"}, monkeypatch)
    step = {"name": "s", "probe": "http", "path": "/", "expect_status": 200,
            "expect_header": {"content-type": "text/html"}, "timeout_s": 5}
    assertions, _, _ = pj._run_http_step(step, "https://example.test", pj._default_http)
    header = [a for a in assertions if a["name"] == "header"][0]
    assert header["ok"] is True, header
    assert header["actual"] == "text/html"


def test_plain_dict_double_still_works():
    """Injected test doubles return plain dicts and must keep working."""
    def http(url, timeout=None):
        return 200, "body", {"content-type": "application/json"}

    step = {"name": "s", "probe": "http", "path": "/", "expect_status": 200,
            "expect_header": {"content-type": "application/json"}, "timeout_s": 5}
    assertions, _, _ = pj._run_http_step(step, "https://example.test", http)
    assert [a for a in assertions if a["name"] == "header"][0]["ok"] is True


# ------------------------------------------------------------------ truncation

def test_body_is_read_past_the_old_200kb_cap(monkeypatch):
    body = b"x" * 400_000 + b"NEEDLE"
    _urlopen_returning(body, {"Content-Type": "text/html"}, monkeypatch)
    _, text, headers = pj._default_http("https://example.test/")
    assert "NEEDLE" in text
    assert headers.truncated is False


def test_truncation_is_detected_and_flagged(monkeypatch):
    monkeypatch.setenv("ORCH_JOURNEY_MAX_BODY", "2000")  # above the 1024 floor
    _urlopen_returning(b"y" * 5000, {"Content-Type": "text/html"}, monkeypatch)
    status, text, headers = pj._default_http("https://example.test/")
    assert status == 200
    assert len(text) == 2000
    assert headers.truncated is True


def test_contains_on_truncated_body_says_inconclusive_not_absent():
    def http(url, timeout=None):
        h = pj._Headers({"Content-Type": "text/html"})
        h.truncated = True
        return 200, "only the first page", h

    step = {"name": "s", "probe": "http", "path": "/", "expect_status": 200,
            "expect_body_contains": ["deep in the page"], "timeout_s": 5}
    assertions, _, _ = pj._run_http_step(step, "https://example.test", http)
    a = [x for x in assertions if x["name"] == "body_contains"][0]
    assert a["ok"] is False
    assert "truncated" in a["actual"], a["actual"]
    assert a["actual"] != "absent"


def test_absent_on_truncated_body_must_not_pass():
    """The promoting direction. Unproven absence is not absence."""
    def http(url, timeout=None):
        h = pj._Headers({"Content-Type": "text/html"})
        h.truncated = True
        return 200, "the healthy-looking first page", h

    step = {"name": "s", "probe": "http", "path": "/", "expect_status": 200,
            "expect_body_absent": ["Application error"], "timeout_s": 5}
    assertions, _, _ = pj._run_http_step(step, "https://example.test", http)
    a = [x for x in assertions if x["name"] == "body_absent"][0]
    assert a["ok"] is False, "a truncated body cannot prove a string is absent"
    assert "truncated" in a["actual"]


def test_absent_on_complete_body_still_passes():
    def http(url, timeout=None):
        return 200, "a healthy page", {"Content-Type": "text/html"}

    step = {"name": "s", "probe": "http", "path": "/", "expect_status": 200,
            "expect_body_absent": ["Application error"], "timeout_s": 5}
    assertions, _, _ = pj._run_http_step(step, "https://example.test", http)
    a = [x for x in assertions if x["name"] == "body_absent"][0]
    assert a["ok"] is True
    assert a["actual"] == "absent"


def test_max_body_bytes_has_a_floor():
    os.environ["ORCH_JOURNEY_MAX_BODY"] = "1"
    try:
        assert pj.max_body_bytes() >= 1024
    finally:
        os.environ.pop("ORCH_JOURNEY_MAX_BODY", None)
