import os, sys, unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import integration_sweeper


class TestIntegrationSweeper(unittest.TestCase):

    def test_done_branch_queues_canonical_train_card(self):
        fake = MagicMock()
        project = {"id": "p1", "name": "alpha", "repo_path": "/repo"}
        task = {"id": "t1", "slug": "feat-x", "project_id": "p1", "state": "DONE",
                "note": "verify pass", "kind": "build"}

        def select(table, params=None):
            if table == "projects":
                return [project]
            if table == "tasks":
                return [task]
            return []

        fake.select.side_effect = select
        with patch.object(integration_sweeper, "db", fake), \
             patch.object(integration_sweeper, "_branch_exists", return_value=True), \
             patch.object(integration_sweeper.merge_train, "ensure_integration_card", return_value=True) as ensure, \
             patch.object(integration_sweeper.merge_train, "train_run", return_value={"merged": 1}) as train:
            out = integration_sweeper.sweep(limit=10, run_train=True)

        self.assertEqual(out["queued"], 1)
        ensure.assert_called_once()
        args, kwargs = ensure.call_args
        self.assertEqual(args[:2], ("alpha", "feat-x"))
        self.assertEqual(kwargs["status"], "approved")
        train.assert_called_once()

    def test_missing_branch_queues_reuse_first_recovery_task(self):
        fake = MagicMock()
        project = {"id": "p1", "name": "alpha", "repo_path": "/repo", "default_base": "main"}
        task = {"id": "t1", "slug": "feat-x", "project_id": "p1", "state": "DONE",
                "note": "verify pass", "kind": "build", "prompt": "add webhook"}

        def select(table, params=None):
            if table == "projects":
                return [project]
            if table == "tasks":
                if (params or {}).get("slug", "").startswith("like.rework-"):
                    return []
                if (params or {}).get("slug") == "eq.recover-missing-branch-feat-x":
                    return []
                return [task]
            return []

        inserted = []
        fake.select.side_effect = select
        fake.insert.side_effect = lambda table, row, **kw: inserted.append((table, row))
        with patch.object(integration_sweeper, "db", fake), \
             patch.object(integration_sweeper, "_branch_exists", return_value=False), \
             patch.object(integration_sweeper, "_reuse_context", return_value="PATCH TEMPLATE demo"), \
             patch.object(integration_sweeper, "pressure", return_value={"projects": {}}):
            out = integration_sweeper.sweep(limit=10, run_train=True)

        self.assertEqual(out["missing_branch"], 1)
        self.assertEqual(out["recovery_queued"], 1)
        rows = [r for t, r in inserted if t == "tasks"]
        self.assertEqual(rows[0]["slug"], "recover-missing-branch-feat-x")
        self.assertIn("PATCH TEMPLATE demo", rows[0]["prompt"])
        self.assertEqual(rows[0]["force_coder"], "ollama")

    def test_recovery_slug_does_not_create_nested_recovery(self):
        fake = MagicMock()
        project = {"id": "p1", "name": "alpha", "repo_path": "/repo", "default_base": "main"}
        task = {"id": "t1", "slug": "recover-missing-branch-feat-x", "project_id": "p1",
                "state": "DONE", "note": "verify pass", "kind": "build", "prompt": "recover"}

        def select(table, params=None):
            if table == "projects":
                return [project]
            if table == "tasks":
                return [task]
            return []

        fake.select.side_effect = select
        with patch.object(integration_sweeper, "db", fake), \
             patch.object(integration_sweeper, "_branch_exists", return_value=False), \
             patch.object(integration_sweeper, "pressure", return_value={"projects": {}}):
            out = integration_sweeper.sweep(limit=10, run_train=True)

        self.assertEqual(out["recovery_queued"], 0)
        self.assertEqual(out["missing_branch"], 0)
        self.assertEqual(out["skipped"], 1)
        fake.insert.assert_not_called()

    def test_recovery_dedup_quarantines_duplicate_active_rows(self):
        fake = MagicMock()
        rows = [
            {"id": "keep", "slug": "recover-missing-branch-feat-x", "project_id": "p1",
             "state": "QUEUED", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "dup", "slug": "recover-missing-branch-recover-missing-branch-feat-x",
             "project_id": "p1", "state": "QUEUED", "created_at": "2026-01-02T00:00:00Z"},
        ]
        fake.select.return_value = rows

        with patch.object(integration_sweeper, "db", fake):
            out = integration_sweeper.recovery_dedup()

        self.assertEqual(out["duplicate_groups"], 1)
        self.assertEqual(out["quarantined"], 1)
        fake.update.assert_called_once()
        self.assertEqual(fake.update.call_args.args[1], {"id": "dup"})
        self.assertEqual(fake.update.call_args.args[2]["state"], "QUARANTINED")


