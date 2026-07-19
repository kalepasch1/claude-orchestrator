import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import production_push_guard


def test_only_production_branch_updates_are_guarded():
    sha = "a" * 40
    lines = [
        f"refs/heads/feature {sha} refs/heads/feature {'0' * 40}\n",
        f"refs/heads/main {sha} refs/heads/main {'b' * 40}\n",
        f"refs/heads/master {sha} refs/heads/master {'c' * 40}\n",
    ]
    updates = production_push_guard.guarded_updates(lines)
    assert [update[2] for update in updates] == ["refs/heads/main", "refs/heads/master"]


def test_branch_deletion_is_not_built():
    lines = [f"(delete) {'0' * 40} refs/heads/main {'a' * 40}\n"]
    assert production_push_guard.guarded_updates(lines) == []


def test_nested_deploy_root_skips_unrelated_changes():
    with tempfile.TemporaryDirectory() as repo:
        web = os.path.join(repo, "web")
        os.makedirs(web)
        with open(os.path.join(web, "vercel.json"), "w") as f:
            f.write("{}")
        with patch.object(production_push_guard.build_gate.dependency_prewarm, "package_roots", return_value=[web]):
            with patch.object(production_push_guard, "_git", return_value="runner/release_train.py"):
                assert production_push_guard.changes_affect_build(repo, "a" * 40, "b" * 40) is False
            with patch.object(production_push_guard, "_git", return_value="web/pages/index.vue"):
                assert production_push_guard.changes_affect_build(repo, "a" * 40, "b" * 40) is True


def test_unproved_production_commit_is_blocked():
    with tempfile.TemporaryDirectory() as repo:
        with patch.object(production_push_guard.build_gate, "detect_build_cmd", return_value="npm run build"):
            with patch.object(production_push_guard.proof_graph, "reusable_verification", return_value=None):
                ok, message = production_push_guard.verify(repo, "a" * 40)
    assert ok is False
    assert "No green release-train proof" in message
