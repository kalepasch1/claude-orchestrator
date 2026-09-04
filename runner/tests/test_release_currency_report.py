"""release_currency_report — does the report tell a human the truth?

The alarm it accompanies is tested in `test_release_currency_check.py`, which
pins what fires. These tests pin what an operator READS, which is a different
contract and fails in different ways:

  * a PASS must be a positive statement, not an absence — the whole reason this
    module exists is that `release_currency_check()` returning `[]` means both
    "clean" and "did not look";
  * the report must never consume the alarm's 6h gate, or the thing that reports
    on the alarm becomes the thing that silences it;
  * the thresholds must be the alarm's own, so the two can never disagree about
    what "current" means;
  * an unmeasurable project must surface as UNKNOWN rather than as the alarm's
    silent PASS-by-default — visible without changing the alarm's semantics;
  * every external edge fails soft, because instrumentation that can break the
    release train is worse than no instrumentation.
"""
import json
import os
import subprocess
import sys
import time

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import release_currency_report as rcr  # noqa: E402


class FakeCompleted:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.returncode = 0


def agent_heads(n):
    return "\n".join(f"sha{i}\trefs/heads/agent/task-{i}" for i in range(n))


def hours_ago(h):
    return time.time() - h * 3600


@pytest.fixture
def harness(monkeypatch, tmp_path):
    inserted = []
    state = {
        "projects": [{"name": "apparently", "repo_path": str(tmp_path),
                      "default_base": "master"}],
        "branches": 0,
        "base_epoch": time.time(),
        "age_stdout": None,
        "select_raises": False,
        "insert_raises": False,
        "git_raises": False,
    }

    def fake_select(table, params=None):
        if state["select_raises"]:
            raise RuntimeError("db down")
        if table == "projects":
            return list(state["projects"])
        return []

    def fake_insert(table, row, upsert=False):
        if state["insert_raises"]:
            raise RuntimeError("db down")
        inserted.append(row)
        return row

    def fake_run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        if state["git_raises"]:
            raise subprocess.TimeoutExpired(cmd, timeout or 1)
        if "ls-remote" in cmd:
            return FakeCompleted(agent_heads(state["branches"]))
        if state["age_stdout"] is not None:
            return FakeCompleted(state["age_stdout"])
        return FakeCompleted(f"{int(state['base_epoch'])}\n")

    monkeypatch.setattr(rcr.db, "select", fake_select)
    monkeypatch.setattr(rcr.db, "insert", fake_insert)
    monkeypatch.setattr(rcr.db, "localize_repo_path", lambda p: p)
    monkeypatch.setattr(subprocess, "run", fake_run)
    return state, inserted


def limits():
    return rcr.thresholds()


# ── a pass is a statement, not a silence ────────────────────────────────────

def test_a_current_project_is_reported_as_present_and_passing(harness):
    state, _ = harness
    state["branches"] = 3
    state["base_epoch"] = hours_ago(1)

    rows = rcr.evaluate()
    assert len(rows) == 1
    assert rows[0]["status"] == rcr.PASS
    assert rows[0]["project"] == "apparently"
    # The measurement itself is in the row, so "24 of 25" is visible before it
    # becomes an alert rather than after.
    assert rows[0]["unmerged_agent_branches"] == 3
    assert rows[0]["base_age_hours"] == pytest.approx(1, abs=0.2)


def test_the_report_states_pass_in_words_a_human_can_act_on(harness):
    state, _ = harness
    state["branches"] = 2
    state["base_epoch"] = hours_ago(1)

    text = rcr.render(rcr.evaluate())
    assert "VERDICT: PASS" in text
    assert "apparently" in text


def test_a_behind_project_names_itself_and_the_remedy(harness):
    state, _ = harness
    max_b, max_h = limits()
    state["branches"] = max_b + 1
    state["base_epoch"] = hours_ago(max_h + 2)

    rows = rcr.evaluate()
    assert rows[0]["status"] == rcr.FAIL
    text = rcr.render(rows)
    assert "VERDICT: FAIL" in text
    assert "apparently" in text
    assert "catchup_drive" in text


# ── the same AND, and the same strict boundary, as the alarm ────────────────

