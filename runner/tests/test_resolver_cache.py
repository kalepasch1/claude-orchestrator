"""5,706 DNS failures for a name that resolves in 3ms.

db.py calls urlopen() once per request, so every control-plane call also performs a
fresh name resolution. Dozens of orchestrator processes doing that several times a
second exhausts the macOS resolver. Counted across the fleet's own .err logs on
2026-09-02:

    urlopen error [Errno 8] nodename nor servname provided   5,706
    urlopen error [Errno 61] Connection refused                174
    urlopen error [Errno 60] Operation timed out              110
    urlopen error timed out                                     90
    urlopen error [Errno 54] Connection reset by peer           88
    control-plane circuit breaker trips                          99

Errno 8 is not the network being down -- it is the host failing to RESOLVE a name it
answers in 3ms when asked calmly. Checked five times in a row during a twenty-minute
window in which 177 of those failures were logged across ten jobs:

    ok 4ms   ok 3ms   ok 3ms   ok 3ms   ok 3ms

Each failure costs a retry, and eight in a row open the circuit breaker for 180
seconds, during which the WHOLE FLEET fails its control-plane calls fast. A
self-inflicted outage from asking the same question ten thousand times.

Measured after installing this: 200 lookups in 1.3ms total, against 14ms for one real
resolution, and example.com still takes its normal 36ms because it passes straight
through.

The caching is the cheap part. STALE-IF-ERROR is the point: a resolver failure for a
host we resolved successfully minutes ago is answered from the last good result
instead of becoming a TransientDBError.
"""
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import resolver_cache  # noqa: E402


ANSWER = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
OTHER = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", 443))]


@pytest.fixture
def fake(monkeypatch):
    """Install the cache over a resolver we control."""
    calls = {"n": 0, "fail": False, "answer": ANSWER}

    def _real(host, port, family=0, type=0, proto=0, flags=0):
        calls["n"] += 1
        if calls["fail"]:
            raise socket.gaierror(8, "nodename nor servname provided, or not known")
        return calls["answer"]

    resolver_cache.uninstall()
    resolver_cache.reset()
    monkeypatch.setattr(socket, "getaddrinfo", _real)
    resolver_cache.install(["db.example.co"])
    yield calls
    resolver_cache.uninstall()
    resolver_cache.reset()


# ── caching ───────────────────────────────────────────────────────────────────

def test_the_second_lookup_does_not_reach_the_resolver(fake):
    socket.getaddrinfo("db.example.co", 443)
    socket.getaddrinfo("db.example.co", 443)
    assert fake["n"] == 1


def test_two_hundred_lookups_cost_one_resolution(fake):
    for _ in range(200):
        socket.getaddrinfo("db.example.co", 443)
    assert fake["n"] == 1


def test_an_unrelated_host_passes_straight_through(fake):
    """A process-wide DNS override is a big hammer; it lands on one nail."""
    socket.getaddrinfo("example.com", 443)
    socket.getaddrinfo("example.com", 443)
    assert fake["n"] == 2
    assert resolver_cache.stats()["passthrough"] == 2


def test_the_ttl_expires(fake, monkeypatch):
    monkeypatch.setenv("ORCH_DNS_CACHE_TTL_S", "0")
    socket.getaddrinfo("db.example.co", 443)
    socket.getaddrinfo("db.example.co", 443)
    assert fake["n"] == 2


def test_a_different_port_is_a_different_entry(fake):
    socket.getaddrinfo("db.example.co", 443)
    socket.getaddrinfo("db.example.co", 80)
    assert fake["n"] == 2


def test_the_host_match_is_case_insensitive(fake):
    socket.getaddrinfo("DB.Example.CO", 443)
    socket.getaddrinfo("db.example.co", 443)
    assert fake["n"] == 1


# ── stale-if-error: the actual point ─────────────────────────────────────────

def test_a_resolver_failure_is_answered_from_the_last_good_result(fake, monkeypatch):
    monkeypatch.setenv("ORCH_DNS_CACHE_TTL_S", "0")     # force a real lookup each time
    assert socket.getaddrinfo("db.example.co", 443) == ANSWER
    fake["fail"] = True
    assert socket.getaddrinfo("db.example.co", 443) == ANSWER, (
        "a transient Errno 8 became a control-plane failure again")
    assert resolver_cache.stats()["stale_served"] == 1


def test_a_failure_with_nothing_cached_still_raises(fake):
    """Inventing an answer we never had would be worse than failing."""
    fake["fail"] = True
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("db.example.co", 443)


def test_a_stale_answer_expires_eventually(fake, monkeypatch):
    monkeypatch.setenv("ORCH_DNS_CACHE_TTL_S", "0")
    monkeypatch.setenv("ORCH_DNS_STALE_S", "0")
    socket.getaddrinfo("db.example.co", 443)
    fake["fail"] = True
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("db.example.co", 443)


def test_a_changed_address_is_picked_up_after_the_ttl(fake, monkeypatch):
    monkeypatch.setenv("ORCH_DNS_CACHE_TTL_S", "0")
    assert socket.getaddrinfo("db.example.co", 443) == ANSWER
    fake["answer"] = OTHER
    assert socket.getaddrinfo("db.example.co", 443) == OTHER


# ── safety ───────────────────────────────────────────────────────────────────

def test_the_kill_switch_restores_plain_resolution(fake, monkeypatch):
    monkeypatch.setenv("ORCH_DNS_CACHE", "false")
    socket.getaddrinfo("db.example.co", 443)
    socket.getaddrinfo("db.example.co", 443)
    assert fake["n"] == 2


def test_install_is_idempotent(fake):
    before = socket.getaddrinfo
    resolver_cache.install(["db.example.co"])
    resolver_cache.install(["db.example.co"])
    assert socket.getaddrinfo is before, "install() wrapped its own wrapper"


def test_uninstall_restores_the_real_resolver(fake):
    resolver_cache.uninstall()
    assert getattr(socket.getaddrinfo, "__module__", "") != "resolver_cache"


def test_install_never_raises(monkeypatch):
    monkeypatch.setattr(resolver_cache, "add_hosts",
                        lambda hosts: (_ for _ in ()).throw(RuntimeError("boom")))
    assert resolver_cache.install(["x"]) is False


def test_db_installs_it_for_its_own_endpoints():
    """Structural: the whole point is that db.py's hosts are covered."""
    runner = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(runner, "db.py")) as fh:
        src = fh.read()
    assert "resolver_cache.install(" in src
    assert "_install_resolver_cache()" in src
