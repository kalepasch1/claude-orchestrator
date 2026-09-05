"""The red-gate cooldown must be bound by its window, not by a row count.

`_recent_failed_gate` asked for the newest 50 failed rows and then discarded
every one outside RED_GATE_COOLDOWN_MIN -- a time window enforced client-side
over a server-side cap that knows nothing about it. The fleet's own truncation
detector had been printing the problem from that exact line:

    [db] TRUNCATED SCAN release_train.py:546 -> releases returned exactly its
    limit (50) ordered by created_at.desc. Anything past the cap is invisible.

The consequence is the cooldown failing open in precisely the case it exists
for: a project failing hard enough to produce 50+ rows inside the window stops
seeing its own earlier failure and re-runs the gate it is meant to damp. Each of
those passes re-integrates, re-runs the suite and re-runs a production build.
"""
import datetime

import pytest

import release_train


def _iso(minutes_ago):
    stamp = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(minutes=minutes_ago))
    return stamp.isoformat()


@pytest.fixture
def captured(monkeypatch):
    """Record the query the cooldown sends, and reply with whatever a test wants."""
    seen = {}

    def fake_select(table, params):
        seen["table"] = table
        seen["params"] = dict(params)
        return seen.get("reply", [])

    monkeypatch.setattr(release_train.db, "select", fake_select)
    monkeypatch.setattr(release_train, "RED_GATE_COOLDOWN_MIN", 180)
    return seen


def test_the_window_is_asked_of_the_server(captured):
    release_train._recent_failed_gate("racefeed", "abc123", "qa")
    params = captured["params"]
    assert params["created_at"].startswith("gte."), \
        "the cooldown window must be a server-side filter, not a client-side discard"
    asked_from = datetime.datetime.fromisoformat(params["created_at"][len("gte."):])
    window = datetime.datetime.now(datetime.timezone.utc) - asked_from
    assert 175 * 60 <= window.total_seconds() <= 185 * 60


def test_the_row_cap_is_no_longer_the_thing_that_bounds_it(captured):
    release_train._recent_failed_gate("racefeed", "abc123", "qa")
    assert int(captured["params"]["limit"]) > 50


def test_a_recent_failure_on_this_sha_and_gate_holds(captured):
    captured["reply"] = [{"to_sha": "abc123", "note": "[gate:qa] staging QA failed",
                          "created_at": _iso(30), "deploy_status": "failed"}]
    assert release_train._recent_failed_gate("racefeed", "abc123", "qa") is True


def test_a_failure_past_the_window_does_not_hold(captured):
    """Belt and braces: even if the server hands back an older row, it is ignored."""
    captured["reply"] = [{"to_sha": "abc123", "note": "[gate:qa] staging QA failed",
                          "created_at": _iso(400), "deploy_status": "failed"}]
    assert release_train._recent_failed_gate("racefeed", "abc123", "qa") is False


def test_a_different_sha_does_not_hold(captured):
    captured["reply"] = [{"to_sha": "different", "note": "[gate:qa] staging QA failed",
                          "created_at": _iso(10), "deploy_status": "failed"}]
    assert release_train._recent_failed_gate("racefeed", "abc123", "qa") is False


def test_a_different_gate_does_not_hold(captured):
    captured["reply"] = [{"to_sha": "abc123", "note": "[gate:build] build failed",
                          "created_at": _iso(10), "deploy_status": "failed"}]
    assert release_train._recent_failed_gate("racefeed", "abc123", "qa") is False


def test_the_50th_row_no_longer_hides_the_51st(captured):
    """The regression, stated directly.

    Under the old query a project with more than 50 failures inside the window
    could not see the one that matched, because the cap cut the reply before the
    match. With the window asked of the server, the match is in the reply.
    """
    noise = [{"to_sha": "other-%d" % i, "note": "[gate:qa] failed",
              "created_at": _iso(5), "deploy_status": "failed"} for i in range(60)]
    match = {"to_sha": "abc123", "note": "[gate:qa] staging QA failed",
             "created_at": _iso(120), "deploy_status": "failed"}
    captured["reply"] = noise + [match]
    assert release_train._recent_failed_gate("racefeed", "abc123", "qa") is True


def test_a_naive_timestamp_is_still_read_as_utc(captured):
    """Pins the earlier fix: a naive created_at must not raise out of the cooldown."""
    naive = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(minutes=20)).replace(tzinfo=None).isoformat()
    captured["reply"] = [{"to_sha": "abc123", "note": "[gate:qa] failed",
                          "created_at": naive, "deploy_status": "failed"}]
    assert release_train._recent_failed_gate("racefeed", "abc123", "qa") is True


def test_a_database_error_fails_open(monkeypatch):
    """A cooldown that cannot read must not block the train."""
    monkeypatch.setattr(release_train, "RED_GATE_COOLDOWN_MIN", 180)

    def boom(*args, **kwargs):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(release_train.db, "select", boom)
    assert release_train._recent_failed_gate("racefeed", "abc123", "qa") is False


def test_a_disabled_cooldown_asks_the_database_nothing(monkeypatch):
    monkeypatch.setattr(release_train, "RED_GATE_COOLDOWN_MIN", 0)
    called = []
    monkeypatch.setattr(release_train.db, "select",
                        lambda *a, **k: called.append(1) or [])
    assert release_train._recent_failed_gate("racefeed", "abc123", "qa") is False
    assert called == []
