#!/usr/bin/env python3
"""Coverage for reconcile_conflict_notouch.

The invariants under test:
  * a conflicted path that the recovery branch touched is ALWAYS a violation;
  * a diff that could not be read fails the gate rather than passing it;
  * every conflicted item gets exactly one follow-up — no fan-out, no silent drop.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reconcile_conflict_notouch as nt  # noqa: E402
import reconcile_followup_queue as rfq  # noqa: E402

FINGERPRINT = "a92ff481c0bad121e4c407fc10f3d96046c11b28ec1004cd6e328dab4e173a7c"


def _record(cls=nt.CONFLICTED, source="refs/heads/codex/thing", **kw):
    base = {"source": source, "classification": cls, "unique_commits": 2,
            "paths": ["runner/a.py"], "detail": ""}
    base.update(kw)
    return base


# ── attribution ─────────────────────────────────────────────────────────────

def test_only_conflicted_records_contribute_paths():
    records = [_record(paths=["runner/a.py"]),
               _record("RECOVERABLE_VALUE", source="refs/heads/x", paths=["runner/b.py"])]
    attributed = nt.conflicted_paths(records)
    assert "runner/a.py" in attributed
    assert "runner/b.py" not in attributed


def test_paths_files_and_path_fields_are_all_read():
    rec = _record(paths=["runner/a.py"], files=["runner/b.py"], path="runner/c.py")
    assert set(nt.conflicted_paths([rec])) == {"runner/a.py", "runner/b.py", "runner/c.py"}


def test_dot_slash_prefix_is_normalised():
    attributed = nt.conflicted_paths([_record(paths=["./runner/a.py"])])
    assert "runner/a.py" in attributed


def test_two_sources_claiming_one_path_are_both_named():
    records = [_record(source="refs/heads/one"), _record(source="refs/heads/two")]
    assert nt.conflicted_paths(records)["runner/a.py"] == ["refs/heads/one",
                                                           "refs/heads/two"]


def test_empty_records_is_empty_not_an_error():
    assert nt.conflicted_paths([]) == {}
    assert nt.conflicted_paths(None) == {}


# ── notouch gate ────────────────────────────────────────────────────────────

def test_untouched_conflicted_path_passes():
    gate = nt.notouch_gate([_record()], ["runner/unrelated.py", "docs/readme.md"])
    assert gate["ok"] is True
    assert gate["violations"] == []


def test_touched_conflicted_path_is_a_violation_naming_the_source():
    gate = nt.notouch_gate([_record()], ["runner/a.py"])
    assert gate["ok"] is False
    assert gate["violations"][0]["path"] == "runner/a.py"
    assert gate["violations"][0]["sources"] == ["refs/heads/codex/thing"]


def test_recoverable_paths_may_be_touched_freely():
    records = [_record("RECOVERABLE_VALUE", paths=["runner/b.py"])]
    assert nt.notouch_gate(records, ["runner/b.py"])["ok"] is True


def test_empty_diff_passes():
    assert nt.notouch_gate([_record()], [])["ok"] is True


# ── exactly-one gate ────────────────────────────────────────────────────────

def test_one_plan_per_conflicted_item_passes():
    records = [_record()]
    plans = rfq.plan_followups(records, FINGERPRINT)
    gate = nt.exactly_one_gate(records, plans)
    assert gate["ok"] is True
    assert gate["covered"] == 1


def test_missing_plan_fails_and_names_the_source():
    gate = nt.exactly_one_gate([_record()], [])
    assert gate["ok"] is False
    assert gate["missing"] == ["refs/heads/codex/thing"]


def test_two_plans_for_one_source_is_fan_out():
    records = [_record()]
    plans = [{"source": "refs/heads/codex/thing", "classification": nt.CONFLICTED,
              "slug": "reconcile-conflict-a"},
             {"source": "refs/heads/codex/thing", "classification": nt.CONFLICTED,
              "slug": "reconcile-conflict-b"}]
    gate = nt.exactly_one_gate(records, plans)
    assert gate["ok"] is False
    assert gate["duplicated"][0]["source"] == "refs/heads/codex/thing"


def test_adopted_slug_counts_as_the_one_followup():
    """Re-running a reconciliation adopts rather than duplicates — still exactly one."""
    records = [_record()]
    plans = rfq.plan_followups(records, FINGERPRINT)
    plans[0]["queued_slug"] = plans[0]["slug"]
    assert nt.exactly_one_gate(records, plans)["ok"] is True


def test_settled_items_are_ignored_by_the_gate():
    records = [_record("ALREADY_PRESENT")]
    gate = nt.exactly_one_gate(records, [])
    assert gate["ok"] is True
    assert gate["covered"] == 0


# ── observation against a real repo ─────────────────────────────────────────

def _git(repo, *args):
    subprocess.run(("git", "-C", str(repo)) + args, check=True,
                   capture_output=True, text=True, timeout=30)


@pytest.fixture()
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "kalepasch@gmail.com")
    _git(path, "config", "user.name", "kalepasch1")
    (path / "runner").mkdir()
    (path / "runner" / "a.py").write_text("original\n")
    (path / "runner" / "b.py").write_text("original\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "baseline")
    return path


def test_changed_paths_sees_only_the_branch_edit(repo):
    _git(repo, "checkout", "-q", "-b", "agent/x")
    (repo / "runner" / "b.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "edit b")
    paths, err = nt.changed_paths(repo, "main", "HEAD")
    assert err == ""
    assert paths == ["runner/b.py"]


def test_run_passes_when_the_conflicted_file_was_left_alone(repo):
    _git(repo, "checkout", "-q", "-b", "agent/x")
    (repo / "runner" / "b.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "edit b")
    records = [_record(paths=["runner/a.py"])]
    plans = rfq.plan_followups(records, FINGERPRINT)
    report = nt.run(records, plans, repo=repo, baseline_ref="main")
    assert report["ok"] is True


def test_run_fails_when_the_conflicted_file_was_overwritten(repo):
    _git(repo, "checkout", "-q", "-b", "agent/x")
    (repo / "runner" / "a.py").write_text("overwritten\n")
    _git(repo, "commit", "-qam", "resolve a on the side")
    records = [_record(paths=["runner/a.py"])]
    plans = rfq.plan_followups(records, FINGERPRINT)
    report = nt.run(records, plans, repo=repo, baseline_ref="main")
    assert report["ok"] is False
    assert report["notouch"]["violations"][0]["path"] == "runner/a.py"


def test_unreadable_diff_fails_the_gate_rather_than_passing_it(repo):
    records = [_record()]
    report = nt.run(records, rfq.plan_followups(records, FINGERPRINT),
                    repo=repo, baseline_ref="refs/heads/does-not-exist")
    assert report["ok"] is False
    assert "could not read diff" in report["error"]


def test_missing_baseline_ref_is_an_explicit_error():
    paths, err = nt.changed_paths(".", "", "HEAD")
    assert paths == []
    assert err == "no baseline ref given"


def test_kill_switch_disables_without_claiming_success(repo, monkeypatch):
    monkeypatch.setenv("ORCH_NOTOUCH_GATE_ENABLED", "false")
    report = nt.run([_record()], [], repo=repo, baseline_ref="main")
    assert report["ok"] is False
    assert "disabled" in report["error"]


def test_nonexistent_repo_is_fail_soft_not_a_crash():
    paths, err = nt.changed_paths("/nonexistent/repo/path", "main", "HEAD")
    assert paths == []
    assert err
