import json
import datetime
from unittest.mock import patch

import failure_compiler
import proof_graph
import release_attribution
import release_train
import route_counterfactual
import router_stats


def test_failure_signature_compiles_repeated_paths_and_numbers_together():
    left = failure_compiler.signature("qa", "/tmp/a/foo.ts:91 TypeError item 123")
    right = failure_compiler.signature("qa", "/private/b/foo.ts:44 TypeError item 987")
    assert left == right


def test_partial_release_flushes_when_cadence_is_due():
    assert release_train._release_decision(3, False, minimum=10) == "hold"
    assert release_train._release_decision(3, True, minimum=10) == "release"
    assert release_train._release_decision(100, False, minimum=10) == "release"


def test_release_train_does_not_duplicate_done_branch_ingestion(monkeypatch):
    monkeypatch.delenv("ORCH_RELEASE_INGEST_DONE", raising=False)
    assert release_train._candidate_state_filter() is None
    monkeypatch.setenv("ORCH_RELEASE_INGEST_DONE", "true")
    assert release_train._candidate_state_filter() == "in.(DONE,MERGED)"


def test_release_fix_holds_are_gate_specific_and_expire(monkeypatch):
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = [
        {"slug": "qafix-app-current", "state": "QUEUED", "note": "auto-queued by release_train",
         "updated_at": now.isoformat()},
        {"slug": "qafix-app-running", "state": "RUNNING", "note": "auto-queued by release_train",
         "updated_at": now.isoformat()},
        {"slug": "copyfix-app-stale", "state": "QUEUED", "note": "auto-queued by release_train",
         "updated_at": (now - datetime.timedelta(hours=4)).isoformat()},
    ]
    monkeypatch.setattr(release_train.db, "select", lambda *a, **k: rows)
    monkeypatch.setenv("ORCH_RELEASE_FIX_HOLD_MIN", "180")
    assert [x["slug"] for x in release_train._open_release_fix_tasks({"id": "p"}, "qa")] == ["qafix-app-running"]
    assert release_train._open_release_fix_tasks({"id": "p"}, "copy") == []


def test_exact_release_attribution_uses_git_range_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setattr(release_attribution, "_messages", lambda *a: "train: agent/fix-auth\n")

    class DB:
        def select(self, table, params):
            return [{"id": "o1", "task_id": "t1", "slug": "fix-auth", "model": "ollama",
                     "project": "app", "integrated": True}]

    result = release_attribution.attribute_release("app", "/repo", {
        "id": "r1", "from_sha": "a", "to_sha": "b"}, DB())
    assert result["attributed"] == 1
    marked = release_attribution.apply([{"id": "o1", "project": "app", "slug": "fix-auth"}])
    assert marked[0]["deployed"] is True
    assert marked[0]["deployment_evidence"] == "git-release-range"


def test_release_messages_returns_git_range_output(monkeypatch):
    monkeypatch.setattr(release_attribution.subprocess, "check_output",
                        lambda *args, **kwargs: "ABC123\nFix Auth\n")
    assert release_attribution._messages("/repo", "a", "b") == "abc123\nfix auth\n"


def test_router_stats_consumes_exact_release_attribution():
    source = open(router_stats.__file__, encoding="utf-8").read()
    assert "rows = release_attribution.apply(rows, authoritative=True)" in source


def test_release_attribution_uses_merged_task_artifact_and_repairs_integrated(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setattr(release_attribution, "_messages", lambda *a: "release merge\n")
    monkeypatch.setattr(release_attribution, "_commit_in_range", lambda repo, commit, before, after: commit == "abc123")

    class DB:
        def __init__(self):
            self.updated = []

        def select(self, table, params):
            if table == "outcomes":
                return [{"id": "o1", "task_id": "t1", "slug": "fix-auth", "model": "xai",
                         "project": "app", "integrated": False}]
            return [{"id": "t1", "slug": "fix-auth", "state": "MERGED", "artifact_commit": "abc123"}]

        def update(self, table, where, values):
            self.updated.append((table, where, values))

    database = DB()
    result = release_attribution.attribute_release("app", "/repo", {
        "id": "r1", "from_sha": "a", "to_sha": "b"}, database)
    assert result["attributed"] == 1
    assert database.updated == [("outcomes", {"id": "o1"}, {"integrated": True})]


def test_content_addressed_verification_proof_reuses_exact_commit(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "package-lock.json").write_text("lock")
    proof_graph.record_verification(str(repo), "abc", "npm test", "qa", True)
    assert proof_graph.reusable_verification(str(repo), "abc", "npm test", "qa")
    assert not proof_graph.reusable_verification(str(repo), "def", "npm test", "qa")


def test_counterfactual_replay_evaluates_fifty_policies_without_calls():
    rows = [{"model": "deepseek-v4-flash", "integrated": True, "deployed": i < 3,
             "tests_passed": True, "wall_ms": 1000, "usd": 0.001} for i in range(20)]
    result = route_counterfactual.evaluate(rows, variants=50)
    assert result["trace_rows"] == 20
    assert len(result["variants"]) == 50
    assert result["experimental_multiplier"] == 50
