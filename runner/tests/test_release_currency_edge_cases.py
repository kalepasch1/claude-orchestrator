"""release_currency_check — edge cases the first test file did not reach.

`test_release_currency_check.py` pins the core contract: the AND between branch
count and base age, the 6h self-limit gate, and fail-soft on the DB/git/FS
edges. What it does not pin is how the check *determines currency for a given
project* — which repo path it resolves, which base ref it asks git about, which
refs it is willing to count, and what it records when a project is unusable.

Those are the inputs to the determination. Every one of them has a silent-skip
path (`continue`, a falsy `repo`, a `.get()` default), so a mistake there does
not raise and does not flag — it just quietly reports the project as current.
That is the same failure mode the alarm exists to prevent, one level up: an
unwatched skip is indistinguishable from a clean pass.

Scope note: these tests describe current behaviour. Where current behaviour is
arguably wrong (a project whose repo cannot be localised vanishes without a
trace) it is pinned with the caveat named, not corrected here — changing it
alters what the alarm reports and belongs in its own task.
"""
import os
import subprocess
import sys
import time

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import blocked_triage as bt  # noqa: E402


class FakeCompleted:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.returncode = 0


def agent_heads(n: int) -> str:
    return "\n".join(f"sha{i}\trefs/heads/agent/task-{i}" for i in range(n))


def hours_ago(h: float) -> float:
    return time.time() - h * 3600


def over_branch_threshold() -> int:
    return bt.RELEASE_CURRENCY_MAX_BRANCHES + 1


def stale_base_epoch() -> float:
    return hours_ago(bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 1)


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """Same shape as the sibling harness, plus a record of the git argv.

    `git_calls` is the point of this fixture: the sibling file asserts on the
    findings, this one also needs to assert on *what was asked of git*, because
    asking about the wrong ref is a currency-determination bug that produces a
    perfectly plausible clean result.
    """
    inserted = []
    git_calls = []

    state = {
        "gate_rows": [],
        "projects": [{"name": "apparently", "repo_path": str(tmp_path),
                      "default_base": "master"}],
        "branches": 0,
        "base_epoch": time.time(),
        "heads_stdout": None,
        "localize": lambda p: p,
    }

    def fake_select(table, params=None):
        if table == "coordination_tasks":
            return list(state["gate_rows"])
        if table == "projects":
            return list(state["projects"])
        return []

    def fake_insert(table, row, upsert=False):
        inserted.append(row)
        return row

    def fake_run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        git_calls.append({"cmd": list(cmd), "cwd": cwd})
        if "ls-remote" in cmd:
            if state["heads_stdout"] is not None:
                return FakeCompleted(state["heads_stdout"])
            return FakeCompleted(agent_heads(state["branches"]))
        if "log" in cmd:
            return FakeCompleted(f"{int(state['base_epoch'])}\n")
        return FakeCompleted("")

    monkeypatch.setattr(bt.db, "select", fake_select)
    monkeypatch.setattr(bt.db, "insert", fake_insert)
    monkeypatch.setattr(bt.db, "localize_repo_path",
                        lambda p: state["localize"](p))
    monkeypatch.setattr(subprocess, "run", fake_run)

    return state, inserted, git_calls


@pytest.fixture
def any_path_is_a_repo(monkeypatch):
    """Let a test name a synthetic repo path without creating it on disk.

    `release_currency_check` guards on `os.path.isdir(repo)`. Tests that are
    about which ref/cwd git is handed — not about the directory check, which has
    its own tests below — would otherwise be silently skipped by that guard and
    pass for the wrong reason.
    """
    real_isdir = os.path.isdir
    monkeypatch.setattr(
        bt.os.path, "isdir",
        lambda p: True if str(p).startswith(("/repo", "/fleet", "/local")) else real_isdir(p))


# ── which base ref currency is measured against ─────────────────────────────

def test_the_configured_base_is_the_ref_that_is_aged(harness, any_path_is_a_repo):
    """tomorrow's base is `main`, not `master`.

    If the check aged `origin/master` on a repo whose production branch is
    `main`, git would answer about a branch that may not exist or may be
    long-abandoned, and the project's currency would be measured against the
    wrong thing entirely.
    """
    state, _, git_calls = harness
    state["projects"] = [{"name": "tomorrow", "repo_path": "/repo",
                          "default_base": "main"}]
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = stale_base_epoch()

    assert len(bt.release_currency_check()) == 1
    log_cmds = [c["cmd"] for c in git_calls if "log" in c["cmd"]]
    assert log_cmds and "origin/main" in log_cmds[0]


