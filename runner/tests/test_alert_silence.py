#!/usr/bin/env python3
"""Silencing an alert rule must actually silence it.

THE DEFECT
----------
`silence()` wrote `silenced_until` onto the firing alert dict and nothing anywhere read
it — not `evaluate()`, not `dispatch_critical()`, not the inbox write. Silencing was a
no-op that returned True, which is worse than not existing: an operator who silenced a
noisy rule believed the problem was handled and kept getting paged.

Two consequences beyond the obvious one:

  * silence() returned False and did nothing at all unless the rule was ALREADY firing,
    so a rule could not be pre-silenced ahead of planned maintenance — the main thing
    anyone wants from silencing.
  * the silence lived on the firing alert, so it was discarded the moment the alert
    resolved. A flapping rule re-notified on its very next transition, which is the
    notification fatigue the module docstring says silencing exists to prevent.
"""
import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alert_rules_engine as engine  # noqa: E402

RULE = {
    "id": "test_rule",
    "name": "Test rule",
    "metric": "widgets",
    "operator": "gt",
    "threshold": 10,
    "severity": "warning",
}


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    engine._STATE["firing"] = {}
    engine._STATE["silenced"] = {}
    engine._STATE["resolved"] = 0
    engine._STATE["evaluations"] = 0
    engine._STATE["suppressed"] = 0
    # Never touch the real inbox or notifier from a unit test.
    monkeypatch.setattr(engine, "dispatch_critical", lambda *a, **k: False)
    yield
    engine._STATE["firing"] = {}
    engine._STATE["silenced"] = {}


def fire(value=99):
    return engine.evaluate(rules=[RULE], metrics={"widgets": value})


def clear(value=0):
    return engine.evaluate(rules=[RULE], metrics={"widgets": value})


# ── the regression ──────────────────────────────────────────────────────────

def test_an_unsilenced_rule_fires():
    events = fire()
    assert [e["event"] for e in events] == ["firing"]


def test_a_silenced_rule_emits_no_event():
    """The whole defect: this used to return a firing event regardless."""
    engine.silence("test_rule", minutes=30)
    assert fire() == []


def test_a_silenced_rule_is_still_evaluated():
    """Silencing must suppress the NOTIFICATION, not the monitoring."""
    engine.silence("test_rule", minutes=30)
    fire()
    assert "test_rule" in engine._STATE["firing"]
    assert engine._STATE["firing"]["test_rule"]["suppressed"] is True
    assert engine.stats()["suppressed"] == 1


def test_a_suppressed_alert_does_not_announce_its_own_resolution():
    """'Resolved' would otherwise be the first thing anyone heard about it."""
    engine.silence("test_rule", minutes=30)
    fire()
    assert clear() == []
    assert engine.stats()["resolved"] == 1


def test_silencing_can_happen_before_the_rule_ever_fires():
    """Pre-silencing for maintenance. This used to return False and do nothing."""
    assert engine.silence("test_rule", minutes=30) is True
    assert fire() == []


def test_a_silence_survives_the_alert_resolving():
    """The flapping case: the silence used to die with the firing episode."""
    engine.silence("test_rule", minutes=30)
    fire()
    clear()
    assert engine.is_silenced("test_rule") is True
    assert fire() == []


# ── expiry ──────────────────────────────────────────────────────────────────

def test_a_silence_expires_and_the_rule_fires_again():
    engine.silence("test_rule", minutes=30)
    engine._STATE["silenced"]["test_rule"] = (
        datetime.datetime.utcnow() - datetime.timedelta(minutes=1)).isoformat() + "Z"
    assert engine.is_silenced("test_rule") is False
    assert [e["event"] for e in fire()] == ["firing"]


def test_an_expired_silence_is_cleared_from_state():
    engine._STATE["silenced"]["test_rule"] = (
        datetime.datetime.utcnow() - datetime.timedelta(minutes=1)).isoformat() + "Z"
    engine.is_silenced("test_rule")
    assert "test_rule" not in engine._STATE["silenced"]


def test_an_unparseable_expiry_does_not_silence_forever():
    """Fail-soft must fail toward alerting, never toward silence."""
    engine._STATE["silenced"]["test_rule"] = "not-a-timestamp"
    assert engine.is_silenced("test_rule") is False
    assert [e["event"] for e in fire()] == ["firing"]


def test_silenced_rules_lists_only_live_silences():
    engine.silence("live_rule", minutes=30)
    engine._STATE["silenced"]["dead_rule"] = (
        datetime.datetime.utcnow() - datetime.timedelta(minutes=1)).isoformat() + "Z"
    assert list(engine.silenced_rules()) == ["live_rule"]


# ── lifting a silence ───────────────────────────────────────────────────────

def test_unsilence_restores_alerting():
    engine.silence("test_rule", minutes=30)
    assert engine.unsilence("test_rule") is True
    assert [e["event"] for e in fire()] == ["firing"]


def test_unsilence_reports_when_nothing_was_silenced():
    assert engine.unsilence("test_rule") is False


def test_zero_minutes_lifts_the_silence():
    engine.silence("test_rule", minutes=30)
    engine.silence("test_rule", minutes=0)
    assert engine.is_silenced("test_rule") is False


# ── fail-soft on input ──────────────────────────────────────────────────────

def test_an_empty_rule_id_is_refused():
    assert engine.silence("") is False
    assert engine.silence(None) is False


def test_a_garbage_duration_falls_back_to_the_default():
    assert engine.silence("test_rule", minutes="soon") is True
    assert engine.is_silenced("test_rule") is True


def test_the_default_duration_is_used_when_none_is_given():
    assert engine.silence("test_rule") is True
    assert engine.is_silenced("test_rule") is True


# ── other rules are unaffected ──────────────────────────────────────────────

def test_silencing_one_rule_does_not_silence_another():
    other = dict(RULE, id="other_rule", name="Other")
    engine.silence("test_rule", minutes=30)
    events = engine.evaluate(rules=[RULE, other], metrics={"widgets": 99})
    assert [e["rule_id"] for e in events] == ["other_rule"]


def test_stats_exposes_silence_counters():
    engine.silence("test_rule", minutes=30)
    fire()
    s = engine.stats()
    assert s["silenced"] == 1 and s["suppressed"] == 1


def test_firing_alerts_shows_the_silence_on_a_live_alert():
    fire()
    engine.silence("test_rule", minutes=30)
    assert engine.firing_alerts()[0]["silenced_until"]
