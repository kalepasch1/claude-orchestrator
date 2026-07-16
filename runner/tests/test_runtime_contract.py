import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import runtime_contract


def test_contract_accepts_current_worktree_keyword_api():
    proof = runtime_contract.check()
    assert proof["ok"] is True
    assert proof["contract_hash"]


def test_contract_rejects_missing_keyword_api():
    class OldModule:
        @staticmethod
        def ensure_task_worktree(repo, slug, base, setup):
            return repo

    with patch.dict(sys.modules, {"worktree_isolation": OldModule()}):
        proof = runtime_contract.check()
    assert proof["ok"] is False
    assert "task_id" in proof["detail"]
