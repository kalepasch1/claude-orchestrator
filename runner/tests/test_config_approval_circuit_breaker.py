"""A control-plane outage must not turn into a wedged main loop.

config_approval.sweep() does one network write per unreviewed fleet_config entry and
swallows each failure individually. That is fail-soft per key but not per PASS: when the
control plane is down, every one of ~60 keys still pays a full request timeout, and the
scheduler runs the whole thing again on the next tick.

Observed on mac-lan 2026-08-19 during a Supabase 522 outage — the runner's stdout stopped
carrying scheduler lines entirely and became nothing but:

    config_approval: skipped ORCH_NATIVE_MODE: HTTP Error 522: status code 522
    config_approval: skipped ORCH_RECOVERY_RESERVED_LANES: HTTP Error 522: <none>
    ... 60 more, every cycle ...

self-deploy stopped firing and the fleet stalled behind an outage it was built to ride out.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config_approval  # noqa: E402


class _DB:
    """Records inserts; fails the ones the test says should fail."""

    def __init__(self, fail_indices=(), rows=None):
        self.fail_indices = set(fail_indices)
        self.rows = rows
        self.attempts = []

    def select(self, table, params=None):
        if table == "fleet_config":
            return list(self.rows)
        return []            # no pending approvals -> nothing is already fingerprinted

    def insert(self, table, values):
        n = len(self.attempts)
        self.attempts.append(values.get("title", ""))
        if n in self.fail_indices:
            raise RuntimeError("HTTP Error 522: status code 522")
        return {"id": n}


def _rows(n):
    return [{"key": f"ORCH_KEY_{i}", "value": str(i), "note": ""} for i in range(n)]


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(config_approval, "ENABLED", True)
    monkeypatch.setattr(config_approval, "CONSECUTIVE_ERROR_LIMIT", 5)


def _wire(monkeypatch, db):
    monkeypatch.setattr(config_approval, "db", db)


def test_a_total_outage_abandons_the_pass_instead_of_paying_every_timeout(monkeypatch, capsys):
    db = _DB(fail_indices=range(60), rows=_rows(60))
    _wire(monkeypatch, db)

    approved, gated = config_approval.sweep()

    assert (approved, gated) == (0, 0)
    assert len(db.attempts) == 5, (
        f"stopped after {len(db.attempts)} writes, not 60 — the outage costs one breaker's "
        f"worth of timeouts per cycle, not sixty")
    out = capsys.readouterr().out
    assert "consecutive write failures" in out
    assert "55 entries unassessed" in out


def test_the_breaker_does_not_trip_on_scattered_failures(monkeypatch):
    """One bad key is not an outage — the rest of the pass must still run."""
    db = _DB(fail_indices=(0, 2, 4, 6, 8), rows=_rows(10))
    _wire(monkeypatch, db)

    approved, gated = config_approval.sweep()

    assert len(db.attempts) == 10, "every entry must still be attempted"
    assert approved + gated == 5


def test_a_success_resets_the_counter(monkeypatch):
    """Four failures, a success, four more failures: below the limit either side."""
    db = _DB(fail_indices=(0, 1, 2, 3, 5, 6, 7, 8), rows=_rows(10))
    _wire(monkeypatch, db)

    config_approval.sweep()

    assert len(db.attempts) == 10


def test_the_healthy_path_is_unchanged(monkeypatch):
    db = _DB(rows=_rows(12))
    _wire(monkeypatch, db)

    approved, gated = config_approval.sweep()

    assert len(db.attempts) == 12
    assert approved + gated == 12


def test_the_breaker_names_the_cause_so_the_log_is_actionable(monkeypatch, capsys):
    db = _DB(fail_indices=range(20), rows=_rows(20))
    _wire(monkeypatch, db)

    config_approval.sweep()

    out = capsys.readouterr().out
    assert "control plane is down, not these keys" in out
    assert "522" in out, "the underlying error must survive into the summary"
    assert out.count("config_approval: skipped") == 5, "and the log must not be flooded"


def test_the_limit_is_configurable(monkeypatch):
    monkeypatch.setattr(config_approval, "CONSECUTIVE_ERROR_LIMIT", 2)
    db = _DB(fail_indices=range(30), rows=_rows(30))
    _wire(monkeypatch, db)

    config_approval.sweep()

    assert len(db.attempts) == 2
