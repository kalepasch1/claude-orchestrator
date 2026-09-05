#!/usr/bin/env python3
"""A per-process DNS cache for the control plane, with stale-if-error.

WHY THIS EXISTS
---------------
db.py calls urllib.request.urlopen() once per request, which opens a new connection and
therefore performs a NEW DNS RESOLUTION every time. Dozens of orchestrator processes
each doing that, several times a second, is enough to exhaust the macOS resolver.
Measured across the fleet's own .err logs on 2026-09-02:

    urlopen error [Errno 8] nodename nor servname provided   5,706
    urlopen error [Errno 61] Connection refused                174
    urlopen error [Errno 60] Operation timed out              110
    urlopen error timed out                                     90
    urlopen error [Errno 54] Connection reset by peer           88
    control-plane circuit breaker trips                          99

Errno 8 is not the network being down. It is the host failing to RESOLVE a name it
resolves in 3ms when asked calmly -- checked five times in a row while 177 of these
failures were being logged in a twenty-minute window:

    ok 4ms   ok 3ms   ok 3ms   ok 3ms   ok 3ms

Every one of those failures costs a retry, and eight in a row open the circuit breaker
for 180 seconds, during which the whole fleet fails its control-plane calls fast. That
is a self-inflicted outage caused by asking the same question ten thousand times.

DESIGN
------
* SCOPED, not global. Only hostnames this module is told about are cached; every other
  getaddrinfo call passes straight through untouched. A process-wide DNS override is a
  big hammer and it should land on exactly one nail.
* STALE-IF-ERROR is the point, not the caching. A resolver failure for a host we
  successfully resolved minutes ago is answered from the last known-good result instead
  of becoming a TransientDBError. If the address really has changed, the connection
  fails and db.py's existing endpoint failover handles it -- which is the same path it
  would take for any dead endpoint.
* Never raises on its own account. Any internal error falls back to the real
  getaddrinfo, so the worst case is exactly today's behaviour.
"""
import os
import socket
import threading
import time

#: How long a successful answer is served without re-asking the resolver.
DEFAULT_TTL_S = 300.0
#: How long a stale answer may be served after a resolver FAILURE. Deliberately much
#: longer than the TTL: the alternative during a resolver wobble is no answer at all.
DEFAULT_STALE_S = 3600.0

_LOCK = threading.Lock()
_CACHE = {}          # (host, port, family, type, proto, flags) -> (at, result)
_HOSTS = set()       # hostnames this cache is allowed to answer for
_INSTALLED = [False]
_REAL = [None]
_STATS = {"hits": 0, "misses": 0, "stale_served": 0, "passthrough": 0}


def enabled():
    return os.environ.get("ORCH_DNS_CACHE", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def ttl_s():
    try:
        return max(0.0, float(os.environ.get("ORCH_DNS_CACHE_TTL_S", DEFAULT_TTL_S)))
    except (TypeError, ValueError):
        return DEFAULT_TTL_S


def stale_s():
    try:
        return max(0.0, float(os.environ.get("ORCH_DNS_STALE_S", DEFAULT_STALE_S)))
    except (TypeError, ValueError):
        return DEFAULT_STALE_S


def stats():
    with _LOCK:
        return dict(_STATS)


def reset():
    """Forget everything. For tests."""
    with _LOCK:
        _CACHE.clear()
        for key in _STATS:
            _STATS[key] = 0


def add_hosts(hosts):
    """Allow this cache to answer for these hostnames."""
    with _LOCK:
        for host in hosts or ():
            name = str(host or "").strip().lower()
            if name:
                _HOSTS.add(name)


def _cached(key, now):
    entry = _CACHE.get(key)
    if not entry:
        return None, None
    at, result = entry
    return (now - at), result


def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    real = _REAL[0] or socket.getaddrinfo
    name = str(host or "").strip().lower()
    if not enabled() or name not in _HOSTS:
        with _LOCK:
            _STATS["passthrough"] += 1
        return real(host, port, family, type, proto, flags)
    key = (name, port, family, type, proto, flags)
    now = time.time()
    with _LOCK:
        age, result = _cached(key, now)
        if result is not None and age is not None and age <= ttl_s():
            _STATS["hits"] += 1
            return result
    try:
        answer = real(host, port, family, type, proto, flags)
    except Exception:
        with _LOCK:
            age, result = _cached(key, now)
            if result is not None and age is not None and age <= stale_s():
                _STATS["stale_served"] += 1
                return result
        raise
    with _LOCK:
        _CACHE[key] = (now, answer)
        _STATS["misses"] += 1
    return answer


def install(hosts=()):
    """Take over socket.getaddrinfo for `hosts`. Idempotent; never raises."""
    try:
        add_hosts(hosts)
        if _INSTALLED[0]:
            return True
        _REAL[0] = socket.getaddrinfo
        socket.getaddrinfo = _getaddrinfo
        _INSTALLED[0] = True
        return True
    except Exception:
        return False


def uninstall():
    """Restore the real resolver. For tests."""
    if _INSTALLED[0] and _REAL[0] is not None:
        socket.getaddrinfo = _REAL[0]
    _INSTALLED[0] = False
    _REAL[0] = None
