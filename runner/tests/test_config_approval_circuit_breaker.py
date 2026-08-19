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
    # 60, not 55. The five entries in the breaker window were not assessed either -- they
    # were attempted and failed. Reporting only the ones after the break under-counted by
    # exactly the breaker width, and "55 of 60" reads as though five got through.
    assert "60 entries unassessed" in out
    assert "5 failed, 55 never attempted" in out


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


# --- a rejection is not an outage --------------------------------------------------------
#
# The breaker's message is a diagnosis: "the control plane is down, NOT these keys." When a
# PostgREST rejection feeds it, that diagnosis is exactly inverted -- the keys ARE the
# problem -- and the cost is not just a wrong log line. The pass aborts, so every remaining
# healthy key goes unassessed; the rejections recur identically next cycle; and the real
# data bug hides inside a message that tells the reader to go look at the network.

import db as _real_db  # noqa: E402


class _RejectingDB(_DB):
    """Fails the named indices the way PostgREST rejects a row it will never accept."""

    def __init__(self, reject_indices=(), rows=None, exc=None):
        super().__init__(rows=rows)
        self.reject_indices = set(reject_indices)
        self.exc = exc or (lambda: _real_db.RequestRejectedError(
            "HTTP 400 on POST /rest/v1/approvals: message=value too long for type "
            "character varying(200)", status=400, payload=None, code="22001"))

    def insert(self, table, values):
        n = len(self.attempts)
        self.attempts.append(values.get("title", ""))
        if n in self.reject_indices:
            raise self.exc()
        return {"id": n}


def test_consecutive_rejections_do_not_trip_the_outage_breaker(monkeypatch):
    """Ten unacceptable values in a row is a data bug, not a network event."""
    db = _RejectingDB(reject_indices=range(10), rows=_rows(20))
    _wire(monkeypatch, db)

    approved, gated = config_approval.sweep()

    assert len(db.attempts) == 20, (
        f"abandoned after {len(db.attempts)} — the ten healthy keys after the bad ones were "
        f"never assessed, and would not be on any future cycle either")
    assert approved + gated == 10


def test_a_rejection_is_not_reported_as_an_outage(monkeypatch, capsys):
    db = _RejectingDB(reject_indices=range(10), rows=_rows(20))
    _wire(monkeypatch, db)

    config_approval.sweep()

    out = capsys.readouterr().out
    assert "control plane is down" not in out, \
        "a PostgREST rejection was diagnosed as a network outage — precisely inverted"


def test_rejections_are_surfaced_as_their_own_permanent_class(monkeypatch, capsys):
    """They never resolve on their own; buried among 'skipped' lines nobody would fix them."""
    db = _RejectingDB(reject_indices=(0, 3), rows=_rows(6))
    _wire(monkeypatch, db)

    config_approval.sweep()

    out = capsys.readouterr().out
    assert "REJECTED" in out
    assert "ORCH_KEY_0" in out and "ORCH_KEY_3" in out, "name the keys that need fixing"
    assert "every cycle" in out


def test_a_rejection_does_not_mask_a_real_outage_that_follows(monkeypatch, capsys):
    """The breaker must still fire on the transient run after an unrelated rejection."""
    class _Mixed(_RejectingDB):
        def insert(self, table, values):
            n = len(self.attempts)
            self.attempts.append(values.get("title", ""))
            if n == 0:
                raise self.exc()
            raise RuntimeError("HTTP Error 522: status code 522")

    db = _Mixed(rows=_rows(40))
    _wire(monkeypatch, db)

    config_approval.sweep()

    assert len(db.attempts) == 6, "1 rejection + 5 transient failures, then abandon"
    assert "control plane is down" in capsys.readouterr().out


def test_a_missing_relation_abandons_immediately_and_says_so(monkeypatch, capsys):
    """No key can succeed and no cycle will change that — 200 requests to relearn it is waste."""
    db = _RejectingDB(
        reject_indices=range(50), rows=_rows(50),
        exc=lambda: _real_db.MissingRelationError("relation 'approvals' does not exist"))
    _wire(monkeypatch, db)

    config_approval.sweep()

    assert len(db.attempts) == 1, "one attempt is enough to learn the table is not there"
    out = capsys.readouterr().out
    assert "schema problem, not an outage" in out
    assert "control plane is down" not in out


def test_unknown_failures_still_take_the_environmental_path(monkeypatch, capsys):
    """The classification is an allowlist. Anything unrecognised keeps the proven behaviour.

    Guessing that a novel exception is permanent would let a real outage burn the full
    per-key timeout budget again, which is the failure the breaker exists to prevent.
    """
    db = _DB(fail_indices=range(30), rows=_rows(30))
    _wire(monkeypatch, db)

    config_approval.sweep()

    assert len(db.attempts) == 5
    assert "control plane is down" in capsys.readouterr().out