class TestLocalBranchAudit(unittest.TestCase):
    """Tests for local_branch_audit() — read-only branch state inspection."""

    def _make_repo(self, tmp_path, branches=(), remote_branches=()):
        """Return (repo, subprocess_mock) with canned git output."""
        local_out = "\n".join(f"agent/{b}" for b in branches) + "\n"
        remote_out = "\n".join(f"origin/agent/{b}" for b in remote_branches) + "\n"
        def fake_run(cmd, **kw):
            m = MagicMock()
            m.returncode = 0
            if "--list" in cmd and "-r" not in cmd:
                m.stdout = local_out
            elif "-r" in cmd:
                m.stdout = remote_out
            elif "worktree" in cmd:
                m.stdout = ""
            elif "reflog" in cmd:
                m.stdout = ""
            else:
                m.stdout = ""
            return m
        return fake_run

    def test_classifies_local_branch(self):
        with patch("subprocess.run", self._make_repo("/repo", branches=["my-task"])), \
             patch("os.path.isdir", return_value=True):
            out = integration_sweeper.local_branch_audit("/repo", slugs=["my-task"])
        self.assertEqual(len(out["local"]), 1)
        self.assertEqual(out["local"][0]["slug"], "my-task")
        self.assertEqual(out["missing"], [])

    def test_classifies_missing_branch(self):
        with patch("subprocess.run", self._make_repo("/repo")), \
             patch("os.path.isdir", return_value=True):
            out = integration_sweeper.local_branch_audit("/repo", slugs=["absent-slug"])
        self.assertEqual(len(out["missing"]), 1)
        self.assertEqual(out["local"], [])

    def test_classifies_remote_only_branch(self):
        with patch("subprocess.run", self._make_repo("/repo", remote_branches=["remote-only"])), \
             patch("os.path.isdir", return_value=True):
            out = integration_sweeper.local_branch_audit("/repo", slugs=["remote-only"])
        self.assertEqual(len(out["remote_only"]), 1)
        self.assertEqual(out["local"], [])

    def test_fail_soft_on_empty_repo_path(self):
        fake_db = MagicMock()
        fake_db.select.return_value = []
        with patch.object(integration_sweeper, "db", fake_db):
            out = integration_sweeper.local_branch_audit("", slugs=["x"])
        self.assertIn("missing", out)
        self.assertEqual(out["missing"][0]["slug"], "x")

    def test_fail_soft_on_missing_repo_dir(self):
        fake_db = MagicMock()
        fake_db.select.return_value = []
        with patch.object(integration_sweeper, "db", fake_db):
            out = integration_sweeper.local_branch_audit("/no/such/path", slugs=["x"])
        self.assertIn("missing", out)

    def test_db_slug_fallback_when_no_slugs_provided(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [{"slug": "from-db"}]
        with patch.object(integration_sweeper, "db", fake_db):
            out = integration_sweeper.local_branch_audit("/no/such/path")
        self.assertEqual(len(out["missing"]), 1)
        self.assertEqual(out["missing"][0]["slug"], "from-db")

    def test_stale_worktree_detection(self):
        wt_porcelain = (
            "worktree /some/path\nHEAD abc123\nbranch refs/heads/agent/wt-slug\n\n"
        )
        def fake_run(cmd, **kw):
            m = MagicMock()
            m.returncode = 0
            if "worktree" in cmd:
                m.stdout = wt_porcelain
            else:
                m.stdout = ""
            return m
        fake_db = MagicMock()
        fake_db.select.return_value = []  # no RUNNING tasks
        with patch("subprocess.run", fake_run), \
             patch("os.path.isdir", return_value=True), \
             patch.object(integration_sweeper, "db", fake_db):
            out = integration_sweeper.local_branch_audit("/repo", slugs=["wt-slug"])
        self.assertEqual(len(out["stale_worktrees"]), 1)
        self.assertEqual(out["stale_worktrees"][0]["branch"], "agent/wt-slug")


if __name__ == "__main__":
    unittest.main()
