"""An open breaker must never be mistaken for "another writer already did it".

db.insert() and db.update() deliberately swallow TransientDBError, because the transient
case they were written for is HTTP 409: a duplicate key, or the other Mac racing the same
row. In both, the write intent IS satisfied by somebody, so returning None is correct and
stops a 409 from terminally BLOCKING a task (that bug once froze 200+ tasks).

The circuit breaker added during the 2026-08-19 outage raised that same exception type from
_req BEFORE any network attempt. Under that code, for the whole cooldown window:

    db.update("tasks", {"id": X}, {"state": "MERGED"})   -> None, no network, no log line
    db.insert("outcomes", {...})                         -> None, no network, no log line

Every caller read None as success. Task states, outcome rows and lease heartbeats would be
dropped silently against a control plane that might already be healthy again -- a strictly
worse failure than the outage itself, because it is invisible.

ControlPlaneDown separates the two. It subclasses TransientDBError so every environmental
classifier (periodic, crash_loop_detector) keeps treating it as "skip this cycle", while
insert/update re-raise it instead of swallowing.
"""
import os
import socket
import sys
import threading
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


def _http_error(code):
    return urllib.error.HTTPError("http://x", code, f"status {code}", {}, None)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(db, "URL", "https://primary.example")
    monkeypatch.setattr(db, "KEY", "test-key")
    monkeypatch.setenv("ORCH_SUPABASE_FALLBACK_URLS", "")
    monkeypatch.setattr(db, "_ACTIVE_BASE", {"url": None})
    monkeypatch.setattr(db, "_save_active_base", lambda url: None)
    monkeypatch.setattr(db, "_BREAKER",
                        {"consecutive": 0, "open_until": 0.0, "trips": 0, "probing": False})
    monkeypatch.setattr(db, "DB_BREAKER_ENABLED", True)
    monkeypatch.setattr(db, "DB_BREAKER_THRESHOLD", 3)
    monkeypatch.setattr(db, "DB_BREAKER_COOLDOWN_S", 60.0)
    monkeypatch.setattr(db, "HTTP_RETRIES", 0)


def _open_the_breaker(monkeypatch):
    """Drive real unreachable failures until the breaker latches open."""
    def dead(req, timeout=None):
        raise socket.timeout("timed out")
    monkeypatch.setattr(db.urllib.request, "urlopen", dead)
    for _ in range(db.DB_BREAKER_THRESHOLD):
        with pytest.raises(db.TransientDBError):
            db._req("GET", "/rest/v1/tasks")
    assert db.breaker_state()["open_until"] > 0


def _expire_the_cooldown():
    """Move the deadline into the past WITHOUT closing the breaker.

    open_until is doing double duty: it is both the deadline and the latch (0.0 means
    'closed'). So zeroing it does not simulate expiry, it simulates recovery -- every caller
    is then admitted because the breaker is simply shut. Expiry is a deadline that has
    already passed but is still non-zero, which is what makes the election reachable.
    """
    db._BREAKER["open_until"] = db.time.monotonic() - 1.0


# --- the type itself --------------------------------------------------------------------

def test_control_plane_down_is_a_transient_db_error():
    """Subclassing is load-bearing: periodic/crash_loop_detector classify on TransientDBError.

    If it were a bare Exception, an outage would look like a code bug to every one of them
    and the crash-loop detector would start disabling healthy jobs.
    """
    assert issubclass(db.ControlPlaneDown, db.TransientDBError)


def test_the_breaker_raises_the_specific_type_not_the_generic_one(monkeypatch):
    _open_the_breaker(monkeypatch)

    with pytest.raises(db.ControlPlaneDown):
        db._req("GET", "/rest/v1/tasks")


def test_a_real_409_is_still_the_plain_transient_type(monkeypatch):
    """The distinction only helps if a genuine 409 does NOT arrive as ControlPlaneDown."""
    def conflicting(req, timeout=None):
        raise _http_error(409)
    monkeypatch.setattr(db.urllib.request, "urlopen", conflicting)

    with pytest.raises(db.TransientDBError) as caught:
        db._req("POST", "/rest/v1/outcomes", body={"id": "x"})
    assert not isinstance(caught.value, db.ControlPlaneDown)


