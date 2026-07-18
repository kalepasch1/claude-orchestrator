#!/usr/bin/env python3
"""Tests for sweep_reconciler — synthetic journal + fake db."""
import json, os, sys, tempfile, pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.dirname(HERE)
sys.path.insert(0, RUNNER)

import sweep_reconciler as sr


# ── Fake DB module ────────────────────────────────────────────────────────────

class FakeDB:
    """Minimal fake that records all calls for assertions."""

    def __init__(self, tasks=None):
        self.tasks = {t["slug"]: t for t in (tasks or [])}
        self.patches = []  # (table, params, body)
        self.inserts = []  # (table, row)

    def select(self, table, params=None):
        if table == "tasks":
            slug_filter = (params or {}).get("slug", "")
            if slug_filter.startswith("eq."):
                slug = slug_filter[3:]
                t = self.tasks.get(slug)
                return [t] if t else []
        return []

    def _req(self, method, path, body=None, headers=None, params=None):
        if method == "PATCH":
            self.patches.append((path, params, body))
            # Apply state change to in-memory tasks for re-reads
            if "/tasks" in path and params:
                id_filter = params.get("id", "")
                if id_filter.startswith("eq."):
                    tid = id_filter[3:]
                    for t in self.tasks.values():
                        if t["id"] == tid and body:
                            t.update(body)
        return None

    def insert(self, table, row, upsert=False):
        self.inserts.append((table, row))
        return [row]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_journal(tmpdir, entries):
    """Write a synthetic journal and point sweep_reconciler at it."""
    jpath = os.path.join(tmpdir, "git_deploy_sweep.jsonl")
    with open(jpath, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return jpath


def _sample_task(slug, state="DONE", task_id=None, project_id="proj-1"):
    return {
        "id": task_id or f"id-{slug}",
        "slug": slug,
        "state": state,
        "project_id": project_id,
        "note": "",
    }


@pytest.fixture(autouse=True)
def _patch_paths(tmp_path, monkeypatch):
    """Redirect journal and offset paths to tmp for every test."""
    monkeypatch.setattr(sr, "JOURNAL", str(tmp_path / "git_deploy_sweep.jsonl"))
    monkeypatch.setattr(sr, "OFFSET_FILE", str(tmp_path / "sweep_reconciler_offset"))
    monkeypatch.setattr(sr, "RUNTIME", str(tmp_path))


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSlugFromBranch:
    def test_agent_prefix(self):
        assert sr._slug_from_branch("agent/my-task") == "my-task"

    def test_origin_agent_prefix(self):
        assert sr._slug_from_branch("origin/agent/fix-login") == "fix-login"

    def test_no_match(self):
        assert sr._slug_from_branch("master") is None

    def test_none(self):
        assert sr._slug_from_branch(None) is None


class TestReconcileDeployed:
    def test_deployed_marks_merged(self, tmp_path):
        entries = [
            {"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
             "branch": "agent/fix-auth", "action": "DEPLOYED", "detail": "abc123def456"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB(tasks=[_sample_task("fix-auth", state="DONE")])
        stats = sr.reconcile(db_module=db)
        assert stats["deployed"] == 1
        assert stats["errors"] == 0
        # Task patched to MERGED
        task_patches = [p for p in db.patches if "/tasks" in p[0]]
        assert any(p[2].get("state") == "MERGED" for p in task_patches)
        assert any("offline-sweep deployed abc123def456" in (p[2].get("note") or "") for p in task_patches)
        # Outcome inserted
        outcome_inserts = [i for i in db.inserts if i[0] == "outcomes"]
        assert len(outcome_inserts) == 1
        assert outcome_inserts[0][1]["usd"] == 0
        assert outcome_inserts[0][1]["integrated"] is True

    def test_deployed_from_running(self, tmp_path):
        entries = [
            {"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
             "branch": "agent/run-task", "action": "DEPLOYED", "detail": "sha999"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB(tasks=[_sample_task("run-task", state="RUNNING")])
        stats = sr.reconcile(db_module=db)
        assert stats["deployed"] == 1

    def test_deployed_guards_state(self, tmp_path):
        """DEPLOYED should NOT transition a QUEUED or MERGED task."""
        entries = [
            {"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
             "branch": "agent/queued-task", "action": "DEPLOYED", "detail": "sha111"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB(tasks=[_sample_task("queued-task", state="QUEUED")])
        stats = sr.reconcile(db_module=db)
        assert stats["deployed"] == 1  # processed, but no patch applied
        task_patches = [p for p in db.patches if "/tasks" in p[0]]
        assert len(task_patches) == 0

    def test_deployed_unknown_slug(self, tmp_path):
        """DEPLOYED for a slug not in DB is a no-op (no error)."""
        entries = [
            {"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
             "branch": "agent/ghost-task", "action": "DEPLOYED", "detail": "sha222"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB(tasks=[])
        stats = sr.reconcile(db_module=db)
        assert stats["deployed"] == 1
        assert stats["errors"] == 0


class TestReconcileFailures:
    def test_gate_red_annotates(self, tmp_path):
        entries = [
            {"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
             "branch": "agent/fail-gate", "action": "GATE-RED", "detail": "tests failed"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB(tasks=[_sample_task("fail-gate", state="DONE")])
        stats = sr.reconcile(db_module=db)
        assert stats["annotated"] == 1
        task_patches = [p for p in db.patches if "/tasks" in p[0]]
        assert any("sweep:gate-red" in (p[2].get("note") or "") for p in task_patches)

    def test_conflict_annotates(self, tmp_path):
        entries = [
            {"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
             "branch": "agent/conflict-task", "action": "CONFLICT",
             "detail": "merge conflict in runner/db.py"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB(tasks=[_sample_task("conflict-task")])
        stats = sr.reconcile(db_module=db)
        assert stats["annotated"] == 1

    def test_push_fail_annotates(self, tmp_path):
        entries = [
            {"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
             "branch": "agent/push-fail-task", "action": "PUSH-FAIL", "detail": "remote rejected"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB(tasks=[_sample_task("push-fail-task")])
        stats = sr.reconcile(db_module=db)
        assert stats["annotated"] == 1


class TestIdempotency:
    def test_second_run_skips_processed(self, tmp_path):
        entries = [
            {"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
             "branch": "agent/task-a", "action": "DEPLOYED", "detail": "sha1"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB(tasks=[_sample_task("task-a")])

        stats1 = sr.reconcile(db_module=db)
        assert stats1["deployed"] == 1

        # Second run: no new entries
        db2 = FakeDB(tasks=[_sample_task("task-a", state="MERGED")])
        stats2 = sr.reconcile(db_module=db2)
        assert stats2["deployed"] == 0
        assert stats2["annotated"] == 0

    def test_appended_entries_processed(self, tmp_path):
        entries = [
            {"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
             "branch": "agent/task-b", "action": "DEPLOYED", "detail": "sha1"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB(tasks=[_sample_task("task-b")])
        sr.reconcile(db_module=db)

        # Append a new entry
        jpath = str(tmp_path / "git_deploy_sweep.jsonl")
        with open(jpath, "a") as f:
            f.write(json.dumps({"at": "2026-07-10T01:00:00Z", "repo": "beethoven",
                                "branch": "agent/task-c", "action": "DEPLOYED",
                                "detail": "sha2"}) + "\n")

        db2 = FakeDB(tasks=[_sample_task("task-c")])
        stats2 = sr.reconcile(db_module=db2)
        assert stats2["deployed"] == 1


class TestEdgeCases:
    def test_empty_journal(self, tmp_path):
        db = FakeDB()
        stats = sr.reconcile(db_module=db)
        assert stats == {"deployed": 0, "annotated": 0, "skipped": 0, "errors": 0}

    def test_missing_journal_file(self, tmp_path):
        db = FakeDB()
        stats = sr.reconcile(db_module=db)
        assert stats["errors"] == 0

    def test_non_agent_branch_skipped(self, tmp_path):
        entries = [
            {"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
             "branch": "master", "action": "DEPLOYED", "detail": "sha"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB()
        stats = sr.reconcile(db_module=db)
        assert stats["skipped"] == 1

    def test_malformed_json_line_skipped(self, tmp_path):
        jpath = str(tmp_path / "git_deploy_sweep.jsonl")
        with open(jpath, "w") as f:
            f.write("NOT VALID JSON\n")
            f.write(json.dumps({"at": "2026-07-10T00:00:00Z", "repo": "beethoven",
                                "branch": "agent/ok-task", "action": "DEPLOYED",
                                "detail": "sha"}) + "\n")
        db = FakeDB(tasks=[_sample_task("ok-task")])
        stats = sr.reconcile(db_module=db)
        assert stats["deployed"] == 1

    def test_mixed_actions(self, tmp_path):
        entries = [
            {"at": "t1", "repo": "r", "branch": "agent/a", "action": "DEPLOYED", "detail": "s1"},
            {"at": "t2", "repo": "r", "branch": "agent/b", "action": "GATE-RED", "detail": "fail"},
            {"at": "t3", "repo": "r", "branch": "agent/c", "action": "CONFLICT", "detail": "x"},
            {"at": "t4", "repo": "r", "branch": "agent/d", "action": "PUSH-FAIL", "detail": "y"},
            {"at": "t5", "repo": "r", "branch": "master", "action": "DEPLOYED", "detail": "z"},
        ]
        _make_journal(str(tmp_path), entries)
        db = FakeDB(tasks=[
            _sample_task("a"), _sample_task("b"),
            _sample_task("c"), _sample_task("d"),
        ])
        stats = sr.reconcile(db_module=db)
        assert stats["deployed"] == 1
        assert stats["annotated"] == 3
        assert stats["skipped"] == 1
