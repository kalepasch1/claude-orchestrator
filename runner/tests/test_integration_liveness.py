"""integration_liveness — the smoke alarm for a merge train that has died.

The condition being detected is a conjunction, and the tests are organised
around proving the alarm needs BOTH halves. A monitor that fires on "nothing
merged lately" would fire every quiet hour and be muted within a week, which is
the same as not having it.

`evaluate()` is pure, so §1 exercises the decision exhaustively with no DB, no
repo and no clock. §2 covers the I/O edges, where the rule is that any failure
means "no verdict this cycle" — an alarm that raises into the triage loop takes
the loop down with it, which is strictly worse than the stall it was watching
for.
"""
import json
import os
import subprocess
import sys
import time

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import integration_liveness as il  # noqa: E402


W = il.STALL_WINDOW_H
G = il.MIN_BRANCH_GROWTH


# ── §1 the verdict, as a pure function ──────────────────────────────────────

def test_the_alarm_needs_both_halves():
    # Nothing landed AND branches growing, for longer than the window.
    fired, reason = il.evaluate(landed=0, branches=40, previous_branches=40 - G, stalled_for_h=W + 1)
    assert fired
    assert "not reaching anyone" in reason


def test_something_landing_is_enough_to_stay_quiet():
    fired, reason = il.evaluate(landed=1, branches=400, previous_branches=1, stalled_for_h=99)
    assert not fired
    assert "landed inside the window" in reason


def test_a_quiet_fleet_is_not_a_blocked_one():
    # Nothing landed for days, but nothing is being produced either. That is a
    # different problem and a different alarm.
    fired, reason = il.evaluate(landed=0, branches=10, previous_branches=10, stalled_for_h=99)
    assert not fired
    assert "quiet fleet" in reason


def test_growth_below_the_floor_is_noise():
    fired, reason = il.evaluate(landed=0, branches=10 + G - 1, previous_branches=10, stalled_for_h=W + 1)
    assert not fired
    assert "quiet fleet" in reason


def test_the_window_must_actually_have_elapsed():
    fired, reason = il.evaluate(landed=0, branches=100, previous_branches=1, stalled_for_h=W / 2)
    assert not fired
    assert "of the" in reason and "window has elapsed" in reason


def test_a_shrinking_branch_count_never_alerts():
    # Branches going down means the train is running.
    fired, _ = il.evaluate(landed=0, branches=5, previous_branches=50, stalled_for_h=99)
    assert not fired


@pytest.mark.parametrize("landed,branches", [(-1, 40), (0, -1), (-1, -1)])
def test_an_unreadable_input_yields_no_verdict(landed, branches):
    # -1 means "could not look". It must not compare equal to zero, or an
    # unreadable repo would read as a branch count that dropped and mask a stall.
    fired, reason = il.evaluate(landed, branches, previous_branches=1, stalled_for_h=99)
    assert not fired
    assert "could not read" in reason


def test_the_first_ever_run_cannot_alert():
    # With no prior snapshot there is no growth to observe. Alerting here would
    # make every fresh install fire once for no reason.
    fired, reason = il.evaluate(landed=0, branches=900, previous_branches=-1, stalled_for_h=99)
    assert not fired
    assert "no prior branch snapshot" in reason


# ── §2 the I/O edges ────────────────────────────────────────────────────────

class FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def heads(n):
    return "\n".join(f"sha{i}\trefs/heads/agent/t{i}" for i in range(n))


def test_only_agent_heads_are_counted(monkeypatch, tmp_path):
    noise = "sha\trefs/heads/master\nsha\trefs/heads/release/x\nsha\trefs/heads/dependabot/y"
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: FakeCompleted(noise + "\n" + heads(7)))
    assert il.count_agent_branches(str(tmp_path)) == 7


def test_a_git_failure_returns_minus_one_not_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted("", returncode=128))
    assert il.count_agent_branches(str(tmp_path)) == -1


def test_a_git_timeout_returns_minus_one(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("git", 1)
    monkeypatch.setattr(subprocess, "run", boom)
    assert il.count_agent_branches(str(tmp_path)) == -1


def test_landed_count_is_server_side_and_excludes_DONE(monkeypatch):
    seen = {}

    def fake_count(table, params=None):
        seen["table"] = table
        seen["params"] = params
        return 4

    monkeypatch.setattr(il.db, "count", fake_count)
    assert il.count_landed_since(time.time() - 3600) == 4
    assert seen["table"] == "tasks"

    state_filter = seen["params"]["state"]
    assert "MERGED" in state_filter
    assert "DEPLOYED_AND_VERIFIED" in state_filter
    # DONE means "branch pushed", which is exactly what piles up during a stall.
    assert "DONE" not in state_filter.replace("DEPLOYED_AND_VERIFIED", "")
    # Counted, never paged and len()'d.
    assert seen["params"]["select"] == "id"


def test_a_db_failure_returns_minus_one(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(il.db, "count", boom)
    assert il.count_landed_since(time.time()) == -1


# ── §3 check(), end to end against fakes ────────────────────────────────────

@pytest.fixture
def wired(monkeypatch, tmp_path):
    inserted = []
    state = {"branches": 10, "landed": 0, "rows": {}, "notified": []}

    monkeypatch.setattr(il, "count_agent_branches", lambda repo: state["branches"])
    monkeypatch.setattr(il, "count_landed_since", lambda since, project_id=None: state["landed"])
    monkeypatch.setattr(il, "_last_row", lambda t: state["rows"].get(t))
    monkeypatch.setattr(il, "_notify", lambda m: state["notified"].append(m))

    def fake_insert(table, row, upsert=False):
        inserted.append(row)
        return row

    monkeypatch.setattr(il.db, "insert", fake_insert)
    return state, inserted


def snapshot_row(branches, hours_ago):
    return {
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours_ago * 3600)),
        "payload": json.dumps({"branches": branches}),
    }


