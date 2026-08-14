import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import phantom_recovery


def test_operator_phantom_is_requeued_with_reconcile_and_preservation_contract():
    database = MagicMock()
    database.select.return_value = [{
        "id": "t1", "slug": "dropbox-manual-improvement", "state": "PHANTOM_UNVERIFIED",
        "prompt": "Implement the missing behavior", "note": "audit note",
    }]
    database.update.return_value = [{"id": "t1", "state": "QUEUED"}]

    with patch.object(phantom_recovery, "db", database), \
         patch.dict(sys.modules, {"steering": MagicMock()}):
        result = phantom_recovery.recover(limit=10)

    assert result["recovered"] == 1
    match, values = database.update.call_args.args[1:]
    assert match == {"id": "t1", "state": "PHANTOM_UNVERIFIED"}
    assert values["state"] == "QUEUED"
    assert "Preserve every newer or\noverlapping improvement" in values["prompt"]
    assert values["prompt"].endswith("Implement the missing behavior")
    assert values["submitted_by_label"] == "Kale Pasch (legacy dropbox)"
    assert values["priority"] == 10


def test_no_phantoms_is_idempotent():
    database = MagicMock()
    database.select.return_value = []

    with patch.object(phantom_recovery, "db", database):
        result = phantom_recovery.recover(limit=10)

    assert result == {
        "scanned": 0, "recovered": 0, "consolidated": 0,
        "restored": 0, "recarded": 0, "infrastructure_holds": 0,
        "slugs": [], "restored_slugs": [], "recarded_slugs": [],
    }
    database.update.assert_not_called()


def test_active_slug_consolidates_duplicate_without_second_writer():
    database = MagicMock()
    database.select.side_effect = [
        [{"id": "duplicate", "slug": "dropbox-same", "state": "PHANTOM_UNVERIFIED",
          "prompt": "Improve it", "note": "audit"}],
        [],
        [{"id": "keeper", "slug": "dropbox-same", "state": "QUEUED"}],
    ]
    database.update.side_effect = [None, [{"id": "duplicate", "state": "DECOMPOSED"}]]

    with patch.object(phantom_recovery, "db", database):
        result = phantom_recovery.recover(limit=10)

    assert result["recovered"] == 0
    assert result["consolidated"] == 1
    _match, values = database.update.call_args.args[1:]
    assert values["state"] == "DECOMPOSED"
    assert values["deps"] == ["dropbox-same"]


def test_staged_artifact_is_restored_to_merged_without_regeneration():
    database = MagicMock()
    staged = {
        "id": "t1", "slug": "dropbox-staged", "state": "QUEUED",
        "project_id": "p1", "artifact_commit": "a" * 40,
        "prompt": "Implement it", "note": "old recovery",
    }
    # PHANTOM query empty, stranded-artifact query returns the old requeued row.
    database.select.side_effect = [[], [staged]]
    database.update.return_value = [{"id": "t1", "state": "MERGED"}]

    with patch.object(phantom_recovery, "db", database), \
         patch.object(phantom_recovery.merge_truth, "resolve_target",
                      return_value=("/repo", "orchestrator/dev", None)), \
         patch.object(phantom_recovery.merge_truth, "verify_merge_reachable",
                      return_value=(phantom_recovery.merge_truth.OK,
                                    "aaaaaaaaaaaa is an ancestor of origin/orchestrator/dev")), \
         patch.object(phantom_recovery.merge_truth, "gate_merged_patch",
                      side_effect=lambda _task, body, **_kwargs: body):
        result = phantom_recovery.recover(limit=10)

    assert result["restored"] == 1
    assert result["recovered"] == 0
    match, values = database.update.call_args.args[1:]
    assert match == {"id": "t1", "state": "QUEUED"}
    assert values["state"] == "MERGED"
    assert values["artifact_commit"] == "a" * 40
    assert "no regeneration" in values["note"]


def test_existing_unintegrated_artifact_is_done_and_recarded():
    database = MagicMock()
    row = {
        "id": "t1", "slug": "dropbox-existing", "state": "PHANTOM_UNVERIFIED",
        "project_id": "p1", "artifact_commit": "b" * 40,
        "prompt": "Implement it", "note": "audit",
    }
    database.select.side_effect = [[row], []]
    database.update.return_value = [{"id": "t1", "state": "DONE"}]

    with patch.object(phantom_recovery, "db", database), \
         patch.object(phantom_recovery.merge_truth, "resolve_target",
                      return_value=("/repo", "orchestrator/dev", None)), \
         patch.object(phantom_recovery.merge_truth, "verify_merge_reachable",
                      return_value=(phantom_recovery.merge_truth.PHANTOM,
                                    "commit bbbbbbbbbbbb is not an ancestor of origin/orchestrator/dev")), \
         patch.object(phantom_recovery, "_ensure_card", return_value=True):
        result = phantom_recovery.recover(limit=10)

    assert result["recarded"] == 1
    assert result["recovered"] == 0
    match, values = database.update.call_args.args[1:]
    assert match == {"id": "t1", "state": "PHANTOM_UNVERIFIED"}
    assert values["state"] == "DONE"
    assert "without regeneration" in values["note"]


def test_infrastructure_error_never_requeues_artifact():
    database = MagicMock()
    row = {
        "id": "t1", "slug": "dropbox-unknown", "state": "PHANTOM_UNVERIFIED",
        "project_id": "p1", "artifact_commit": "c" * 40,
        "prompt": "Implement it", "note": "audit",
    }
    database.select.side_effect = [[row], []]

    with patch.object(phantom_recovery, "db", database), \
         patch.object(phantom_recovery.merge_truth, "resolve_target",
                      return_value=("/repo", "orchestrator/dev", None)), \
         patch.object(phantom_recovery.merge_truth, "verify_merge_reachable",
                      return_value=(phantom_recovery.merge_truth.INFRA_ERROR,
                                    "fetch timed out")):
        result = phantom_recovery.recover(limit=10)

    assert result["infrastructure_holds"] == 1
    assert result["recovered"] == 0
    database.update.assert_not_called()
