import os
import subprocess

import blocker_portfolio
import minimal_commit
import patch_tournament
import swarm_executor
import parallel_dispatch
import release_manifest
import release_attribution
import release_train
import route_evidence
import selective_qa
import merge_train
import queue_velocity
import db


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def init_repo(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    git(repo, "init"); git(repo, "config", "user.email", "test@example.com"); git(repo, "config", "user.name", "Test")
    return repo


def test_terminal_task_rows_collapses_retries_and_keeps_terminal_evidence():
    rows = [
        {"id": 1, "task_id": "t", "model": "ollama:qwen", "usd": 1, "wall_ms": 10, "created_at": "1"},
        {"id": 2, "task_id": "t", "model": "ollama:qwen", "usd": 2, "wall_ms": 20,
         "tests_passed": True, "integrated": True, "deployed": True, "created_at": "2"},
    ]
    result = route_evidence.terminal_task_rows(rows)
    assert len(result) == 1
    assert result[0]["deployed"] is True
    assert result[0]["usd"] == 3
    assert result[0]["_trial_rows"] == 2


def test_release_manifest_is_content_addressed_and_detects_lock_drift(tmp_path, monkeypatch):
    repo = init_repo(tmp_path)
    (repo / "package-lock.json").write_text("one")
    (repo / "app.js").write_text("one")
    git(repo, "add", "."); git(repo, "commit", "-m", "base"); base = git(repo, "rev-parse", "HEAD")
    (repo / "app.js").write_text("two")
    git(repo, "add", "."); git(repo, "commit", "-m", "change"); candidate = git(repo, "rev-parse", "HEAD")
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    first = release_manifest.create("app", str(repo), base, candidate, test_cmd="npm test")
    second = release_manifest.create("app", str(repo), base, candidate, test_cmd="npm test")
    assert first["id"] == second["id"]
    assert release_manifest.validate(str(repo), first)[0]
    drifted = dict(first); drifted["dependency_fingerprint"] = "bad"
    assert release_manifest.validate(str(repo), drifted) == (False, "dependency lock fingerprint changed")


def test_manifest_discovers_exact_task_artifacts_and_drives_attribution(tmp_path, monkeypatch):
    repo = init_repo(tmp_path)
    (repo / "app.py").write_text("one")
    git(repo, "add", "."); git(repo, "commit", "-m", "base"); base = git(repo, "rev-parse", "HEAD")
    (repo / "app.py").write_text("two")
    git(repo, "add", "."); git(repo, "commit", "-m", "opaque change"); candidate = git(repo, "rev-parse", "HEAD")
    class FakeDB:
        def select(self, table, query):
            if table == "tasks":
                return [{"id": "t1", "slug": "task-one", "state": "MERGED",
                         "artifact_commit": candidate, "model": "xai:grok"}]
            if table == "outcomes":
                return [{"id": "o1", "task_id": "t1", "slug": "task-one",
                         "model": "xai:grok", "project": "app", "integrated": True}]
            return []
        def update(self, *args):
            return None
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    tasks = release_manifest.discover_tasks(FakeDB(), "p1", str(repo), base, candidate)
    assert [task["id"] for task in tasks] == ["t1"]
    release_manifest.create("app", str(repo), base, candidate, tasks=tasks)
    result = release_attribution.attribute_release(
        "app", str(repo), {"id": "r1", "from_sha": base, "to_sha": candidate}, FakeDB())
    assert result["attributed"] == 1
    assert release_attribution.apply([{"id": "o1", "project": "app", "slug": "task-one"}])[0]["deployed"]


def test_exact_attribution_clears_broad_window_false_positive(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    row = {"id": "none", "project": "app", "slug": "unshipped", "deployed": True,
           "deploy_status": "success", "deployment_evidence": "project-release-window"}
    result = release_attribution.apply([row], authoritative=True)[0]
    assert result["deployed"] is False
    assert result["deployment_evidence"] == "no-exact-release-link"


def test_queue_depth_uses_exact_count(monkeypatch):
    monkeypatch.setattr(queue_velocity.db, "count", lambda *_args, **_kwargs: 2595)
    assert queue_velocity._queue_depth() == 2595


def test_selective_qa_maps_imported_source_to_one_test(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "src").mkdir(); (repo / "tests").mkdir()
    (repo / "src" / "math.ts").write_text("export const n = 1")
    (repo / "tests" / "math.spec.ts").write_text("import '../src/math'")
    (repo / "tests" / "other.spec.ts").write_text("test('x',()=>{})")
    git(repo, "add", "."); git(repo, "commit", "-m", "base"); base = git(repo, "rev-parse", "HEAD")
    (repo / "src" / "math.ts").write_text("export const n = 2")
    git(repo, "add", "."); git(repo, "commit", "-m", "change"); candidate = git(repo, "rev-parse", "HEAD")
    plan = selective_qa.plan(str(repo), base, candidate, "npm test")
    assert plan["mode"] == "selective"
    assert plan["tests"] == ["tests/math.spec.ts"]
    assert "other.spec.ts" not in plan["command"]


def test_blocker_portfolio_promotes_task_that_unblocks_chain():
    tasks = [
        {"id": "feature", "slug": "new-feature", "deps": [], "created_at": "2026-01-01"},
        {"id": "fix", "slug": "qafix-app-abcdef123456", "deps": [], "created_at": "2026-07-01"},
        {"id": "child", "slug": "ship", "deps": ["qafix-app-abcdef123456"], "created_at": "2026-07-02"},
    ]
    assert blocker_portfolio.rank(tasks)[0]["id"] == "fix"


def test_patch_tournament_blinds_identity_and_prefers_valid_deployed_value():
    candidates = [
        {"provider": "xai", "model": "grok-4.3", "patch": "diff --git a/a b/a\n", "applies": True,
         "tests_passed": True, "build_passed": True},
        {"provider": "claude", "model": "claude", "patch": "not a patch", "applies": False},
    ]
    result = patch_tournament.choose(candidates, {"xai": {"deployed": 4, "n": 8}})
    assert result["winner"]["anonymous_id"] == patch_tournament.anonymous_id(candidates[0]["patch"])
    assert "provider" not in result["winner"]
    assert set(result["ranking"][0]) == {"anonymous_id", "score"}
    empty = patch_tournament.choose([{"provider": "xai", "model": "grok", "patch": ""}])
    assert empty["winner"] is None
    assert set(empty["ranking"][0]) == {"anonymous_id", "score"}


def test_minimal_commit_extracts_only_artifact_files_onto_fresh_base(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "a.txt").write_text("base\n"); (repo / "noise.txt").write_text("base\n")
    git(repo, "add", "."); git(repo, "commit", "-m", "base"); base = git(repo, "rev-parse", "HEAD")
    base_branch = git(repo, "branch", "--show-current")
    git(repo, "switch", "-c", "agent/task")
    (repo / "a.txt").write_text("task\n"); git(repo, "add", "a.txt"); git(repo, "commit", "-m", "task")
    artifact = git(repo, "rev-parse", "HEAD")
    (repo / "noise.txt").write_text("noise\n"); git(repo, "add", "noise.txt"); git(repo, "commit", "-m", "noise")
    git(repo, "switch", base_branch)
    result = minimal_commit.extract(str(repo), "agent/task", base,
                                    {"slug": "task", "artifact_commit": artifact})
    assert result["ok"], result
    assert result["files"] == ["a.txt"]
    assert git(repo, "show", "agent/task:a.txt") == "task"
    assert git(repo, "show", "agent/task:noise.txt") == "base"


def test_accelerators_are_wired_into_delivery_paths():
    release_source = open(release_train.__file__, encoding="utf-8").read()
    dispatch_source = open(parallel_dispatch.__file__, encoding="utf-8").read()
    merge_source = open(merge_train.__file__, encoding="utf-8").read()
    db_source = open(db.__file__, encoding="utf-8").read()
    assert "release_manifest.create" in release_source
    assert "release_manifest.discover_tasks" in release_source
    assert "selective_qa.plan" in release_source
    assert "patch_tournament.run_live" in dispatch_source
    assert "minimal_commit.extract" in merge_source
    assert "blocker_portfolio.scores" in db_source
    assert "_load_env()" in open(swarm_executor.__file__, encoding="utf-8").read()
