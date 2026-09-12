#!/usr/bin/env python3
"""Coverage for tools/recovery_ledger_generate.

The invariants under test:
  * exactly one record per evidence item, always, including for junk input;
  * every record carries the audit fingerprint;
  * a commit is COPIED from evidence and never invented — an item with no recoverable
    diff says QUEUED_FOCUSED_FOLLOW_UP and names its follow-up instead;
  * the output is deterministic, so two runs diff to nothing.
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import recovery_ledger_generate as gen  # noqa: E402

FP = "939f3db3fe9cd10e7fbf0d008a4bcb629ac76aabf35f5f4231a2c6027d2f6fae"


def item(classification="RECOVERABLE_VALUE", source="refs/heads/codex/thing", **kw):
    base = {"ref": source, "classification": classification, "files": ["a.py"]}
    base.update(kw)
    return base


# ── one record per item ─────────────────────────────────────────────────────

def test_exactly_one_record_per_evidence_item():
    items = [item(source=f"refs/heads/codex/x{i}") for i in range(7)]
    ledger = gen.build_ledger(items, FP)
    assert ledger["item_count"] == 7
    assert len(ledger["items"]) == 7


def test_input_order_is_preserved():
    items = [item(source="refs/heads/b"), item(source="refs/heads/a")]
    assert [r["source"] for r in gen.build_ledger(items, FP)["items"]] == \
        ["refs/heads/b", "refs/heads/a"]


def test_an_empty_evidence_list_is_an_empty_ledger():
    assert gen.build_ledger([], FP)["item_count"] == 0
    assert gen.build_ledger(None, FP)["item_count"] == 0


def test_a_junk_item_still_produces_a_record():
    """Dropping an unparseable item is how evidence goes missing silently."""
    ledger = gen.build_ledger([{}, {"nothing": "useful"}], FP)
    assert ledger["item_count"] == 2


# ── the fingerprint ─────────────────────────────────────────────────────────

def test_every_record_carries_the_fingerprint():
    ledger = gen.build_ledger([item(), item(source="refs/heads/other")], FP)
    assert all(r["audit_fingerprint"] == FP for r in ledger["items"])
    assert ledger["audit_fingerprint"] == FP


@pytest.mark.parametrize("bad", ["", None, "short", "z" * 64, FP + "extra"])
def test_a_malformed_fingerprint_is_refused(bad):
    """Publishing under a wrong fingerprint makes the ledger unfindable later."""
    with pytest.raises(ValueError):
        gen.build_ledger([item()], bad)


def test_an_uppercase_fingerprint_is_accepted():
    assert gen.build_ledger([item()], FP.upper())["audit_fingerprint"] == FP.upper()


# ── commits are never invented ──────────────────────────────────────────────

def test_an_item_without_a_commit_is_queued_for_follow_up():
    record = gen.build_ledger([item()], FP)["items"][0]
    assert record["disposition"] == gen.DISPOSITION_FOLLOW_UP
    assert record["planned_followup_task"]


def test_a_queued_item_has_no_commit_branch_or_task():
    """The core rule: do not imply work landed somewhere when it did not."""
    record = gen.build_ledger([item()], FP, task_slug="some-task",
                              branch="agent/some-branch")["items"][0]
    assert record["commit"] == ""
    assert record["branch"] == ""
    assert record["task_slug"] == ""


def test_an_item_with_a_real_commit_records_full_provenance():
    record = gen.build_ledger([item(commit="abc1234")], FP, task_slug="t",
                              branch="agent/b")["items"][0]
    assert record["disposition"] == gen.DISPOSITION_RECOVERED
    assert (record["commit"], record["branch"], record["task_slug"]) == \
        ("abc1234", "agent/b", "t")


def test_a_sha_field_is_accepted_as_the_commit():
    record = gen.build_ledger([item(sha="deadbee")], FP)["items"][0]
    assert record["disposition"] == gen.DISPOSITION_RECOVERED


def test_a_conflicted_item_is_queued_not_resolved():
    record = gen.build_ledger([item("CONFLICTED_NEEDS_FOCUSED_TASK")], FP)["items"][0]
    assert record["disposition"] == gen.DISPOSITION_FOLLOW_UP
    assert record["planned_followup_task"].startswith("reconcile-conflict-")


def test_a_recoverable_item_names_a_recover_follow_up():
    record = gen.build_ledger([item("RECOVERABLE_VALUE")], FP)["items"][0]
    assert record["planned_followup_task"].startswith("reconcile-recover-")


# ── settled and unknown ─────────────────────────────────────────────────────

@pytest.mark.parametrize("label", ["ALREADY_PRESENT", "SUPERSEDED_BY_NEWER",
                                   "ACTIVE_IN_ANOTHER_TASK"])
def test_settled_items_need_no_action(label):
    record = gen.build_ledger([item(label)], FP)["items"][0]
    assert record["disposition"] == gen.DISPOSITION_SETTLED
    assert record["planned_followup_task"] == ""


def test_an_unrecognised_label_becomes_unknown_and_is_triaged():
    record = gen.build_ledger([item("SOMETHING_ELSE")], FP)["items"][0]
    assert record["classification"] == gen.UNKNOWN
    assert record["disposition"] == gen.DISPOSITION_UNKNOWN
    assert record["planned_followup_task"].startswith("reconcile-triage-")


def test_counts_are_reported_per_classification():
    ledger = gen.build_ledger(
        [item("RECOVERABLE_VALUE"), item("RECOVERABLE_VALUE", source="refs/heads/b"),
         item("ALREADY_PRESENT", source="refs/heads/c")], FP)
    assert ledger["counts"] == {"ALREADY_PRESENT": 1, "RECOVERABLE_VALUE": 2}


# ── determinism ─────────────────────────────────────────────────────────────

def test_two_runs_produce_identical_json(tmp_path):
    items = [item(source=f"refs/heads/codex/x{i}") for i in range(5)]
    first = gen.write_ledger(gen.build_ledger(items, FP), str(tmp_path / "a.json"))
    second = gen.write_ledger(gen.build_ledger(items, FP), str(tmp_path / "b.json"))
    assert open(first).read() == open(second).read()


def test_follow_up_names_are_stable_across_runs():
    """Derived from the ref, not a counter — otherwise a re-run fans out duplicates."""
    a = gen.followup_task_name("refs/heads/codex/thing", "RECOVERABLE_VALUE")
    b = gen.followup_task_name("codex/thing", "RECOVERABLE_VALUE")
    assert a == b


def test_the_ledger_contains_no_timestamp():
    """A clock in the output would make every run differ."""
    blob = json.dumps(gen.build_ledger([item()], FP))
    assert "timestamp" not in blob and "generated_at" not in blob


# ── provenance gate ─────────────────────────────────────────────────────────

def test_the_gate_passes_when_every_item_is_accounted_for():
    ledger = gen.build_ledger([item(), item("ALREADY_PRESENT", source="refs/heads/b")], FP)
    assert gen.provenance_gate(ledger)["ok"] is True


def test_the_gate_fails_on_an_unknown_item():
    ledger = gen.build_ledger([item("MYSTERY")], FP)
    gate = gen.provenance_gate(ledger)
    assert gate["ok"] is False and gate["unknown"]


# ── the shape the publisher consumes ────────────────────────────────────────

def test_records_carry_every_field_the_publisher_reads():
    """recovery_ledger_publish.record_for reads these by name."""
    record = gen.build_ledger([item()], FP, evidence_kind="local-branches",
                              base="master")["items"][0]
    for field in ("audit_fingerprint", "evidence_kind", "base", "source", "sha",
                  "classification", "disposition", "evidence", "file_count",
                  "task_slug", "branch", "commit"):
        assert field in record, field


def test_file_count_falls_back_to_the_files_list():
    assert gen.build_ledger([item(files=["a.py", "b.py"])], FP)["items"][0]["file_count"] == 2


# ── CLI ─────────────────────────────────────────────────────────────────────

def _cli(tmp_path, items, fingerprint=FP, extra=()):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(items))
    out = tmp_path / "ledger.json"
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "recovery_ledger_generate.py"),
         "--evidence", str(evidence), "--fingerprint", fingerprint, "--out", str(out),
         *extra],
        capture_output=True, text=True, timeout=120)
    return proc, out


def test_cli_writes_one_record_per_item(tmp_path):
    proc, out = _cli(tmp_path, [item(), item(source="refs/heads/b")])
    assert proc.returncode == 0, proc.stderr
    ledger = json.loads(out.read_text())
    assert ledger["item_count"] == 2
    assert all(r["audit_fingerprint"] == FP for r in ledger["items"])


def test_cli_exits_nonzero_when_an_item_is_unclassified(tmp_path):
    proc, _ = _cli(tmp_path, [item("MYSTERY")])
    assert proc.returncode == 1


def test_cli_refuses_a_bad_fingerprint(tmp_path):
    proc, _ = _cli(tmp_path, [item()], fingerprint="nope")
    assert proc.returncode == 2


def test_cli_accepts_a_wrapped_evidence_object(tmp_path):
    evidence = tmp_path / "e.json"
    evidence.write_text(json.dumps({"items": [item()]}))
    out = tmp_path / "l.json"
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "recovery_ledger_generate.py"),
         "--evidence", str(evidence), "--fingerprint", FP, "--out", str(out)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(out.read_text())["item_count"] == 1


def test_cli_reports_a_missing_evidence_file(tmp_path):
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "recovery_ledger_generate.py"),
         "--evidence", str(tmp_path / "nope.json"), "--fingerprint", FP,
         "--out", str(tmp_path / "l.json")],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2
