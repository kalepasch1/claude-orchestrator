"""Tests for the producer-side self-feeding exclusion.

Acceptance criteria come from the original task
(`followup-reconcile-evidence-generator-is-self-feeding`):

  * a rescue ref containing ONLY a recovery ledger is excluded, not classified;
  * a run's own scaffolding is excluded;
  * exclusions surface under an explicit key with a count;
  * and — the restriction that matters most — a mixed item is KEPT, because
    excluding it to tidy the loop would discard real unshipped work.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestration_artifacts import (  # noqa: E402
    REASON_BOOKKEEPING,
    REASON_SCAFFOLDING,
    all_paths_are_orchestration,
    classify_exclusion,
    is_orchestration_path,
    is_scaffolding_path,
    partition_evidence,
)


def test_ledger_and_reconcile_paths_are_bookkeeping():
    assert is_orchestration_path(".orch/recovery-ledger-abc123.json")
    assert is_orchestration_path("docs/tasks/chatgpt-local-reconcile-tomorrow-7fdd.md")
    assert is_orchestration_path("docs/recovery-ledger/2026-08-24.md")
    assert is_orchestration_path("scripts/reconcile-evidence.mjs")
    assert is_orchestration_path("tools/reconcile_evidence.py")
    assert is_orchestration_path(".recovery-intent-backlog-batch-tomorrow-008fe42.txt")


def test_real_source_files_are_not_bookkeeping():
    # Anchored patterns: a real file cannot match by merely containing the word.
    assert not is_orchestration_path("src/reconcile-user-balances.ts")
    assert not is_orchestration_path("app/docs/recovery-ledger-notes.tsx")
    assert not is_orchestration_path("scripts/lib/reconcile-evidence.mjs")
    assert not is_orchestration_path("README.md")


def test_fleet_worktrees_are_scaffolding():
    assert is_scaffolding_path("/Users/k/Documents/tomorrow/tomorrow-wt/some-slug/a.ts")
    assert is_scaffolding_path("/private/tmp/beethoven-baseline/x.py")
    assert not is_scaffolding_path("src/components/Button.tsx")


def test_empty_path_set_is_never_bookkeeping():
    # "We could not read what it carries" != "it carries only ledgers".
    assert not all_paths_are_orchestration([])
    assert not all_paths_are_orchestration(None)
    excluded, _reason, _detail = classify_exclusion([])
    assert excluded is False


def test_rescue_ref_with_only_a_ledger_is_excluded():
    excluded, reason, detail = classify_exclusion([".orch/recovery-ledger-250fb499.json"])
    assert excluded is True
    assert reason == REASON_BOOKKEEPING
    assert "recovery-ledger" in detail


def test_run_scaffolding_is_excluded_with_its_own_reason():
    excluded, reason, _detail = classify_exclusion(
        ["/Users/k/Documents/darwn/darwn-wt/slug-a/file.ts"])
    assert excluded is True
    assert reason == REASON_SCAFFOLDING


def test_one_real_file_keeps_the_whole_item():
    # THE restriction. Excluding this would discard real unshipped work.
    excluded, _reason, _detail = classify_exclusion([
        ".orch/recovery-ledger-abc.json",
        "src/lib/pricing.ts",
    ])
    assert excluded is False


def test_partition_reports_exclusions_rather_than_dropping_them():
    items = [
        {"ref": "refs/orch-rescue/a", "sha": "aaa"},   # ledger only  -> excluded
        {"ref": "refs/orch-rescue/b", "sha": "bbb"},   # real code    -> kept
    ]
    paths = {
        "aaa": [".orch/recovery-ledger-a.json"],
        "bbb": ["src/index.ts"],
    }
    kept, excluded = partition_evidence(items, lambda row: paths[row["sha"]])
    assert [k["ref"] for k in kept] == ["refs/orch-rescue/b"]
    assert len(excluded) == 1
    assert excluded[0]["excluded_reason"] == REASON_BOOKKEEPING
    assert excluded[0]["excluded_detail"]          # never silent
    assert excluded[0]["ref"] == "refs/orch-rescue/a"  # keeps its identity


def test_unreadable_item_is_kept_not_excluded():
    def boom(_row):
        raise RuntimeError("diff-tree failed")

    kept, excluded = partition_evidence([{"ref": "x", "sha": ""}], boom)
    assert len(kept) == 1 and not excluded
