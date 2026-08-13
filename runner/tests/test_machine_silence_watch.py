"""Proof for the operator directive: "Silence a machine heartbeat: operator alert fires."

The 2026-08-02 incident was that Mac 2's runner died at ~10:28 and nothing told the
operator. fleet_doctor only asserts THIS host is fresh, which by construction can
never catch the host that died. These tests pin the cross-host behaviour.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import machine_silence_watch as msw

NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _row(hostname, minutes_ago, active_tasks=0, runner_id="r1"):
    return {
        "hostname": hostname,
        "last_seen": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
        "active_tasks": active_tasks,
        "runner_id": runner_id,
    }


def _hosts(entries):
    return [e["hostname"] for e in entries]


def test_silent_machine_is_detected():
    rows = [_row("mac1", 1), _row("mac2", 95)]
    verdict = msw.evaluate(rows, now=NOW, self_host="mac1")
    assert _hosts(verdict["silent"]) == ["mac2"]
    assert verdict["silent"][0]["age_minutes"] == 95


def test_fresh_machine_is_not_flagged():
    rows = [_row("mac1", 1), _row("mac2", 5)]
    verdict = msw.evaluate(rows, now=NOW, self_host="mac1")
    assert verdict["silent"] == []
    assert _hosts(verdict["live"]) == ["mac2"]


def test_self_is_never_flagged():
    """The observing host is alive by construction — it is running this code."""
    rows = [_row("mac1", 500)]
    verdict = msw.evaluate(rows, now=NOW, self_host="mac1")
    assert verdict["silent"] == []
    assert verdict["retired"] == []


def test_self_matches_despite_local_suffix():
    rows = [_row("mac1.local", 500)]
    assert msw.evaluate(rows, now=NOW, self_host="mac1")["silent"] == []
    assert msw.evaluate(rows, now=NOW, self_host="mac1.local")["silent"] == []


def test_long_dead_machine_is_retired_not_alerted():
    """A machine retired weeks ago must not alert forever."""
    rows = [_row("mac1", 1), _row("oldbox", 60 * 24 * 9)]
    verdict = msw.evaluate(rows, now=NOW, self_host="mac1")
    assert verdict["silent"] == []
    assert _hosts(verdict["retired"]) == ["oldbox"]


def test_boundary_just_under_threshold_is_live():
    rows = [_row("mac2", 29)]
    verdict = msw.evaluate(rows, now=NOW, self_host="mac1", silence_minutes=30)
    assert verdict["silent"] == []


def test_boundary_just_over_threshold_is_silent():
    rows = [_row("mac2", 31)]
    verdict = msw.evaluate(rows, now=NOW, self_host="mac1", silence_minutes=30)
    assert _hosts(verdict["silent"]) == ["mac2"]


def test_newest_row_per_machine_wins():
    """Stale rows for a machine must not mask a recent heartbeat."""
    rows = [_row("mac2", 300), _row("mac2", 2), _row("mac2", 120)]
    verdict = msw.evaluate(rows, now=NOW, self_host="mac1")
    assert verdict["silent"] == []
    assert _hosts(verdict["live"]) == ["mac2"]


def test_stale_row_does_not_hide_silence():
    rows = [_row("mac2", 300), _row("mac2", 200)]
    verdict = msw.evaluate(rows, now=NOW, self_host="mac1")
    assert _hosts(verdict["silent"]) == ["mac2"]
    assert verdict["silent"][0]["age_minutes"] == 200


def test_rows_without_hostname_or_timestamp_are_ignored():
    rows = [{"hostname": "", "last_seen": NOW.isoformat()},
            {"hostname": "ghost", "last_seen": None},
            {"hostname": "ghost2", "last_seen": "not-a-date"},
            _row("mac2", 90)]
    verdict = msw.evaluate(rows, now=NOW, self_host="mac1")
    assert _hosts(verdict["silent"]) == ["mac2"]


def test_empty_input_is_safe():
    verdict = msw.evaluate([], now=NOW, self_host="mac1")
    assert verdict == {"silent": [], "live": [], "retired": []}


@pytest.mark.parametrize("raw", [
    "2026-08-02T11:00:00Z",
    "2026-08-02 11:00:00+00:00",
    "2026-08-02T11:00:00.123456+00:00",
    "2026-08-02T11:00:00.1234567+00:00",  # 7-digit fraction: Postgres does emit these
    "2026-08-02T11:00:00.12+00:00",
])
def test_timestamp_formats_parse(raw):
    """A parse failure here would silently classify a dead host as absent, not silent."""
    parsed = msw._parse_ts(raw)
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.hour == 11


def test_naive_timestamp_is_treated_as_utc():
    parsed = msw._parse_ts("2026-08-02T11:00:00")
    assert parsed is not None and parsed.tzinfo is not None


def test_check_alerts_operator_on_silence(monkeypatch):
    """End-to-end proof: a silent machine produces exactly one operator alert."""
    sent = []

    class _Alerter:
        @staticmethod
        def alert(pattern, project_id="", detail="", severity=""):
            sent.append((pattern, project_id, severity, detail))
            return True

    monkeypatch.setattr(msw, "error_alerter", _Alerter)
    monkeypatch.setattr(msw.db, "select", lambda *a, **k: [
        _row("mac2", 95),
    ])
    monkeypatch.setattr(msw, "HOST", "mac1")

    result = msw.check(now=NOW)

    assert result["alerted"] == ["mac2"]
    assert len(sent) == 1
    pattern, project_id, severity, detail = sent[0]
    assert pattern == "MACHINE_SILENT"
    assert project_id == "mac2"
    assert severity == "critical"
    assert "95m ago" in detail


def test_check_does_not_alert_when_fleet_healthy(monkeypatch):
    sent = []

    class _Alerter:
        @staticmethod
        def alert(*a, **k):
            sent.append(a)
            return True

    monkeypatch.setattr(msw, "error_alerter", _Alerter)
    monkeypatch.setattr(msw.db, "select", lambda *a, **k: [_row("mac2", 2)])
    monkeypatch.setattr(msw, "HOST", "mac1")

    assert msw.check(now=NOW)["alerted"] == []
    assert sent == []


def test_db_failure_is_reported_not_raised(monkeypatch):
    """A monitoring bug must never take the runner it monitors down."""
    def _boom(*a, **k):
        raise RuntimeError("supabase unreachable")

    monkeypatch.setattr(msw.db, "select", _boom)
    result = msw.check()
    assert "supabase unreachable" in result["error"]
    assert result["silent"] == [] and result["alerted"] == []


def test_alerter_failure_does_not_lose_detection(monkeypatch):
    """Delivery can fail; the silent machine must still be reported."""
    class _Alerter:
        @staticmethod
        def alert(*a, **k):
            raise RuntimeError("smtp down")

    monkeypatch.setattr(msw, "error_alerter", _Alerter)
    monkeypatch.setattr(msw.db, "select", lambda *a, **k: [_row("mac2", 95)])
    monkeypatch.setattr(msw, "HOST", "mac1")

    result = msw.check(now=NOW)
    assert _hosts(result["silent"]) == ["mac2"]
    assert result["alerted"] == []
