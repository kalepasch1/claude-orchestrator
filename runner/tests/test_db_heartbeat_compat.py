"""Heartbeat rolling-schema compatibility keeps executor identity when possible."""
import os
from unittest.mock import patch

import db
import host_update_visibility
import runtime_contract


def test_schema_lag_preserves_runtime_identity():
    """A missing commits_behind column must not erase a valid code-SHA proof."""
    attempts = []

    def reject_visibility_only(table, row, upsert=False):
        if table == "runner_heartbeats":
            attempts.append(dict(row))
            if "commits_behind" in row:
                raise Exception("column runner_heartbeats.commits_behind does not exist")
        return [row]

    proof = {
        "code_sha": "4716945bbc219f4c7132c13a8071ae1529b476c2",
        "contract_hash": "contract-hash",
        "contract_version": "executor-contract-v1",
    }
    with patch.object(db.db, "insert", side_effect=reject_visibility_only), \
         patch.object(db, "_prune_stale_heartbeats"), \
         patch.object(runtime_contract, "check", return_value=proof), \
         patch.object(host_update_visibility, "heartbeat_fields",
                      return_value={"commits_behind": 0}), \
         patch.dict(os.environ, {"ORCH_LOGICAL_RUNNERS": "false"}):
        db.heartbeat("runner-42", "test-host.local", 0)

    assert len(attempts) == 2
    assert "commits_behind" in attempts[0]
    assert "commits_behind" not in attempts[1]
    assert attempts[1]["code_sha"] == proof["code_sha"]
    assert attempts[1]["contract_hash"] == proof["contract_hash"]