def test_a_project_with_no_declared_base_falls_back_to_master(harness, any_path_is_a_repo):
    state, _, git_calls = harness
    state["projects"] = [{"name": "nameless", "repo_path": "/repo",
                          "default_base": None}]
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = stale_base_epoch()

    assert len(bt.release_currency_check()) == 1
    log_cmds = [c["cmd"] for c in git_calls if "log" in c["cmd"]]
    assert "origin/master" in log_cmds[0]


def test_an_empty_base_string_also_falls_back_rather_than_asking_for_origin_slash(harness, any_path_is_a_repo):
    # `or "master"` catches "" as well as None. Without it the ref would be
    # the string "origin/", which git rejects — and the project would then be
    # skipped silently rather than measured.
    state, _, git_calls = harness
    state["projects"] = [{"name": "blank", "repo_path": "/repo",
                          "default_base": ""}]
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = stale_base_epoch()

    assert len(bt.release_currency_check()) == 1
    log_cmds = [c["cmd"] for c in git_calls if "log" in c["cmd"]]
    assert "origin/master" in log_cmds[0]


def test_git_is_run_inside_the_localised_repo_not_the_recorded_path(harness, any_path_is_a_repo):
    """`repo_path` is the fleet-canonical path; `localize_repo_path` maps it
    onto this machine. Running git in the unmapped path would either fail or,
    worse, read a different checkout."""
    state, _, git_calls = harness
    state["projects"] = [{"name": "apparently", "repo_path": "/fleet/apparently",
                          "default_base": "master"}]
    state["localize"] = lambda p: "/local/apparently"
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = stale_base_epoch()

    bt.release_currency_check()
    assert git_calls, "git was never invoked"
    assert all(c["cwd"] == "/local/apparently" for c in git_calls)


# ── projects that cannot be measured at all ─────────────────────────────────

def test_a_project_whose_path_does_not_localise_is_skipped_silently(harness):
    """Pinned, with the caveat named.

    An empty localisation means the repo is not on this machine. The project is
    dropped with `continue`: no finding, no separate record, and it is not
    distinguishable in the scan payload from a project that was checked and
    found current. A project that is never measured should not read as healthy;
    surfacing it belongs in its own task.
    """
    state, inserted, git_calls = harness
    state["localize"] = lambda p: ""
    state["branches"] = 9999
    state["base_epoch"] = hours_ago(9999)

    assert bt.release_currency_check() == []
    assert git_calls == []          # git never asked
    scans = [r for r in inserted if r.get("task_type") == "release_currency_scan"]
    assert len(scans) == 1
    assert '"flagged": 0' in scans[0]["payload"]


def test_a_project_row_with_no_repo_path_at_all_is_skipped(harness):
    state, _, git_calls = harness
    state["projects"] = [{"name": "pathless", "default_base": "master"}]
    assert bt.release_currency_check() == []
    assert git_calls == []


def test_an_unmeasurable_project_does_not_stop_the_ones_after_it(harness, tmp_path):
    """The loop is per-project. One bad row must not mask a real alert behind it."""
    state, _, _ = harness
    state["projects"] = [
        {"name": "gone", "repo_path": "/does/not/exist", "default_base": "master"},
        {"name": "apparently", "repo_path": str(tmp_path), "default_base": "master"},
    ]
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = stale_base_epoch()

    findings = bt.release_currency_check()
    assert [f["project"] for f in findings] == ["apparently"]


def test_an_empty_project_table_still_records_the_scan(harness):
    # The 6h gate must advance even on an empty fleet, or the check re-runs
    # every triage cycle for no reason.
    state, inserted, _ = harness
    state["projects"] = []

    assert bt.release_currency_check() == []
    assert any(r.get("task_type") == "release_currency_scan" for r in inserted)


# ── which refs count as built-but-unmerged work ─────────────────────────────

def test_nested_agent_branches_are_counted(harness):
    # agent/<project>/<slug> is a real shape in this fleet.
    state, _, _ = harness
    state["heads_stdout"] = "\n".join(
        f"sha{i}\trefs/heads/agent/beethoven/slice-{i}" for i in range(40))
    state["base_epoch"] = stale_base_epoch()

    findings = bt.release_currency_check()
    assert findings[0]["unmerged_agent_branches"] == 40


def test_a_branch_that_merely_ends_in_agent_is_not_counted(harness):
    """`refs/heads/my-agent/x` and `refs/heads/reagent` contain "agent" but are
    not agent branches. The prefix match is what keeps the count honest."""
    state, _, _ = harness
    state["heads_stdout"] = "\n".join([
        "sha\trefs/heads/my-agent/x",
        "sha\trefs/heads/reagent",
        "sha\trefs/heads/feature/agentic-coder",
    ] + [f"sha{i}\trefs/heads/agent/real-{i}" for i in range(30)])
    state["base_epoch"] = stale_base_epoch()

    findings = bt.release_currency_check()
    assert findings[0]["unmerged_agent_branches"] == 30


