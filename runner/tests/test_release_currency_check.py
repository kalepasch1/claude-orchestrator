"""release_currency_check — is production falling behind the work that is built?

`blocked_triage.release_currency_check()` is the alarm added after 244 unmerged
agent branches sat on apparently (1,174 on tomorrow) while prod served weeks-old
masters and nothing fired, because every other monitor watched process health
rather than outcome currency. It had no tests at all: `git grep -l
release_currency` across runner/tests and runner/test_*.py on origin/master
returned nothing. An unwatched alarm is indistinguishable from a broken one, and
this one is the last line of defence against exactly the failure it was built
for.

What is pinned here:

  * the AND: a project is flagged only when branches exceed the threshold AND
    the base has not advanced inside the window. Either alone is normal — a
    healthy fleet has open branches, and a quiet week has a stale base.
  * the 6h self-limit gate, which runs inside a 10-minute triage cycle.
  * fail-soft on every external edge — DB, filesystem, git.

Two current behaviours around an unreadable base age are pinned deliberately
rather than corrected, because they fail in OPPOSITE directions and neither is
obviously intended. Empty git output becomes epoch 0, so the base reads as ~56
years stale and the alarm fires with a nonsense age in the payload; non-numeric
output raises, becomes -1, and can never exceed the threshold, so the project is
silently reported as current. The tests below record both so the tradeoffs are
decisions on the record instead of accidents. Changing either alters what the
alarm fires on and belongs in its own task.
"""
import os
import subprocess
import sys
import time

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import blocked_triage as bt  # noqa: E402


# ── test doubles ────────────────────────────────────────────────────────────

class FakeCompleted:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.returncode = 0


def agent_heads(n: int) -> str:
    return "\n".join(f"sha{i}\trefs/heads/agent/task-{i}" for i in range(n))


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """Wire release_currency_check to controllable DB, git and filesystem."""
    inserted = []

    state = {
        "gate_rows": [],          # last release_currency_scan row, if any
        "projects": [{"name": "apparently", "repo_path": str(tmp_path), "default_base": "master"}],
        "branches": 0,
        "base_epoch": time.time(),   # base tip commit time
        "select_raises": False,
        "insert_raises": False,
        "git_raises": False,
        "age_stdout": None,          # override raw git output
    }

    def fake_select(table, params=None):
        if state["select_raises"]:
            raise RuntimeError("db down")
        if table == "coordination_tasks":
            return list(state["gate_rows"])
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
        if "log" in cmd:
            if state["age_stdout"] is not None:
                return FakeCompleted(state["age_stdout"])
            return FakeCompleted(f"{int(state['base_epoch'])}\n")
        return FakeCompleted("")

    monkeypatch.setattr(bt.db, "select", fake_select)
    monkeypatch.setattr(bt.db, "insert", fake_insert)
    monkeypatch.setattr(bt.db, "localize_repo_path", lambda p: p)
    monkeypatch.setattr(subprocess, "run", fake_run)

    return state, inserted


def hours_ago(h: float) -> float:
    return time.time() - h * 3600


# ── the AND, under various conditions ───────────────────────────────────────

def test_a_healthy_project_is_not_flagged(harness):
    state, inserted = harness
    state["branches"] = 3
    state["base_epoch"] = hours_ago(1)

    assert bt.release_currency_check() == []
    # The scan is still recorded, so the 6h gate advances on a clean pass too.
    assert any(r.get("task_type") == "release_currency_scan" for r in inserted)
    assert not any(r.get("task_type") == "release_currency_alert" for r in inserted)


def test_many_branches_alone_is_not_an_alert(harness):
    # A busy fleet has open branches. On its own that is throughput, not decay.
    state, _ = harness
    state["branches"] = bt.RELEASE_CURRENCY_MAX_BRANCHES + 50
    state["base_epoch"] = hours_ago(1)

    assert bt.release_currency_check() == []


def test_a_stale_base_alone_is_not_an_alert(harness):
    # A quiet week leaves the base old with nothing waiting. Also not decay.
    state, _ = harness
    state["branches"] = 1
    state["base_epoch"] = hours_ago(bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 100)

    assert bt.release_currency_check() == []


def test_both_together_is_the_alert(harness):
    state, inserted = harness
    state["branches"] = bt.RELEASE_CURRENCY_MAX_BRANCHES + 1
    state["base_epoch"] = hours_ago(bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 2)

    findings = bt.release_currency_check()
    assert len(findings) == 1
    assert findings[0]["project"] == "apparently"
    assert findings[0]["unmerged_agent_branches"] == bt.RELEASE_CURRENCY_MAX_BRANCHES + 1
    assert findings[0]["base_age_hours"] > bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H

    alerts = [r for r in inserted if r.get("task_type") == "release_currency_alert"]
    assert len(alerts) == 1
    assert "catchup_drive" in alerts[0]["payload"]


def test_the_thresholds_are_strict_not_inclusive(harness):
    """Exactly at the threshold is not over it — the boundary is deliberate."""
    state, _ = harness
    state["branches"] = bt.RELEASE_CURRENCY_MAX_BRANCHES  # == not >
    state["base_epoch"] = hours_ago(bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 5)
    assert bt.release_currency_check() == []


