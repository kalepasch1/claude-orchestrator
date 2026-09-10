"""publish_recovery_ledger — read every ledger shape, and never call zero rows a success.

Three tools in this repo emit recovery ledgers and they disagree on the item key.
`tools/reconcile_*.py` and `tools/reconcile-local-evidence.mjs` write `items[]`
with `ref`/`files`; `scripts/reconcile-rescue-refs.mjs` writes `records[]` with
`source`/`source_sha`/`touched_files`.

The publisher read only `items`. Pointed at a rescue-ref ledger it therefore
published NOTHING — and exited 0 printing `"total": 0, "written": 0, "failed": 0`,
which reads exactly like a clean pass over an empty evidence set. That is the
failure mode worth pinning: not a crash, but a silent no-op wearing a success
message, while the durable queue provenance the recovery contract requires was
never written for a 791-item ledger.

So these tests pin, in order of importance: both shapes are read, the fields are
mapped rather than dropped, and an unreadable ledger fails loudly instead of
reporting success.
"""
import json
import os
import sys

import pytest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

prl = pytest.importorskip("publish_recovery_ledger")


class _Args:
    task_slug = "slug"
    project = "beethoven"
    branch = "agent/slug"
    commit = "abc1234"


ITEMS_LEDGER = {
    "audit_fingerprint": "f" * 64,
    "items": [
        {
            "ref": "refs/orch-rescue/aaa",
            "kind": "rescue_ref",
            "classification": "RECOVERABLE_VALUE",
            "disposition": "apply in an isolated worktree",
            "evidence": "unique content",
            "files": ["runner/db.py", "runner/db.py", "runner/log.py"],
        }
    ],
}

RECORDS_LEDGER = {
    "audit_fingerprint": "e" * 64,
    "records": [
        {
            "source": "refs/orch-rescue/20260910T093839-claude-orchestrator",
            "source_sha": "f9ae47e07a43",
            "classification": "CONFLICTED_NEEDS_FOCUSED_TASK",
            "classification_reason": "diff does not apply cleanly onto base",
            "disposition": "queue a focused conflict-resolution task",
            "touched_files": ["CLAUDE.md", "runner/db.py"],
        }
    ],
}


def test_reads_items_shape():
    assert len(prl.ledger_items(ITEMS_LEDGER)) == 1


def test_reads_records_shape():
    """The regression. Before the fix this returned [] and the run reported success."""
    assert len(prl.ledger_items(RECORDS_LEDGER)) == 1


def test_empty_ledger_yields_no_items():
    assert prl.ledger_items({"audit_fingerprint": "a" * 64}) == []
    assert prl.ledger_items({"items": [], "records": []}) == []


def test_records_shape_maps_source_and_files():
    """A record read but mapped to empty strings is no better than not reading it."""
    item = prl.ledger_items(RECORDS_LEDGER)[0]
    payload = prl.build_payload(item, RECORDS_LEDGER, _Args())

    assert payload["source"] == "refs/orch-rescue/20260910T093839-claude-orchestrator"
    assert payload["classification"] == "CONFLICTED_NEEDS_FOCUSED_TASK"
    assert payload["file_count"] == 2
    assert payload["files"] == ["CLAUDE.md", "runner/db.py"]
    # records[] has no `evidence` key; the reason carries the same information.
    assert payload["evidence"] == "diff does not apply cleanly onto base"


def test_items_shape_still_maps_ref_and_files():
    item = prl.ledger_items(ITEMS_LEDGER)[0]
    payload = prl.build_payload(item, ITEMS_LEDGER, _Args())

    assert payload["source"] == "refs/orch-rescue/aaa"
    assert payload["source_kind"] == "rescue_ref"
    assert payload["evidence"] == "unique content"
    # de-duplicated, not merely truncated
    assert payload["file_count"] == 2


def test_file_list_is_capped_but_count_is_not():
    """The blob on the branch is the full record; the row must not become the diff."""
    many = {
        "audit_fingerprint": "d" * 64,
        "records": [{
            "source": "refs/orch-rescue/big",
            "classification": "SUPERSEDED_BY_NEWER",
            "touched_files": ["f%03d.py" % i for i in range(200)],
        }],
    }
    payload = prl.build_payload(prl.ledger_items(many)[0], many, _Args())
    assert len(payload["files"]) == 20
    assert payload["file_count"] == 200


def test_unreadable_ledger_exits_nonzero(tmp_path, capsys):
    """A fingerprinted ledger whose items cannot be read is a shape mismatch.

    Exiting 0 here is what hid the bug for a 791-item ledger, so the guard is
    asserted on the exit code, not on the log line.
    """
    bad = tmp_path / "ledger.json"
    bad.write_text(json.dumps({"audit_fingerprint": "c" * 64, "entries": [{"a": 1}]}))

    argv = sys.argv
    sys.argv = [
        "publish_recovery_ledger", "--ledger", str(bad), "--task-slug", "slug",
        "--project", "beethoven", "--branch", "agent/slug", "--commit", "abc1234",
        "--dry-run",
    ]
    try:
        rc = prl.main()
    finally:
        sys.argv = argv

    assert rc != 0
    assert "no readable items" in capsys.readouterr().err


def test_missing_fingerprint_still_refuses():
    """Pre-existing guard: untraceable records must not be published."""
    argv = sys.argv
    sys.argv = [
        "publish_recovery_ledger", "--ledger", "/nonexistent-on-purpose.json",
        "--task-slug", "s", "--project", "p", "--branch", "b", "--commit", "c",
        "--dry-run",
    ]
    try:
        with pytest.raises((FileNotFoundError, SystemExit)):
            prl.main()
    finally:
        sys.argv = argv
