"""db.count() must use the same failover/retry/breaker path as every other read.

`count()` hand-rolled a single bare urlopen against the primary URL. It therefore, alone
among the reads: paid the full timeout budget while the control-plane breaker was open,
never failed over to a healthy endpoint, and raised on a transient 503 that `select()`
retries. Callers wrap counts in `except: 0` (queue_monitor does for all ten states), so
each of those failures became a silent, plausible-looking ZERO on a dashboard — the most
expensive kind of wrong number.
"""
import io
import os
import sys
import urllib.error

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import db  # noqa: E402


class _Response:
    def __init__(self, total="7", body=""):
        self.headers = {"Content-Range": f"0-0/{total}"} if total is not None else {}
        self._body = body

    def read(self):
        return self._body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, total=None):
    headers = {"Content-Range": f"0-0/{total}"} if total is not None else {}
    return urllib.error.HTTPError("u", code, "err", headers, io.BytesIO(b""))


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    monkeypatch.setattr(db, "URL", "https://primary.example")
    monkeypatch.setattr(db, "KEY", "k")
    monkeypatch.setattr(db, "_breaker_blocks", lambda: False)
    monkeypatch.setattr(db, "_breaker_record_answer", lambda: None)
    monkeypatch.setattr(db, "_breaker_record_unreachable", lambda: None)
    monkeypatch.setattr(db, "_pin", lambda base: None)
    monkeypatch.setattr(db, "_base_urls", lambda: ["https://primary.example"])
    monkeypatch.setattr(db.time, "sleep", lambda *_: None)


def test_parses_the_total_from_content_range():
    assert db._total_from_content_range("0-0/1234") == 1234
    assert db._total_from_content_range("0-0/*") is None
    assert db._total_from_content_range("") is None
    assert db._total_from_content_range(None) is None
    assert db._total_from_content_range("0-0/notanumber") is None


def test_happy_path_returns_the_count(monkeypatch):
    monkeypatch.setattr(db.urllib.request, "urlopen", lambda *a, **k: _Response("42"))
    assert db.count("tasks", {"state": "eq.QUEUED"}) == 42


def test_empty_result_416_is_an_answer_not_an_error(monkeypatch):
    def raise_416(*a, **k):
        raise _http_error(416, total=0)
    monkeypatch.setattr(db.urllib.request, "urlopen", raise_416)
    assert db.count("tasks") == 0


def test_transient_503_is_retried_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(503)
        return _Response("9")

    monkeypatch.setattr(db.urllib.request, "urlopen", flaky)
    assert db.count("tasks") == 9, "a transient 503 must not surface as a failure"
    assert calls["n"] == 2


def test_open_breaker_fails_fast_instead_of_paying_the_timeout(monkeypatch):
    monkeypatch.setattr(db, "_breaker_blocks", lambda: True)
    monkeypatch.setattr(db.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("must not hit the network"))
    with pytest.raises(db.ControlPlaneDown):
        db.count("tasks")


def test_unreachable_endpoint_fails_over_to_a_healthy_one(monkeypatch):
    monkeypatch.setattr(db, "_base_urls",
                        lambda: ["https://dead.example", "https://alive.example"])
    seen = []

    def by_host(req, *a, **k):
        seen.append(req.full_url)
        if "dead" in req.full_url:
            raise urllib.error.URLError("connection refused")
        return _Response("5")

    monkeypatch.setattr(db.urllib.request, "urlopen", by_host)
    assert db.count("tasks") == 5
    assert any("dead" in u for u in seen) and any("alive" in u for u in seen)


def test_gateway_status_fails_over_rather_than_raising(monkeypatch):
    monkeypatch.setattr(db, "_base_urls",
                        lambda: ["https://proxy.example", "https://alive.example"])

    def by_host(req, *a, **k):
        if "proxy" in req.full_url:
            raise _http_error(522)
        return _Response("3")

    monkeypatch.setattr(db.urllib.request, "urlopen", by_host)
    assert db.count("tasks") == 3


def test_all_endpoints_down_raises_transient_not_a_silent_zero(monkeypatch):
    """The failure MUST be loud: a swallowed count becomes a fake 0 on a dashboard."""
    monkeypatch.setattr(db.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("down")))
    with pytest.raises(db.TransientDBError):
        db.count("tasks")


def test_real_client_error_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def bad_request(*a, **k):
        calls["n"] += 1
        raise _http_error(400)

    monkeypatch.setattr(db.urllib.request, "urlopen", bad_request)
    with pytest.raises(urllib.error.HTTPError):
        db.count("tasks")
    assert calls["n"] == 1, "a 400 is a bug in the query; retrying it just costs latency"


def test_count_requests_no_row_payload(monkeypatch):
    captured = {}

    def capture(req, *a, **k):
        captured["url"] = req.full_url
        captured["headers"] = {k.lower(): v for k, v in req.headers.items()}
        return _Response("1")

    monkeypatch.setattr(db.urllib.request, "urlopen", capture)
    db.count("tasks", {"state": "eq.QUEUED"})
    assert captured["headers"].get("Range".lower()) == "0-0"
    assert "count=exact" in captured["headers"].get("Prefer".lower(), "")
    assert "state=eq.QUEUED" in captured["url"]
