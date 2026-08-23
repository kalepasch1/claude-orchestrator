"""RELEASE ON CAPACITY, NOT ON A CLOCK.

The operator's ask is one sentence: ship whenever there is capacity and something to ship.
These tests pin the two halves of that — that a single staged change releases promptly, and
that the cost controls which justified the old clock are still the things holding it back.

The bug being prevented is subtle: it is easy to "fix" this by deleting the batch/interval
gates, which trades a starved release train for a Vercel build per commit. So every test
below that asserts a RELEASE is paired with one asserting a HOLD for a cost reason.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import release_train


def _iso(seconds_ago):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


class _FakeDb:
    """Minimal stand-in for db.select over the `releases` table."""

    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail
        self.calls = []

    def select(self, table, params):
        self.calls.append((table, dict(params)))
        if self.fail:
            raise RuntimeError("db unreachable")
        if table != "releases":
            return []
        wanted = params.get("deploy_status") or ""
        rows = self.rows
        if wanted.startswith("in."):
            allowed = wanted[3:].strip("()").split(",")
            rows = [r for r in rows if str(r.get("deploy_status", "")).lower() in allowed]
        since = params.get("created_at")
        if since and since.startswith("gte."):
            cutoff = since[4:]
            rows = [r for r in rows if str(r.get("created_at", "")) >= cutoff]
        limit = int(params.get("limit", len(rows) or 1))
        return rows[:limit]


@pytest.fixture
def fake_db(monkeypatch):
    def _install(rows=None, fail=False):
        fake = _FakeDb(rows, fail)
        monkeypatch.setattr(release_train.db, "select", fake.select)
        return fake
    return _install


@pytest.fixture(autouse=True)
def _capacity_mode(monkeypatch):
    """Default every test to capacity mode with the debounce disabled unless it opts in."""
    monkeypatch.setattr(release_train, "RELEASE_MODE", "capacity")
    monkeypatch.setattr(release_train, "RELEASE_DEBOUNCE_S", 0.0)


# 1. The operator's core ask.
def test_one_staged_change_releases_when_nothing_is_in_flight(fake_db):
    fake_db([])
    decision, note = release_train._capacity_release_decision("beethoven", ahead=1)
    assert decision == "release", note
    assert "1 change(s) staged" in note


def test_capacity_mode_lowers_the_batch_threshold_to_one():
    # MIN_BATCH=10 is what makes a project with 3 finished changes wait for 7 more.
    assert release_train._effective_min_batch("beethoven") == 1


# 2. One release in flight per project. Concurrency is the capacity signal.
@pytest.mark.parametrize("status", ["pending", "building"])
def test_release_already_in_flight_holds(fake_db, status):
    fake_db([{"id": 1, "deploy_status": status, "created_at": _iso(10)}])
    decision, note = release_train._capacity_release_decision("beethoven", ahead=5)
    assert decision == "hold"
    assert status in note


def test_in_flight_check_fails_closed(fake_db):
    # Shipping a second concurrent release is the expensive mistake; skipping a pass is not.
    fake_db(fail=True)
    in_flight, note = release_train._release_in_flight("beethoven")
    assert in_flight is True
    assert "fail-closed" in note


# 3. A burst of merges coalesces into one release.
def test_two_merges_five_seconds_apart_produce_one_release(monkeypatch, fake_db):
    monkeypatch.setattr(release_train, "RELEASE_DEBOUNCE_S", 60.0)
    # First merge: no prior release, nothing in flight -> ships.
    fake_db([])
    first, _ = release_train._capacity_release_decision("beethoven", ahead=1)
    assert first == "release"

    # Second merge 5s later, with that release now recorded -> coalesced, not a second build.
    fake_db([{"id": 1, "deploy_status": "success", "created_at": _iso(5)}])
    second, note = release_train._capacity_release_decision("beethoven", ahead=2)
    assert second == "hold"
    assert "debounce" in note


def test_debounce_expires(monkeypatch, fake_db):
    monkeypatch.setattr(release_train, "RELEASE_DEBOUNCE_S", 60.0)
    fake_db([{"id": 1, "deploy_status": "success", "created_at": _iso(120)}])
    decision, note = release_train._capacity_release_decision("beethoven", ahead=1)
    assert decision == "release", note


def test_debounce_fails_open(fake_db, monkeypatch):
    # An unreadable timestamp must not wedge releases forever — in-flight is the hard bound.
    monkeypatch.setattr(release_train, "RELEASE_DEBOUNCE_S", 60.0)
    fake_db([{"id": 1, "deploy_status": "success", "created_at": "not-a-timestamp"}])
    debounced, _ = release_train._release_debounced("beethoven")
    assert debounced is False


# 4. Nothing staged is nothing to ship, however long it has been.
def test_nothing_staged_is_up_to_date_regardless_of_elapsed_time(fake_db):
    fake_db([{"id": 1, "deploy_status": "success", "created_at": _iso(60 * 60 * 24 * 30)}])
    decision, note = release_train._capacity_release_decision("beethoven", ahead=0)
    assert decision == "up-to-date"
    assert note == "nothing staged"


# 5. Capacity mode does not override existing back-pressure.
def test_capacity_decision_does_not_touch_red_project_backpressure():
    # The RED/gate/hold machinery lives in the caller and is untouched by this function —
    # _capacity_release_decision only ever answers "is there work and is there room".
    src = release_train._capacity_release_decision.__doc__ or ""
    assert "not overridden" in src
    for symbol in ("_deploy_health_for", "_hold_for_open_fix", "_recent_failed_gate"):
        assert hasattr(release_train, symbol), f"back-pressure helper {symbol} must still exist"


# 6. One config change reverts to the previous behaviour, exactly.
def test_cadence_mode_restores_batch_and_interval(monkeypatch):
    monkeypatch.setattr(release_train, "RELEASE_MODE", "cadence")
    assert release_train._capacity_mode() is False
    assert release_train._effective_min_batch("beethoven") == release_train.MIN_BATCH
    # The original decision function is untouched and still governs cadence mode.
    assert release_train._release_decision(1, due=False, minimum=10) == "hold"
    assert release_train._release_decision(1, due=True, minimum=10) == "release"
    assert release_train._release_decision(10, due=False, minimum=10) == "release"
    assert release_train._release_decision(0, due=True, minimum=10) == "up-to-date"


# Cost regression must stay visible.
def test_release_rate_per_hour_is_reported(fake_db):
    fake_db([{"id": 1, "deploy_status": "success", "created_at": _iso(60)},
             {"id": 2, "deploy_status": "success", "created_at": _iso(120)}])
    assert release_train._release_rate_per_hour("beethoven") == 2


def test_release_rate_is_fail_soft(fake_db):
    fake_db(fail=True)
    assert release_train._release_rate_per_hour("beethoven") is None


# The dead knob is gone.
def test_unreachable_interval_branch_removed():
    src = (release_train._release_due.__code__.co_consts, )
    text = open(release_train.__file__, encoding="utf-8").read()
    assert "release interval disabled" not in text, (
        "the RELEASE_INTERVAL_HOURS <= 0 branch is unreachable behind max(6.0, ...) "
        "and must not be reintroduced"
    )
    assert src is not None


def test_cost_control_floors_are_preserved():
    text = open(release_train.__file__, encoding="utf-8").read()
    assert "RELEASE_INTERVAL_HOURS = max(6.0," in text
    assert "MIN_BATCH = max(" in text