def test_thresholds_come_from_the_alarm_so_they_cannot_drift(monkeypatch):
    import blocked_triage
    assert rcr.thresholds() == (blocked_triage.RELEASE_CURRENCY_MAX_BRANCHES,
                                blocked_triage.RELEASE_CURRENCY_MAX_MASTER_AGE_H)


def test_many_branches_alone_is_still_current(harness):
    state, _ = harness
    max_b, _ = limits()
    state["branches"] = max_b + 50
    state["base_epoch"] = hours_ago(1)
    assert rcr.evaluate()[0]["status"] == rcr.PASS


def test_a_stale_base_alone_is_still_current(harness):
    state, _ = harness
    _, max_h = limits()
    state["branches"] = 1
    state["base_epoch"] = hours_ago(max_h + 100)
    assert rcr.evaluate()[0]["status"] == rcr.PASS


def test_exactly_at_the_threshold_is_not_over_it(harness):
    state, _ = harness
    max_b, max_h = limits()
    state["branches"] = max_b
    state["base_epoch"] = hours_ago(max_h + 5)
    assert rcr.evaluate()[0]["status"] == rcr.PASS


def test_only_agent_branches_count_toward_the_limit():
    noise = "\n".join(["sha\trefs/heads/master",
                       "sha\trefs/heads/release/2026-08",
                       "sha\trefs/heads/dependabot/npm/x"])
    assert rcr.count_agent_branches(noise + "\n" + agent_heads(30)) == 30
    assert rcr.count_agent_branches("") == 0
    assert rcr.count_agent_branches(None) == 0


def test_every_project_is_reported_not_just_the_failing_ones(harness, tmp_path):
    state, _ = harness
    max_b, max_h = limits()
    state["projects"] = [
        {"name": "apparently", "repo_path": str(tmp_path), "default_base": "master"},
        {"name": "tomorrow", "repo_path": str(tmp_path), "default_base": "main"},
    ]
    state["branches"] = max_b + 200
    state["base_epoch"] = hours_ago(max_h + 400)

    rows = rcr.evaluate()
    # The alarm returns findings only. The report is per-project and total.
    assert {r["project"] for r in rows} == {"apparently", "tomorrow"}
    assert all(r["status"] == rcr.FAIL for r in rows)
    assert rcr.summarize(rows)["behind"] == ["apparently", "tomorrow"]


def test_the_base_branch_is_taken_from_the_project_not_assumed(harness, tmp_path):
    state, _ = harness
    state["projects"] = [{"name": "tomorrow", "repo_path": str(tmp_path),
                          "default_base": "main"}]
    seen = []

    def fake_run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        seen.append(cmd)
        if "ls-remote" in cmd:
            return FakeCompleted(agent_heads(1))
        return FakeCompleted(f"{int(time.time())}\n")

    import release_currency_report as m
    m_sub = sys.modules["subprocess"]
    old = m_sub.run
    m_sub.run = fake_run
    try:
        rows = rcr.evaluate()
    finally:
        m_sub.run = old
    assert rows[0]["base"] == "main"
    assert any("origin/main" in c for cmd in seen for c in cmd)


# ── the ungated read, and not consuming the alarm's gate ────────────────────

def test_the_report_never_writes_the_alarms_gate_row(harness):
    state, inserted = harness
    max_b, max_h = limits()
    state["branches"] = max_b + 1
    state["base_epoch"] = hours_ago(max_h + 1)

    rows = rcr.evaluate()
    assert rcr.record(rows, source="test") is True
    types = {r.get("task_type") for r in inserted}
    # Writing release_currency_scan here would advance the 6h gate and suppress
    # the alarm's next real scan — the report would silence what it reports on.
    assert "release_currency_scan" not in types
    assert types == {rcr.REPORT_TASK_TYPE}


