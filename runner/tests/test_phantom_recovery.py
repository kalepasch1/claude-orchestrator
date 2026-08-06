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
    assert values["submitted_by"] == "legacy-dropbox-owner"
    assert values["priority"] == 10


def test_no_phantoms_is_idempotent():
    database = MagicMock()
    database.select.return_value = []

    with patch.object(phantom_recovery, "db", database):
        result = phantom_recovery.recover(limit=10)

    assert result == {"scanned": 0, "recovered": 0, "slugs": []}
    database.update.assert_not_called()
