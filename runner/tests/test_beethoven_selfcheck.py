"""beethoven is the orchestrator; a merge into it changes what gates the next merge.

Every other project on this fleet is judged by the trains. beethoven IS the trains,
so a change that passes its own suite can still break the machinery that would have
caught the following one — and by then the thing that catches mistakes is the thing
that is broken.

Observed during the 2026-09-03 session, on changes that each passed their own
targeted tests:

  * seven merge_train tests broke, because the card path was made to depend on the
    host's load average
  * a self-heal was dropped, so a failed staging publish left a red release with
    nothing working on it
  * a tail truncation came back that a guard test exists specifically to forbid

All three were caught by running a WIDER suite than the change appeared to need.
This module makes that reflex automatic for the one repo where missing it takes out
the gates themselves.
"""
import os
import subprocess
import sys
import textwrap

import pytest

import beethoven_selfcheck as bsc


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, timeout=60, check=False)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "orch"
    (root / "runner" / "tests").mkdir(parents=True)
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "T")
    (root / "runner" / "merge_train.py").write_text("VALUE = 1\n")
    (root / "runner" / "scratch.py").write_text("ROOT = 'x'\n")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "base")
    return root


# ── what the merge touched ────────────────────────────────────────────────────

def test_changed_modules_names_only_runner_source(repo):
    (repo / "runner" / "merge_train.py").write_text("VALUE = 2\n")
    (repo / "runner" / "tests" / "test_x.py").write_text("# not a module\n")
    (repo / "README.md").write_text("docs\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "change")
    assert bsc.changed_modules(str(repo), "HEAD~1", "HEAD") == ["merge_train"]


def test_a_docs_only_merge_touches_no_modules(repo):
    (repo / "README.md").write_text("docs only\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "docs")
    assert bsc.changed_modules(str(repo), "HEAD~1", "HEAD") == []


def test_a_bad_ref_does_not_raise(repo):
    assert bsc.changed_modules(str(repo), "nope", "alsonope") == []


# ── which tests to run ────────────────────────────────────────────────────────

def test_a_test_file_that_merely_imports_the_module_is_selected(repo, tmp_path):
    """Substring matching on the test's SOURCE, not just its name.

    test_delivery_accelerators.py is not named after commit_overlay, and it was the
    file that caught the overlay change breaking a worktree assertion. Selecting only
    same-named tests would have missed it.
    """
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_unrelated.py").write_text("import json\n")
    (tests_dir / "test_delivery_accelerators.py").write_text(
        "import commit_overlay\n\ndef test_x():\n    pass\n")
    (repo / "runner" / "commit_overlay.py").write_text("X = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "overlay")
    chosen = bsc.impacted_tests(str(repo), "HEAD~1", "HEAD", tests_dir=str(tests_dir))
    assert "tests/test_delivery_accelerators.py" in chosen
    assert "tests/test_unrelated.py" not in chosen


def test_the_selection_is_bounded(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(bsc, "MAX_TEST_FILES", 3)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for i in range(20):
        (tests_dir / f"test_{i}.py").write_text("import merge_train\n")
    (repo / "runner" / "merge_train.py").write_text("VALUE = 3\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "touch")
    chosen = bsc.impacted_tests(str(repo), "HEAD~1", "HEAD", tests_dir=str(tests_dir))
    assert len(chosen) <= 3


# ── the verdict ───────────────────────────────────────────────────────────────

def test_a_merge_that_breaks_nothing_is_ok(repo, monkeypatch):
    monkeypatch.setattr(bsc, "failing_tests", lambda *a, **k: set())
    out = bsc.verify_merge(str(repo), "HEAD", "HEAD", test_files=["tests/test_a.py"])
    assert out["ok"] is True
    assert out["newly_failing"] == []


def test_a_merge_that_breaks_a_passing_test_is_not_ok(repo, monkeypatch):
    monkeypatch.setattr(bsc, "failing_tests", lambda *a, **k: {"tests/t.py::test_new"})
    monkeypatch.setattr(bsc, "_failures_at", lambda *a, **k: set())
    out = bsc.verify_merge(str(repo), "base", "merged", test_files=["tests/t.py"])
    assert out["ok"] is False
    assert out["newly_failing"] == ["tests/t.py::test_new"]


def test_a_test_that_was_already_red_is_not_blamed_on_the_merge(repo, monkeypatch):
    """Differential, not absolute. Blaming a merge for a pre-existing failure trains
    everyone to ignore this, which is worse than not having it at all."""
    monkeypatch.setattr(bsc, "failing_tests", lambda *a, **k: {"tests/t.py::test_old"})
    monkeypatch.setattr(bsc, "_failures_at", lambda *a, **k: {"tests/t.py::test_old"})
    out = bsc.verify_merge(str(repo), "base", "merged", test_files=["tests/t.py"])
    assert out["ok"] is True
    assert out["already_failing"] == ["tests/t.py::test_old"]
    assert out["newly_failing"] == []


def test_an_unrunnable_check_is_not_reported_as_green(repo, monkeypatch):
    """None is not an empty set. A run that could not happen says nothing about the
    merge, and calling it 'no failures' is exactly the shape of bug this whole
    session kept finding."""
    monkeypatch.setattr(bsc, "failing_tests", lambda *a, **k: None)
    out = bsc.verify_merge(str(repo), "base", "merged", test_files=["tests/t.py"])
    assert "could not run" in out["reason"]
    assert out["newly_failing"] == []


def test_an_unmeasurable_base_still_reports_the_red(repo, monkeypatch):
    monkeypatch.setattr(bsc, "failing_tests", lambda *a, **k: {"tests/t.py::test_x"})
    monkeypatch.setattr(bsc, "_failures_at", lambda *a, **k: None)
    out = bsc.verify_merge(str(repo), "base", "merged", test_files=["tests/t.py"])
    assert out["ok"] is False
    assert "could not be measured" in out["reason"]


def test_verify_never_raises(repo, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("pytest exploded")

    monkeypatch.setattr(bsc, "failing_tests", boom)
    out = bsc.verify_merge(str(repo), "base", "merged", test_files=["tests/t.py"])
    assert out["ok"] is True and "self-check error" in out["reason"]


# ── what happens on a regression ──────────────────────────────────────────────

def test_a_regression_alerts_and_repauses(repo, monkeypatch):
    monkeypatch.setenv("ORCH_BEETHOVEN_AUTOPAUSE", "true")
    alerts, updates = [], []

    class FakeDb:
        @staticmethod
        def insert(table, row):
            alerts.append((table, row))

        @staticmethod
        def update(table, match, patch):
            updates.append((table, match, patch))

    monkeypatch.setitem(sys.modules, "db", FakeDb)
    result = {"ok": False, "newly_failing": ["tests/t.py::test_x"],
              "already_failing": [], "tests": [], "reason": ""}
    bsc.report(str(repo), "aaaaaaaaaaaa", "bbbbbbbbbbbb", result=result)

    assert alerts and alerts[0][0] == "runner_alerts"
    assert alerts[0][1]["kind"] == bsc.ALERT_KIND
    assert "test_x" in alerts[0][1]["detail"]
    assert updates and updates[0][1] == {"scope": "project", "project": "beethoven"}
    assert updates[0][2]["paused"] is True
    assert "REVERSIBLE" in updates[0][2]["reason"]


def test_autopause_can_be_switched_off(repo, monkeypatch):
    monkeypatch.setenv("ORCH_BEETHOVEN_AUTOPAUSE", "false")
    updates = []

    class FakeDb:
        @staticmethod
        def insert(table, row):
            pass

        @staticmethod
        def update(table, match, patch):
            updates.append(patch)

    monkeypatch.setitem(sys.modules, "db", FakeDb)
    bsc.report(str(repo), "a" * 12, "b" * 12,
               result={"ok": False, "newly_failing": ["t::x"], "already_failing": [],
                       "tests": [], "reason": ""})
    assert updates == []


def test_a_green_merge_neither_alerts_nor_pauses(repo, monkeypatch):
    touched = []

    class FakeDb:
        @staticmethod
        def insert(table, row):
            touched.append(row)

        @staticmethod
        def update(table, match, patch):
            touched.append(patch)

    monkeypatch.setitem(sys.modules, "db", FakeDb)
    bsc.report(str(repo), "a" * 12, "b" * 12,
               result={"ok": True, "newly_failing": [], "already_failing": [],
                       "tests": [], "reason": "green"})
    assert touched == []


def test_the_baseline_never_moves_the_live_tree():
    """Checking the base out in place would swap the orchestrator's source from under
    the running fleet. The baseline must go through commit_overlay."""
    import inspect
    source = inspect.getsource(bsc._failures_at)
    assert "commit_overlay" in source
    for forbidden in ("checkout", "reset", "stash"):
        assert f'"{forbidden}"' not in source, \
            f"the baseline must not run git {forbidden} in the live repo"