def test_a_recent_alarm_scan_cannot_suppress_the_report(harness, monkeypatch):
    """The 6h gate is right for a 10-minute triage loop and wrong for a human.

    Pinned structurally rather than behaviourally: the report never reads the
    gate table at all, so no state of that table can turn a real FAIL into the
    `[]` that reads as "all clear". An edit that adds the gate read back in
    fails here even if it happens to return a passing answer that day.
    """
    state, _ = harness
    max_b, max_h = limits()
    state["branches"] = max_b + 1
    state["base_epoch"] = hours_ago(max_h + 1)
    tables = []
    inner = rcr.db.select

    def recording_select(table, params=None):
        tables.append(table)
        return inner(table, params)

    monkeypatch.setattr(rcr.db, "select", recording_select)
    assert rcr.evaluate()[0]["status"] == rcr.FAIL
    assert tables == ["projects"]


def test_the_recorded_payload_is_json_and_carries_the_summary(harness):
    state, inserted = harness
    state["branches"] = 4
    rcr.record(rcr.evaluate(), source="release_train")
    payload = json.loads(inserted[0]["payload"])
    assert payload["source"] == "release_train"
    assert payload["summary"]["counts"][rcr.PASS] == 1
    assert payload["projects"][0]["project"] == "apparently"


# ── UNKNOWN: the alarm's silent failure, made visible without changing it ───

def test_unreadable_base_age_is_unknown_not_a_pass(harness):
    """`release_currency_check()` turns this into age_h = -1 and reports the
    project as current no matter how many branches wait. That behaviour is
    pinned by its own tests and is not changed here — it is surfaced."""
    state, _ = harness
    max_b, _ = limits()
    state["branches"] = max_b + 500
    state["age_stdout"] = "fatal: bad revision\n"

    row = rcr.evaluate()[0]
    assert row["status"] == rcr.UNKNOWN
    assert row["base_age_hours"] is None
    assert "not a number" in row["reason"]
    assert "fatal: bad revision" in row["reason"]


def test_empty_base_age_is_unknown_not_a_nonsense_age(harness):
    """The alarm reads empty git output as epoch 0 and reports a ~500,000-hour
    age inside a CRITICAL payload. Here it is simply not measured."""
    state, _ = harness
    max_b, _ = limits()
    state["branches"] = max_b + 500
    state["age_stdout"] = ""

    row = rcr.evaluate()[0]
    assert row["status"] == rcr.UNKNOWN
    assert row["base_age_hours"] is None
    assert "empty" in row["reason"]


def test_unknown_is_visible_in_the_rendered_report(harness):
    state, _ = harness
    state["age_stdout"] = "fatal: bad revision\n"
    text = rcr.render(rcr.evaluate())
    assert "UNKNOWN" in text
    assert "Caveat" in text


# ── exit codes: the pipeline-usable verdict ─────────────────────────────────

def test_a_current_fleet_exits_zero(harness):
    state, _ = harness
    state["branches"] = 1
    assert rcr.exit_code(rcr.evaluate()) == 0


def test_a_behind_fleet_exits_one(harness):
    state, _ = harness
    max_b, max_h = limits()
    state["branches"] = max_b + 1
    state["base_epoch"] = hours_ago(max_h + 1)
    assert rcr.exit_code(rcr.evaluate()) == 1


def test_unknown_is_tolerated_by_default_and_fails_under_strict(harness):
    state, _ = harness
    state["age_stdout"] = "fatal: bad revision\n"
    rows = rcr.evaluate()
    assert rcr.exit_code(rows) == 0
    assert rcr.exit_code(rows, strict=True) == 2


def test_behind_outranks_unmeasurable(harness, tmp_path):
    """A project known to be behind is the more actionable signal; collapsing
    the two exit codes would hide it behind a measurement problem."""
    rows = [{"project": "a", "status": rcr.UNKNOWN},
            {"project": "b", "status": rcr.FAIL}]
    assert rcr.exit_code(rows, strict=True) == 1


def test_a_skipped_project_never_fails_the_gate(harness):
    state, _ = harness
    state["projects"] = [{"name": "gone", "repo_path": "/does/not/exist",
                          "default_base": "master"}]
    rows = rcr.evaluate()
    assert rows[0]["status"] == rcr.SKIPPED
    assert rcr.exit_code(rows, strict=True) == 0


# ── fail-soft on every external edge ────────────────────────────────────────