def test_tags_under_agent_are_not_counted_as_unmerged_work(harness):
    state, _, _ = harness
    state["heads_stdout"] = "\n".join(
        [f"sha\trefs/tags/agent/archived-{i}" for i in range(200)]
        + [f"sha{i}\trefs/heads/agent/live-{i}" for i in range(30)])
    state["base_epoch"] = stale_base_epoch()

    findings = bt.release_currency_check()
    assert findings[0]["unmerged_agent_branches"] == 30


def test_no_remote_heads_at_all_is_zero_not_an_error(harness):
    state, _, _ = harness
    state["heads_stdout"] = ""
    state["base_epoch"] = stale_base_epoch()
    assert bt.release_currency_check() == []


# ── thresholds are read at call time, so fleet pushes take effect ───────────

def test_lowering_the_branch_threshold_takes_effect_without_reimport(monkeypatch, harness):
    """The constants are read inside the function body, not captured at import.

    That is what lets `fleet_config` push `ORCH_RELEASE_CURRENCY_MAX_BRANCHES`
    to a live runner. If they were bound at import the push would be a no-op
    until restart, and nobody would notice.
    """
    state, _, _ = harness
    state["branches"] = 3
    state["base_epoch"] = stale_base_epoch()
    assert bt.release_currency_check() == []

    monkeypatch.setattr(bt, "RELEASE_CURRENCY_MAX_BRANCHES", 2)
    state["gate_rows"] = []
    assert len(bt.release_currency_check()) == 1


def test_raising_the_age_window_suppresses_a_previously_flagged_project(monkeypatch, harness):
    state, _, _ = harness
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = hours_ago(bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 5)
    assert len(bt.release_currency_check()) == 1

    monkeypatch.setattr(bt, "RELEASE_CURRENCY_MAX_MASTER_AGE_H",
                        bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 500)
    assert bt.release_currency_check() == []


# ── what the alert payload actually carries ─────────────────────────────────

def test_the_reported_age_is_rounded_to_one_decimal(harness):
    # The payload is read by a human in a CRITICAL alert. Full float precision
    # on an estimated age is noise that makes the number look more exact than it
    # is.
    state, _, _ = harness
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = hours_ago(72.456789)

    age = bt.release_currency_check()[0]["base_age_hours"]
    assert round(age, 1) == age


def test_the_scan_row_counts_the_projects_that_were_flagged(harness, tmp_path):
    state, inserted, _ = harness
    state["projects"] = [
        {"name": "a", "repo_path": str(tmp_path), "default_base": "master"},
        {"name": "b", "repo_path": str(tmp_path), "default_base": "master"},
    ]
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = stale_base_epoch()

    bt.release_currency_check()
    scans = [r for r in inserted if r.get("task_type") == "release_currency_scan"]
    assert len(scans) == 1
    assert '"flagged": 2' in scans[0]["payload"]


def test_one_alert_row_carries_every_flagged_project(harness, tmp_path):
    # Not one row per project: the operator gets a single actionable CRITICAL.
    state, inserted, _ = harness
    state["projects"] = [
        {"name": "a", "repo_path": str(tmp_path), "default_base": "master"},
        {"name": "b", "repo_path": str(tmp_path), "default_base": "master"},
    ]
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = stale_base_epoch()

    bt.release_currency_check()
    alerts = [r for r in inserted if r.get("task_type") == "release_currency_alert"]
    assert len(alerts) == 1
    assert '"a"' in alerts[0]["payload"] and '"b"' in alerts[0]["payload"]


def test_no_alert_row_is_written_when_nothing_is_flagged(harness):
    state, inserted, _ = harness
    state["branches"] = 1
    state["base_epoch"] = hours_ago(1)

    bt.release_currency_check()
    assert not any(r.get("task_type") == "release_currency_alert" for r in inserted)


# ── the gate boundary ───────────────────────────────────────────────────────

def test_a_scan_exactly_at_the_window_is_not_suppressed(harness):
    """`< 6*3600` is strict, so a scan at exactly 6h lets the check run.

    Pinned because the alternative (>=) would stall the check by one full cycle
    on a fleet whose triage happens to land on the boundary.
    """
    import datetime
    state, _, _ = harness
    at = datetime.datetime.fromtimestamp(
        hours_ago(6), tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    state["gate_rows"] = [{"created_at": at}]
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = stale_base_epoch()

    assert len(bt.release_currency_check()) == 1


def test_an_empty_gate_result_is_treated_as_never_scanned(harness):
    state, _, _ = harness
    state["gate_rows"] = []
    state["branches"] = over_branch_threshold()
    state["base_epoch"] = stale_base_epoch()

    assert len(bt.release_currency_check()) == 1
