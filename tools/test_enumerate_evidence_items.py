"""Tests for tools.enumerate_evidence_items.

The headline acceptance test runs the tool over the exact TASK text that
motivated it: the report must contain the FAILURE entry and must explicitly
mark the absent live-source enumeration as MISSING_IN_INPUT.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.enumerate_evidence_items import (  # noqa: E402
    build_report,
    extract_evidence_items,
    main,
)

TASK_TEXT = (
    "TASK: reconcile local evidence for beethoven 939f3db3fe9c\n"
    "FAILURE/SLOG: agent session crashed before it could enumerate the live source"
)


def _by_status(report, status):
    return [item for item in report if item["status"] == status]


def test_acceptance_task_text_reports_failure_and_missing_section():
    report = build_report(TASK_TEXT)

    extracted = _by_status(report, "EXTRACTED")
    assert any(item["inferred_type"] == "failure" for item in extracted)

    missing = _by_status(report, "MISSING_IN_INPUT")
    assert missing, "must not silently assume the unprovided live-source list"
    assert missing[0]["source_path"] == "UNKNOWN"
    assert missing[0]["inferred_type"] == "live_source_enumeration"


def test_report_is_json_serializable():
    json.dumps(build_report(TASK_TEXT))


@pytest.mark.parametrize("bad", [None, "", "   ", 42, [], {}])
def test_extract_is_fail_soft_on_bad_input(bad):
    assert extract_evidence_items(bad) == []


def test_bad_input_still_yields_a_missing_marker():
    report = build_report(None)
    assert _by_status(report, "MISSING_IN_INPUT")


def test_extracts_paths_stashes_worktrees_refs_and_digests():
    text = (
        "stash@{3} holds /Users/kpasch/Documents/beethoven/claude-orchestrator/runner/x.py\n"
        "worktree claude-orchestrator-wt/recover-slice-2 tracks origin/master\n"
        "refs/remotes/origin/agent/foo at 939f3db3fe9c.\n"
    )
    kinds = {item["inferred_type"] for item in extract_evidence_items(text)}
    assert "stash" in kinds
    assert "path" in kinds
    assert "worktree" in kinds
    assert "digest" in kinds
    assert {"remote_ref", "ref"} & kinds


def test_ids_are_stable_and_unique():
    items = extract_evidence_items(TASK_TEXT + "\nstash@{0} stash@{1}")
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids))
    assert extract_evidence_items(TASK_TEXT)[0]["id"] == build_report(TASK_TEXT)[0]["id"]


def test_every_item_has_the_required_fields():
    for item in build_report(TASK_TEXT):
        assert set(["id", "source_path", "inferred_type", "sample", "status"]) <= set(item)
        assert item["status"] in ("EXTRACTED", "MISSING_IN_INPUT")


def test_cli_round_trip(tmp_path, capsys):
    snapshot = tmp_path / "snapshot.txt"
    snapshot.write_text(TASK_TEXT, encoding="utf-8")
    assert main(["--input", str(snapshot)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert _by_status(report, "MISSING_IN_INPUT")


def test_cli_missing_file_is_fail_soft(capsys):
    assert main(["--input", "/nonexistent/snapshot.txt"]) == 0
    assert json.loads(capsys.readouterr().out)


def test_module_is_runnable_as_a_script(tmp_path):
    snapshot = tmp_path / "s.txt"
    snapshot.write_text(TASK_TEXT, encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "tools.enumerate_evidence_items", "-i", str(snapshot)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)