def test_only_agent_branches_are_counted(harness, monkeypatch):
    # refs/heads/main, dependabot/*, release/* are not built-but-unmerged work.
    state, _ = harness
    noise = "\n".join([
        "sha\trefs/heads/master",
        "sha\trefs/heads/release/2026-08",
        "sha\trefs/heads/dependabot/npm/x",
    ])

    def fake_run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        if "ls-remote" in cmd:
            return FakeCompleted(noise + "\n" + agent_heads(30))
        return FakeCompleted(f"{int(hours_ago(bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 5))}\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    findings = bt.release_currency_check()
    assert findings[0]["unmerged_agent_branches"] == 30


def test_every_failing_project_is_reported_not_just_the_first(harness, tmp_path):
    state, inserted = harness
    state["projects"] = [
        {"name": "apparently", "repo_path": str(tmp_path), "default_base": "master"},
        {"name": "tomorrow", "repo_path": str(tmp_path), "default_base": "main"},
    ]
    state["branches"] = bt.RELEASE_CURRENCY_MAX_BRANCHES + 200
    state["base_epoch"] = hours_ago(bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 400)

    assert {f["project"] for f in bt.release_currency_check()} == {"apparently", "tomorrow"}


# ── the 6h self-limit gate ──────────────────────────────────────────────────

def test_a_recent_scan_short_circuits_the_whole_check(harness):
    state, inserted = harness
    state["gate_rows"] = [{"created_at": _iso(hours_ago(1))}]
    state["branches"] = 9999
    state["base_epoch"] = hours_ago(9999)

    assert bt.release_currency_check() == []
    # Nothing recorded either: the check did not run.
    assert inserted == []


def test_a_scan_older_than_the_window_lets_it_run(harness):
    state, _ = harness
    state["gate_rows"] = [{"created_at": _iso(hours_ago(7))}]
    state["branches"] = bt.RELEASE_CURRENCY_MAX_BRANCHES + 1
    state["base_epoch"] = hours_ago(bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 1)

    assert len(bt.release_currency_check()) == 1


def test_an_unparseable_gate_timestamp_does_not_suppress_the_scan(harness):
    # Failing OPEN here is right: a bad gate row must not silence the alarm.
    state, _ = harness
    state["gate_rows"] = [{"created_at": "not-a-timestamp"}]
    state["branches"] = bt.RELEASE_CURRENCY_MAX_BRANCHES + 1
    state["base_epoch"] = hours_ago(bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 1)

    assert len(bt.release_currency_check()) == 1


# ── fail-soft on every external edge ────────────────────────────────────────

def test_an_unreachable_project_table_returns_empty_rather_than_raising(harness):
    state, _ = harness
    state["select_raises"] = True
    assert bt.release_currency_check() == []


def test_a_missing_repo_directory_is_skipped_not_fatal(harness):
    state, _ = harness
    state["projects"] = [{"name": "gone", "repo_path": "/does/not/exist", "default_base": "master"}]
    assert bt.release_currency_check() == []


def test_a_git_timeout_skips_the_project_and_keeps_going(harness, tmp_path):
    state, _ = harness
    state["git_raises"] = True
    state["projects"] = [
        {"name": "a", "repo_path": str(tmp_path), "default_base": "master"},
        {"name": "b", "repo_path": str(tmp_path), "default_base": "master"},
    ]
    assert bt.release_currency_check() == []


def test_a_failed_alert_write_still_returns_the_findings(harness):
    # The caller acts on the return value; losing it because the audit write
    # failed would turn a DB blip into a missed alarm.
    state, _ = harness
    state["branches"] = bt.RELEASE_CURRENCY_MAX_BRANCHES + 1
    state["base_epoch"] = hours_ago(bt.RELEASE_CURRENCY_MAX_MASTER_AGE_H + 1)
    state["insert_raises"] = True

    assert len(bt.release_currency_check()) == 1


def test_empty_git_output_reads_as_infinitely_stale(harness):
    """Pinned, with the caveat named.

    `float((age.stdout or "0").strip())` turns empty git output into epoch 0, so
    the base looks ~56 years old and the alarm fires. Firing is the right
    direction for an alarm — but the reported `base_age_hours` is then a nonsense
    number (hundreds of thousands of hours) sitting in a CRITICAL payload an
    operator reads. Worth knowing before trusting that field.
    """
    state, _ = harness
    state["branches"] = bt.RELEASE_CURRENCY_MAX_BRANCHES + 500
    state["age_stdout"] = ""   # git produced nothing

    findings = bt.release_currency_check()
    assert len(findings) == 1
    assert findings[0]["base_age_hours"] > 100_000  # not a real age


def test_unparseable_git_output_fails_quiet(harness):
    """Pinned, not endorsed.

    Non-numeric output (a git error printed to stdout, a truncated read) raises
    ValueError, the handler sets age_h = -1, and -1 can never exceed the
    threshold — so the project is silently reported as current no matter how
    many branches are waiting. In an alarm built to catch prod falling behind,
    that is the wrong direction to fail, and it is the quieter sibling of the
    case above. Recorded so the tradeoff is a decision rather than an accident;
    changing it alters what the alarm fires on and belongs in its own task.
    """
    state, _ = harness
    state["branches"] = bt.RELEASE_CURRENCY_MAX_BRANCHES + 500
    state["age_stdout"] = "fatal: bad revision\n"

    assert bt.release_currency_check() == []


def _iso(epoch: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(
        epoch, tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")