def test_an_unreachable_project_table_reports_rather_than_raises(harness):
    state, _ = harness
    state["select_raises"] = True
    rows = rcr.evaluate()
    assert rows[0]["status"] == rcr.SKIPPED
    assert "project list unavailable" in rows[0]["reason"]
    assert rcr.exit_code(rows) == 0


def test_a_missing_repo_is_skipped_with_a_reason(harness):
    state, _ = harness
    state["projects"] = [{"name": "gone", "repo_path": "/does/not/exist",
                          "default_base": "master"}]
    row = rcr.evaluate()[0]
    assert row["status"] == rcr.SKIPPED
    assert "not present on this machine" in row["reason"]


def test_a_git_timeout_skips_the_project_and_keeps_going(harness, tmp_path):
    state, _ = harness
    state["git_raises"] = True
    state["projects"] = [
        {"name": "a", "repo_path": str(tmp_path), "default_base": "master"},
        {"name": "b", "repo_path": str(tmp_path), "default_base": "master"},
    ]
    rows = rcr.evaluate()
    assert [r["status"] for r in rows] == [rcr.SKIPPED, rcr.SKIPPED]
    assert "TimeoutExpired" in rows[0]["reason"]


def test_a_failed_write_does_not_lose_the_report(harness):
    state, _ = harness
    state["insert_raises"] = True
    rows = rcr.evaluate()
    assert rcr.record(rows) is False
    assert len(rows) == 1  # the caller still has the findings


def test_the_gate_never_blocks_a_release_when_it_breaks(harness, monkeypatch):
    monkeypatch.setattr(rcr, "evaluate",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ok, rows = rcr.gate(source="release_train")
    assert ok is True
    assert rows == []


def test_the_gate_returns_false_when_a_project_is_behind(harness):
    state, inserted = harness
    max_b, max_h = limits()
    state["branches"] = max_b + 1
    state["base_epoch"] = hours_ago(max_h + 1)

    ok, rows = rcr.gate(source="release_train")
    assert ok is False
    assert len(rows) == 1
    assert inserted[0]["task_type"] == rcr.REPORT_TASK_TYPE


def test_thresholds_survive_blocked_triage_being_unimportable(monkeypatch):
    real = sys.modules.pop("blocked_triage", None)
    monkeypatch.setitem(sys.modules, "blocked_triage", None)
    try:
        assert rcr.thresholds() == (25, 48)
    finally:
        if real is not None:
            sys.modules["blocked_triage"] = real


# ── the no-silent-bucket contract ───────────────────────────────────────────

def test_every_project_lands_in_exactly_one_known_bucket(harness, tmp_path):
    state, _ = harness
    state["projects"] = [
        {"name": "a", "repo_path": str(tmp_path), "default_base": "master"},
        {"name": "gone", "repo_path": "/does/not/exist", "default_base": "master"},
    ]
    rows = rcr.evaluate()
    assert rcr.unaccounted(rows) == []
    assert rcr.summarize(rows)["total"] == 2
    assert sum(rcr.summarize(rows)["counts"].values()) == 2


def test_a_future_silent_bucket_shows_up_as_a_number_not_as_silence():
    rows = [{"project": "x", "status": "WEIRD"}]
    assert len(rcr.unaccounted(rows)) == 1
    assert "WARNING" in rcr.render(rows)


# ── the CLI ─────────────────────────────────────────────────────────────────

def test_the_cli_prints_a_human_report_and_returns_the_verdict(harness, capsys):
    state, _ = harness
    max_b, max_h = limits()
    state["branches"] = max_b + 1
    state["base_epoch"] = hours_ago(max_h + 1)

    code = rcr.main([])
    assert code == 1
    assert "VERDICT: FAIL" in capsys.readouterr().out


def test_the_cli_emits_machine_readable_json_on_request(harness, capsys):
    state, _ = harness
    state["branches"] = 2
    assert rcr.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["counts"][rcr.PASS] == 1


def test_the_cli_writes_nothing_unless_asked(harness, capsys):
    state, inserted = harness
    rcr.main(["--quiet"])
    assert inserted == []
    rcr.main(["--quiet", "--record"])
    assert len(inserted) == 1