def test_a_stall_alerts_and_records_both_rows(wired, tmp_path):
    state, inserted = wired
    state["branches"] = 60
    state["landed"] = 0
    state["rows"][il.SNAPSHOT_TYPE] = snapshot_row(60 - G - 5, W + 1)

    verdict = il.check(repo=str(tmp_path))
    assert verdict["alert"] is True
    assert {r["task_type"] for r in inserted} == {il.SNAPSHOT_TYPE, il.ALERT_TYPE}
    assert state["notified"] and "CRITICAL" in state["notified"][0]

    alert = [r for r in inserted if r["task_type"] == il.ALERT_TYPE][0]
    assert "merge_train" in alert["payload"]


def test_the_snapshot_is_written_even_when_quiet(wired, tmp_path):
    # The next cycle needs this baseline to observe growth at all.
    state, inserted = wired
    state["landed"] = 5
    state["rows"][il.SNAPSHOT_TYPE] = snapshot_row(10, W + 1)

    verdict = il.check(repo=str(tmp_path))
    assert verdict["alert"] is False
    assert [r["task_type"] for r in inserted] == [il.SNAPSHOT_TYPE]
    assert state["notified"] == []


def test_a_persisting_stall_does_not_re_notify_every_cycle(wired, tmp_path):
    state, inserted = wired
    state["branches"] = 60
    state["rows"][il.SNAPSHOT_TYPE] = snapshot_row(20, W + 1)
    state["rows"][il.ALERT_TYPE] = {"created_at": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))}  # a minute ago

    verdict = il.check(repo=str(tmp_path))
    assert verdict["alert"] is True          # still stalled
    assert state["notified"] == []           # but the operator is not paged again
    assert [r["task_type"] for r in inserted] == [il.SNAPSHOT_TYPE]


def test_an_old_alert_lets_the_alarm_speak_again(wired, tmp_path):
    state, inserted = wired
    state["branches"] = 60
    state["rows"][il.SNAPSHOT_TYPE] = snapshot_row(20, W + 1)
    state["rows"][il.ALERT_TYPE] = {"created_at": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - (il.RENOTIFY_H + 1) * 3600))}

    il.check(repo=str(tmp_path))
    assert state["notified"]


def test_an_unreadable_alert_timestamp_does_not_silence_the_alarm(wired, tmp_path):
    state, _ = wired
    state["branches"] = 60
    state["rows"][il.SNAPSHOT_TYPE] = snapshot_row(20, W + 1)
    state["rows"][il.ALERT_TYPE] = {"created_at": "not-a-timestamp"}

    il.check(repo=str(tmp_path))
    assert state["notified"]


def test_a_failing_snapshot_write_does_not_raise(wired, tmp_path, monkeypatch):
    state, _ = wired
    state["rows"][il.SNAPSHOT_TYPE] = snapshot_row(10, W + 1)

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(il.db, "insert", boom)
    assert il.check(repo=str(tmp_path))["alert"] is False


def test_a_corrupt_snapshot_payload_is_treated_as_no_baseline(wired, tmp_path):
    state, _ = wired
    state["branches"] = 900
    state["rows"][il.SNAPSHOT_TYPE] = {"created_at": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 99 * 3600)),
        "payload": "{not json"}

    verdict = il.check(repo=str(tmp_path))
    assert verdict["alert"] is False
    assert "no prior branch snapshot" in verdict["reason"]


def test_the_verdict_always_has_alert_and_reason(wired, tmp_path):
    state, _ = wired
    for branches, landed, row in [
        (-1, 0, None),
        (10, -1, snapshot_row(1, 99)),
        (10, 0, None),
        (99, 0, snapshot_row(1, 99)),
    ]:
        state["branches"], state["landed"] = branches, landed
        state["rows"][il.SNAPSHOT_TYPE] = row
        verdict = il.check(repo=str(tmp_path))
        assert isinstance(verdict["alert"], bool)
        assert isinstance(verdict["reason"], str) and verdict["reason"]
