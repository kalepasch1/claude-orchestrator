"""Proof for the durable compliance event router.

The claim under test is narrow and worth stating precisely, because "exactly-once"
is usually asserted where only at-least-once is delivered:

    An effect recorded through `ctx.record()` lands exactly once, even if the
    process dies between the handler returning and the offset being committed.

That window is the one that breaks naive implementations. The test drives it
directly via `_crash_after_handler`, then reopens the database from disk — the
same thing a restarted process does — and redelivers.

Every test points the router at a tmp_path DB, so nothing here touches
.runtime/compliance_router.db.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import compliance_event_router as router
from compliance_event_stream import ComplianceEvent, ComplianceEventStream, ComplianceEventType


@pytest.fixture(autouse=True)
def _isolated_router(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_COMPLIANCE_ROUTER_DB", str(tmp_path / "router.db"))
    router.reset_connection()
    yield
    router.reset_connection()


def _restart():
    """Model a process restart: drop every in-memory handle, reopen from disk."""
    router.reset_connection()


def _publish(n=3, kind="filing.submitted", app="app-a"):
    return [
        router.publish(kind=kind, app_id=app, payload={"i": i}, event_id=f"evt-{i}")
        for i in range(n)
    ]


# ── outbox ───────────────────────────────────────────────────────────────────

def test_publish_is_durable_and_ordered():
    _publish(3)
    _restart()
    log = router.replay()
    assert [e["event_id"] for e in log] == ["evt-0", "evt-1", "evt-2"]
    assert [e["seq"] for e in log] == sorted(e["seq"] for e in log)
    assert log[0]["payload"] == {"i": 0}


def test_publish_is_idempotent_on_the_evidence_bus_key():
    first = router.publish(kind="filing.submitted", app_id="app-a", payload={"i": 1}, event_id="evt-1")
    second = router.publish(kind="filing.submitted", app_id="app-a", payload={"i": 1}, event_id="evt-1")
    assert first["duplicate"] is False and second["duplicate"] is True
    assert second["seq"] == first["seq"]
    assert len(router.replay()) == 1


def test_replay_is_deterministic_and_read_only():
    _publish(4)
    once = router.replay(from_seq=1)
    twice = router.replay(from_seq=1)
    assert once == twice
    assert [e["event_id"] for e in once] == ["evt-1", "evt-2", "evt-3"]
    assert router.offset("auditor") == 0  # replay must not move any consumer


# ── offsets ──────────────────────────────────────────────────────────────────

def test_offset_survives_restart_and_resumes():
    _publish(3)
    seen: list[str] = []

    def handler(event, ctx):
        seen.append(event["event_id"])
        ctx.record(f"seen:{event['event_id']}")

    router.deliver("c1", handler, limit=2)
    assert seen == ["evt-0", "evt-1"]
    at = router.offset("c1")

    _restart()
    assert router.offset("c1") == at        # read back from disk, not memory
    router.deliver("c1", handler)
    assert seen == ["evt-0", "evt-1", "evt-2"]


def test_consumers_have_independent_offsets():
    _publish(2)
    a: list[str] = []
    b: list[str] = []
    router.deliver("a", lambda e, ctx: a.append(e["event_id"]))
    assert router.offset("b") == 0
    router.deliver("b", lambda e, ctx: b.append(e["event_id"]))
    assert a == b == ["evt-0", "evt-1"]


# ── exactly-once effects ─────────────────────────────────────────────────────

def test_effect_lands_exactly_once_across_a_crash_and_restart():
    """The core claim. Crash after the handler, restart, redeliver."""
    _publish(1)
    calls: list[str] = []

    def handler(event, ctx):
        calls.append(event["event_id"])
        ctx.record("applied", {"event": event["event_id"]})

    with pytest.raises(BaseException):
        router.deliver("c1", handler, _crash_after_handler=True)

    # The handler ran, but nothing committed.
    assert calls == ["evt-0"]
    assert router.offset("c1") == 0
    assert router.effects("c1") == []

    _restart()
    router.deliver("c1", handler)

    # The handler ran a second time — delivery is at-least-once and says so.
    assert calls == ["evt-0", "evt-0"]
    # The EFFECT landed once. That is the guarantee.
    recorded = router.effects("c1")
    assert len(recorded) == 1
    assert recorded[0]["effect_key"] == "applied"
    assert router.offset("c1") > 0


def test_record_dedupes_across_different_events():
    """Two events meaning the same thing converge on one effect.

    This is the ordinary case — a `filing.changed` retry and the original both
    resolving to "filing X is current" — and it is why `record` keys on the
    effect, not on the event.
    """
    _publish(2)
    outcomes: list[bool] = []
    router.deliver("c1", lambda e, ctx: outcomes.append(ctx.record("filing:X:current")))
    assert outcomes == [True, False]
    assert len(router.effects("c1")) == 1
    assert router.offset("c1") > 0


def test_a_committed_delivery_is_never_handled_twice():
    """If the offset lags a committed delivery, redelivery must skip the handler."""
    _publish(1)
    calls: list[str] = []
    router.deliver("c1", lambda e, ctx: calls.append(e["event_id"]))
    assert calls == ["evt-0"]

    # Rewind only the offset — the state a crash between the two writes would
    # leave if they were not in one transaction.
    conn = router._connect()
    conn.execute("UPDATE consumer_offsets SET seq = 0 WHERE consumer = 'c1'")
    _restart()

    router.deliver("c1", lambda e, ctx: calls.append(e["event_id"]))
    assert calls == ["evt-0"]                # handler not re-run
    assert router.offset("c1") > 0           # offset repaired


# ── retry and dead-letter ────────────────────────────────────────────────────

def test_failed_handler_is_retried_and_does_not_advance_the_offset():
    _publish(2)
    attempts = {"n": 0}

    def flaky(event, ctx):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        ctx.record(f"ok:{event['event_id']}")

    r1 = router.deliver("c1", flaky, max_attempts=5)
    assert r1["failed"] == 1 and r1["delivered"] == 0
    assert router.offset("c1") == 0          # a failure must not skip the event

    router.deliver("c1", flaky, max_attempts=5)
    r3 = router.deliver("c1", flaky, max_attempts=5)
    assert r3["delivered"] >= 1
    assert [e["effect_key"] for e in router.effects("c1")] == ["ok:evt-0", "ok:evt-1"]


def test_retry_state_survives_restart():
    _publish(1)

    def always_fails(event, ctx):
        raise RuntimeError("still broken")

    router.deliver("c1", always_fails, max_attempts=3)
    _restart()
    router.deliver("c1", always_fails, max_attempts=3)
    _restart()
    result = router.deliver("c1", always_fails, max_attempts=3)

    # Attempts accumulated across three separate "processes", so the third
    # exhausts the budget rather than restarting the count each time.
    assert result["dead_lettered"] == 1
    letters = router.dead_letters("c1")
    assert len(letters) == 1 and letters[0]["attempts"] == 3
    assert "still broken" in letters[0]["error"]


def test_a_poisoned_event_does_not_wedge_the_stream():
    _publish(3)
    handled: list[str] = []

    def poison_on_first(event, ctx):
        if event["event_id"] == "evt-0":
            raise ValueError("poison")
        handled.append(event["event_id"])
        ctx.record(event["event_id"])

    for _ in range(4):
        router.deliver("c1", poison_on_first, max_attempts=3)

    assert [d["event_id"] for d in router.dead_letters("c1")] == ["evt-0"]
    assert handled == ["evt-1", "evt-2"]     # the stream moved on past the poison


def test_ordering_is_preserved_while_an_event_is_retrying():
    _publish(3)
    handled: list[str] = []
    fail_once = {"done": False}

    def handler(event, ctx):
        if event["event_id"] == "evt-0" and not fail_once["done"]:
            fail_once["done"] = True
            raise RuntimeError("first attempt fails")
        handled.append(event["event_id"])

    router.deliver("c1", handler, max_attempts=5)
    assert handled == []                     # evt-1/evt-2 must not jump the queue
    router.deliver("c1", handler, max_attempts=5)
    assert handled == ["evt-0", "evt-1", "evt-2"]


def test_requeue_dead_letters_replays_them_in_order():
    _publish(2)
    broken = {"yes": True}

    def handler(event, ctx):
        if broken["yes"]:
            raise RuntimeError("down")
        ctx.record(event["event_id"])

    for _ in range(6):
        router.deliver("c1", handler, max_attempts=2)
    assert len(router.dead_letters("c1")) == 2

    broken["yes"] = False
    assert router.requeue_dead_letters("c1") == 2
    assert router.dead_letters("c1") == []

    router.deliver("c1", handler)
    assert [e["effect_key"] for e in router.effects("c1")] == ["evt-0", "evt-1"]


# ── wiring: the stream actually uses the router ──────────────────────────────

def test_stream_publish_writes_the_durable_outbox(monkeypatch):
    monkeypatch.setattr("evidence_bus.append", lambda *a, **k: {"persisted": True})
    stream = ComplianceEventStream()
    stream.publish(ComplianceEvent(ComplianceEventType.RISK_SCORE_CHANGED, "app-a", {"new": 20}, "tenant-a"))

    _restart()
    log = stream.history()
    assert len(log) == 1
    assert log[0]["kind"] == "risk.score_changed"
    assert log[0]["tenant_id"] == "tenant-a"
    assert log[0]["payload"] == {"new": 20}


def test_durable_consumer_resumes_after_restart_where_subscribe_would_lose_it(monkeypatch):
    monkeypatch.setattr("evidence_bus.append", lambda *a, **k: {"persisted": True})
    stream = ComplianceEventStream()
    stream.publish(ComplianceEvent(ComplianceEventType.FILING_SUBMITTED, "app-a", {"n": 1}))
    stream.publish(ComplianceEvent(ComplianceEventType.FILING_SUBMITTED, "app-a", {"n": 2}))

    _restart()

    # A NEW stream object: in-process subscribers and _history are gone, exactly
    # as they would be in a fresh process. The durable consumer still catches up.
    fresh = ComplianceEventStream()
    assert fresh.recent() == []
    seen: list[int] = []
    fresh.register_durable_consumer("reporter", lambda e, ctx: seen.append(e["payload"]["n"]))
    fresh.drain()
    assert seen == [1, 2]

    fresh.drain()
    assert seen == [1, 2]                    # already-delivered events do not repeat


def test_in_process_subscribers_still_work():
    """The durable path is additive; existing callers must not break."""
    received = []
    stream = ComplianceEventStream()
    stream.subscribe(ComplianceEventType.RISK_SCORE_CHANGED, received.append)
    stream.publish(ComplianceEvent(ComplianceEventType.RISK_SCORE_CHANGED, "app-a", {"new": 20}, "tenant-a"))
    assert received[0].app_id == "app-a"


def test_router_failure_does_not_break_local_delivery(monkeypatch):
    """Fail-soft: an unavailable outbox must not stop in-process fan-out."""
    monkeypatch.setattr(router, "publish", lambda **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    received = []
    stream = ComplianceEventStream()
    stream.subscribe("*", received.append)
    stream.publish(ComplianceEvent(ComplianceEventType.INCIDENT_REPORTED, "app-a", {}))
    assert len(received) == 1


def test_stats_reports_the_durable_state():
    _publish(2)
    router.deliver("c1", lambda e, ctx: ctx.record(e["event_id"]))
    s = router.stats()
    assert s["events"] == 2 and s["consumers"] == 1 and s["effects"] == 2
