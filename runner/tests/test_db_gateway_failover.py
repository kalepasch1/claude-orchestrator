"""A gateway error is the proxy saying it never reached the origin — not an answer.

On 2026-08-19 the fleet's Supabase project stopped answering. Every endpoint in the chain
returned Cloudflare 522, and two rules in db.py turned that into an 8-hour total stall:

  * `_req_one` pinned the endpoint on ANY HTTPError, including 522 — in memory AND in
    `.runtime/supabase-active-endpoint`, so every process started with the dead one first;
  * `_req` re-raised any HTTPError rather than failing over, so the three remaining
    endpoints were never tried.

And with the plane down, every call still paid the full timeout budget: one
`config_approval` sweep advanced at ONE KEY PER 25 SECONDS, the main loop stopped emitting
scheduler lines, and the periodic reaper began killing jobs for outliving their lease.
"""
import os
import socket
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


def _http_error(code):
    return urllib.error.HTTPError("http://x", code, f"status {code}", {}, None)


class _Resp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, payload=b"[]"):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Real URL/KEY, a known endpoint chain, and a reset breaker for every test."""
    monkeypatch.setattr(db, "URL", "https://primary.example")
    monkeypatch.setattr(db, "KEY", "test-key")
    monkeypatch.setenv("ORCH_SUPABASE_FALLBACK_URLS",
                       "https://second.example,https://third.example")
    monkeypatch.setattr(db, "_ACTIVE_BASE", {"url": None})
    monkeypatch.setattr(db, "_save_active_base", lambda url: None)
    # "probing" is not optional: _breaker_blocks() reads it on every call, so a dict
    # without it turns the first request after a trip into a KeyError inside the lock.
    monkeypatch.setattr(db, "_BREAKER",
                        {"consecutive": 0, "open_until": 0.0, "trips": 0, "probing": False})
    monkeypatch.setattr(db, "DB_BREAKER_ENABLED", True)
    monkeypatch.setattr(db, "DB_BREAKER_THRESHOLD", 3)
    monkeypatch.setattr(db, "DB_BREAKER_COOLDOWN_S", 60.0)
    monkeypatch.setattr(db, "HTTP_RETRIES", 0)
    monkeypatch.setattr(db, "time", db.time)


def _urlopen(behaviour):
    """behaviour: host-substring -> exception instance or _Resp. Records call order."""
    calls = []

    def fake(req, timeout=None):
        url = req.full_url
        calls.append(url)
        for key, outcome in behaviour.items():
            if key in url:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"unexpected url {url}")

    return fake, calls


# --- failover ---------------------------------------------------------------------------

def test_a_gateway_error_fails_over_to_the_next_endpoint(monkeypatch):
    fake, calls = _urlopen({"primary": _http_error(522), "second": _Resp()})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    assert db._req("GET", "/rest/v1/projects") == []

    assert any("primary" in c for c in calls) and any("second" in c for c in calls)


@pytest.mark.parametrize("code", [502, 504, 520, 521, 522, 523, 524, 525])
def test_every_gateway_status_fails_over(monkeypatch, code):
    fake, calls = _urlopen({"primary": _http_error(code), "second": _Resp()})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    assert db._req("GET", "/rest/v1/projects") == []
    assert any("second" in c for c in calls)


@pytest.mark.parametrize("code", [500, 503])
def test_a_real_server_error_does_not_fail_over(monkeypatch, code):
    """PostgREST and Postgres return these themselves — the endpoint IS reachable."""
    fake, calls = _urlopen({"primary": _http_error(code)})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    with pytest.raises(urllib.error.HTTPError):
        db._req("GET", "/rest/v1/projects")
    assert all("primary" in c for c in calls), "must not have tried another endpoint"


def test_a_gateway_error_never_pins_the_dead_endpoint(monkeypatch):
    saved = []
    monkeypatch.setattr(db, "_save_active_base", lambda url: saved.append(url))
    fake, _ = _urlopen({"primary": _http_error(522), "second": _Resp()})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    db._req("GET", "/rest/v1/projects")

    assert db._ACTIVE_BASE["url"] == "https://second.example"
    assert "https://primary.example" not in saved, \
        "pinning a 522-ing endpoint is what made the outage sticky across processes"


def test_all_endpoints_gateway_failing_raises_transient_not_httperror(monkeypatch):
    """Callers classify TransientDBError as environmental; a bare HTTPError crash-loops."""
    fake, _ = _urlopen({"example": _http_error(522)})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    with pytest.raises(db.TransientDBError):
        db._req("GET", "/rest/v1/projects")


# --- circuit breaker --------------------------------------------------------------------

def test_the_breaker_opens_and_then_costs_no_network_at_all(monkeypatch):
    fake, calls = _urlopen({"example": _http_error(522)})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    for _ in range(db.DB_BREAKER_THRESHOLD):
        with pytest.raises(db.TransientDBError):
            db._req("GET", "/rest/v1/projects")
    calls_before = len(calls)

    with pytest.raises(db.TransientDBError) as caught:
        db._req("GET", "/rest/v1/projects")

    assert len(calls) == calls_before, "an open breaker must not touch the network"
    assert "circuit breaker open" in str(caught.value)
    assert db.breaker_state()["trips"] == 1


def test_tripping_the_breaker_does_not_raise_NameError(monkeypatch, capsys):
    """The trip path writes to sys.stderr — and `sys` was not imported at module scope.

    py_compile cannot catch that: it only fires when the breaker actually trips, i.e. in the
    middle of an outage. This test is the reason it is caught here instead of there.
    """
    fake, _ = _urlopen({"example": _http_error(522)})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    for _ in range(db.DB_BREAKER_THRESHOLD):
        with pytest.raises(db.TransientDBError):
            db._req("GET", "/rest/v1/projects")

    assert "circuit breaker OPEN" in capsys.readouterr().err


def test_a_success_closes_the_breaker(monkeypatch):
    fake, _ = _urlopen({"primary": _http_error(522), "second": _Resp()})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    for _ in range(5):
        db._req("GET", "/rest/v1/projects")

    assert db.breaker_state()["consecutive"] == 0
    assert db.breaker_state()["open_until"] == 0.0


def test_a_postgrest_status_also_counts_as_the_plane_being_up(monkeypatch):
    """A 400 is an answer. It must not accumulate toward 'the control plane is down'."""
    fake, _ = _urlopen({"primary": _http_error(400)})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    for _ in range(db.DB_BREAKER_THRESHOLD + 2):
        with pytest.raises(Exception):
            db._req("GET", "/rest/v1/projects")

    assert db.breaker_state()["trips"] == 0
    assert db.breaker_state()["open_until"] == 0.0


def test_the_cooldown_re_admits_exactly_one_real_probe(monkeypatch):
    fake, calls = _urlopen({"example": _http_error(522)})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)
    for _ in range(db.DB_BREAKER_THRESHOLD):
        with pytest.raises(db.TransientDBError):
            db._req("GET", "/rest/v1/projects")

    # A deadline in the PAST, not zero: open_until is both the deadline and the latch, so
    # zeroing it simulates recovery rather than expiry and never reaches the half-open path.
    db._BREAKER["open_until"] = db.time.monotonic() - 1.0
    before = len(calls)
    with pytest.raises(db.TransientDBError):
        db._req("GET", "/rest/v1/projects")

    assert len(calls) > before, "the half-open probe must actually hit the network"
    assert db._BREAKER["open_until"] > 0, "and a failed probe must re-open the breaker"


def test_the_breaker_can_be_disabled(monkeypatch):
    monkeypatch.setattr(db, "DB_BREAKER_ENABLED", False)
    fake, calls = _urlopen({"example": _http_error(522)})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    for _ in range(db.DB_BREAKER_THRESHOLD + 2):
        with pytest.raises(db.TransientDBError):
            db._req("GET", "/rest/v1/projects")

    assert db.breaker_state()["trips"] == 0
    assert len(calls) > db.DB_BREAKER_THRESHOLD


def test_connection_errors_still_trip_it_too(monkeypatch):
    fake, _ = _urlopen({"example": socket.timeout("timed out")})
    monkeypatch.setattr(db.urllib.request, "urlopen", fake)

    for _ in range(db.DB_BREAKER_THRESHOLD):
        with pytest.raises(db.TransientDBError):
            db._req("GET", "/rest/v1/projects")

    assert db.breaker_state()["trips"] == 1