# --- the writes -------------------------------------------------------------------------

def test_insert_raises_instead_of_silently_returning_none(monkeypatch):
    _open_the_breaker(monkeypatch)

    with pytest.raises(db.ControlPlaneDown):
        db.insert("outcomes", {"task_id": "t1", "result": "ok"})


def test_update_raises_instead_of_silently_returning_none(monkeypatch):
    """The one that mattered most: a dropped state transition strands the task forever."""
    _open_the_breaker(monkeypatch)

    with pytest.raises(db.ControlPlaneDown):
        db.update("tasks", {"id": "t1"}, {"state": "MERGED"})


def test_upsert_insert_also_raises(monkeypatch):
    """upsert takes its own branch inside the handler; it must not swallow either."""
    _open_the_breaker(monkeypatch)

    with pytest.raises(db.ControlPlaneDown):
        db.insert("outcomes", {"task_id": "t1"}, upsert=True)


def test_a_real_409_on_update_is_still_swallowed(monkeypatch):
    """Regression guard for the behaviour the new branch must NOT have broken.

    A concurrent-writer 409 has to keep returning None -- that swallow is what stopped
    "runner exception: HTTP 409 conflict" from terminally BLOCKING 200+ racing tasks.
    """
    def conflicting(req, timeout=None):
        raise _http_error(409)
    monkeypatch.setattr(db.urllib.request, "urlopen", conflicting)

    assert db.update("tasks", {"id": "t1"}, {"state": "MERGED"}) is None


# --- half-open election -----------------------------------------------------------------

def test_only_one_caller_is_admitted_when_the_cooldown_expires(monkeypatch):
    """Releasing every waiting thread at once is a thundering herd, not a probe.

    The runner is many-threaded; without the election, cooldown expiry sent one request per
    live thread straight at an origin that had just been failing.
    """
    _open_the_breaker(monkeypatch)
    _expire_the_cooldown()

    admitted = [db._breaker_blocks() is False for _ in range(20)]

    assert admitted.count(True) == 1, "exactly one prober, not a herd"


def test_the_election_is_thread_safe(monkeypatch):
    """_breaker_blocks() mutates shared state; without the lock two threads both win."""
    _open_the_breaker(monkeypatch)
    _expire_the_cooldown()

    results = []
    barrier = threading.Barrier(8)

    def race():
        barrier.wait()
        results.append(db._breaker_blocks())

    threads = [threading.Thread(target=race) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(False) == 1, f"exactly one prober expected, got {results}"


def test_a_failed_probe_re_opens_and_counts_a_new_trip(monkeypatch):
    """trips is the outage's only signal to a human. It read 1 for eight hours.

    open_until was compared against itself, so a re-open after a failed half-open probe was
    never counted and the stderr line was emitted exactly once for the life of the process.
    """
    _open_the_breaker(monkeypatch)
    assert db.breaker_state()["trips"] == 1

    for _ in range(3):
        _expire_the_cooldown()
        with pytest.raises(db.TransientDBError):
            db._req("GET", "/rest/v1/tasks")       # the elected probe fails for real

    assert db.breaker_state()["trips"] == 4, "each failed probe is a fresh trip"


def test_a_successful_probe_clears_probing_so_the_next_trip_can_elect_again(monkeypatch):
    """A stuck `probing` flag means nobody is ever elected again -- a permanent outage."""
    _open_the_breaker(monkeypatch)
    _expire_the_cooldown()
    assert db._breaker_blocks() is False           # elected

    db._breaker_record_answer()

    assert db.breaker_state()["probing"] is False
    assert db.breaker_state()["open_until"] == 0.0
    assert db.breaker_state()["consecutive"] == 0


def test_the_cooldown_default_covers_a_supabase_restart():
    """60s was shorter than a project restart, so the fleet re-stormed mid-recovery.

    Read from the source, not the module attribute: the autouse fixture pins the attribute
    to 60.0 so the other tests do not sleep, which would make an attribute assertion pass
    vacuously.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db.py")
    with open(src) as fh:
        line = [l for l in fh if l.startswith("DB_BREAKER_COOLDOWN_S")][0]
    assert '"180"' in line, f"default cooldown regressed: {line.strip()}"
