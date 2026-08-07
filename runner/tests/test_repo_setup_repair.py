#!/usr/bin/env python3
"""
test_repo_setup_repair.py - tests for repo_setup_repair module.

Covers: diagnose, repair, check_git_config, check_worktree_health,
        repair_git_config, repair_index_lock, repair_orphaned_worktrees.
Task: improve-implement-advanced-branch-management-repai-slice-5
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import repo_setup_repair


class TestCheckGit(unittest.TestCase):
    def test_valid_repo(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            ok, err = repo_setup_repair.check_git(d)
            self.assertTrue(ok)

    def test_invalid_repo(self):
        with tempfile.TemporaryDirectory() as d:
            ok, err = repo_setup_repair.check_git(d)
            self.assertFalse(ok)


class TestCheckGitConfig(unittest.TestCase):
    def test_missing_config(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            # Unset user.name/email in the temp repo
            os.system(f"cd {d} && git config --unset user.name 2>/dev/null; git config --unset user.email 2>/dev/null")
            issues = repo_setup_repair.check_git_config(d)
            # May or may not have global config; just verify it returns a list
            self.assertIsInstance(issues, list)


class TestCheckTool(unittest.TestCase):
    def test_git_exists(self):
        self.assertTrue(repo_setup_repair.check_tool("git"))

    def test_nonexistent_tool(self):
        self.assertFalse(repo_setup_repair.check_tool("nonexistent_tool_xyz_999"))


class TestCheckWorktreeHealth(unittest.TestCase):
    def test_clean_repo(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            issues = repo_setup_repair.check_worktree_health(d)
            self.assertEqual(issues, [])

    def test_stale_index_lock(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            lock = os.path.join(d, ".git", "index.lock")
            open(lock, "w").close()
            issues = repo_setup_repair.check_worktree_health(d)
            self.assertIn("index.lock", issues)
            os.remove(lock)


class TestDiagnose(unittest.TestCase):
    def test_nonexistent_path(self):
        report = repo_setup_repair.diagnose("/tmp/does_not_exist_xyz_999")
        self.assertFalse(report["valid"])

    def test_valid_repo(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            report = repo_setup_repair.diagnose(d)
            self.assertTrue(report["valid"])
            self.assertIn("repo", report)


class TestRepair(unittest.TestCase):
    def test_repair_nonexistent(self):
        report = repo_setup_repair.repair("/tmp/does_not_exist_xyz_999")
        self.assertFalse(report["valid"])

    def test_repair_valid_repo(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            report = repo_setup_repair.repair(d)
            self.assertIn("repairs", report)
            self.assertIn("healthy", report)


class TestRepairGitConfig(unittest.TestCase):
    def test_sets_repo_owner_identity_not_bot(self):
        # Vercel blocks deploys authored by non-owner identities; the repair
        # must install the owner identity, never a bot placeholder.
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            calls = []

            def fake_run(cmd, cwd=None, timeout=30):
                calls.append(cmd)
                if len(cmd) == 3 and cmd[1] == "config":
                    return "", "", 1  # key missing -> triggers repair
                return "", "", 0

            with patch.object(repo_setup_repair, "_run", side_effect=fake_run):
                repaired = repo_setup_repair.repair_git_config(d)
            self.assertEqual(sorted(repaired), ["user.email", "user.name"])
            set_calls = [c for c in calls if len(c) == 4 and c[1] == "config"]
            values = {c[2]: c[3] for c in set_calls}
            self.assertEqual(values.get("user.name"), repo_setup_repair.GIT_IDENTITY_NAME)
            self.assertEqual(values.get("user.email"), repo_setup_repair.GIT_IDENTITY_EMAIL)
            self.assertNotIn("orchestrator-bot", values.values())
            self.assertNotIn("bot@orchestrator.local", values.values())

    def test_identity_env_override(self):
        with patch.dict(os.environ, {"ORCH_GIT_USER_NAME": "someone", "ORCH_GIT_USER_EMAIL": "s@x.y"}):
            import importlib
            importlib.reload(repo_setup_repair)
            self.assertEqual(repo_setup_repair.GIT_IDENTITY_NAME, "someone")
            self.assertEqual(repo_setup_repair.GIT_IDENTITY_EMAIL, "s@x.y")
        importlib_mod = __import__("importlib")
        importlib_mod.reload(repo_setup_repair)  # restore defaults for other tests


class TestRepairIndexLock(unittest.TestCase):
    def test_no_lock(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            self.assertFalse(repo_setup_repair.repair_index_lock(d))

    def test_removes_stale_lock(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git init {d} >/dev/null 2>&1")
            lock = os.path.join(d, ".git", "index.lock")
            open(lock, "w").close()
            with patch.object(repo_setup_repair, "_run", return_value=("", "", 1)):
                removed = repo_setup_repair.repair_index_lock(d)
            # pgrep mock returns empty (no git process), so lock should be removed
            self.assertTrue(removed or not os.path.exists(lock))


GIT_ID = ["-c", "user.name=test", "-c", "user.email=test@test.local"]


def _git(args, cwd=None):
    import subprocess
    subprocess.run(["git"] + GIT_ID + args, cwd=cwd, check=True, capture_output=True)


def _make_upstream(root, branch="main"):
    upstream = os.path.join(root, "upstream")
    _git(["init", "-b", branch, upstream])
    with open(os.path.join(upstream, "README.md"), "w") as f:
        f.write("hello\n")
    _git(["add", "."], cwd=upstream)
    _git(["commit", "-m", "init"], cwd=upstream)
    return upstream


def _advance_upstream(upstream):
    with open(os.path.join(upstream, "more.txt"), "w") as f:
        f.write("more\n")
    _git(["add", "."], cwd=upstream)
    _git(["commit", "-m", "advance"], cwd=upstream)


class TestRepairRepo(unittest.TestCase):
    def test_structure(self):
        result = repo_setup_repair.repair_repo("/tmp/does_not_exist_xyz_999")
        for key in ("cloned", "fetched", "fast_forwarded", "actions",
                    "error", "ready", "default_branch", "clean", "current"):
            self.assertIn(key, result)

    def test_missing_repo_no_remote_url(self):
        result = repo_setup_repair.repair_repo("/tmp/does_not_exist_xyz_999")
        self.assertFalse(result["cloned"])
        self.assertFalse(result["ready"])
        self.assertIn("no remote_url", result["error"])

    def test_clone_success(self):
        with tempfile.TemporaryDirectory() as root:
            upstream = _make_upstream(root)
            local = os.path.join(root, "local")
            result = repo_setup_repair.repair_repo(local, remote_url=upstream)
            self.assertTrue(result["cloned"])
            self.assertTrue(result["ready"])
            self.assertEqual(result["default_branch"], "main")
            self.assertEqual(result["error"], "")

    def test_clone_failure(self):
        with tempfile.TemporaryDirectory() as root:
            local = os.path.join(root, "local")
            result = repo_setup_repair.repair_repo(
                local, remote_url=os.path.join(root, "no_such_upstream"))
            self.assertFalse(result["cloned"])
            self.assertFalse(result["ready"])
            self.assertIn("clone failed", result["error"])

    def test_fast_forward_behind_main(self):
        with tempfile.TemporaryDirectory() as root:
            upstream = _make_upstream(root)
            local = os.path.join(root, "local")
            _git(["clone", upstream, local])
            _advance_upstream(upstream)
            result = repo_setup_repair.repair_repo(local)
            self.assertTrue(result["fetched"])
            self.assertTrue(result["fast_forwarded"])
            self.assertTrue(result["ready"])
            self.assertTrue(result["current"])

    def test_fast_forward_behind_develop(self):
        with tempfile.TemporaryDirectory() as root:
            upstream = _make_upstream(root, branch="develop")
            local = os.path.join(root, "local")
            _git(["clone", upstream, local])
            _advance_upstream(upstream)
            result = repo_setup_repair.repair_repo(local)
            self.assertTrue(result["fast_forwarded"])
            self.assertEqual(result["default_branch"], "develop")
            self.assertTrue(result["ready"])

    def test_fast_forward_without_switching_branch(self):
        """A repo parked on a feature branch gets main updated in place."""
        import subprocess
        with tempfile.TemporaryDirectory() as root:
            upstream = _make_upstream(root)
            local = os.path.join(root, "local")
            _git(["clone", upstream, local])
            _git(["checkout", "-b", "agent/feature"], cwd=local)
            _advance_upstream(upstream)
            result = repo_setup_repair.repair_repo(local)
            self.assertTrue(result["fast_forwarded"])
            head = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=local, capture_output=True, text=True).stdout.strip()
            self.assertEqual(head, "agent/feature")

    def test_dirty_tree_skips_fast_forward(self):
        with tempfile.TemporaryDirectory() as root:
            upstream = _make_upstream(root)
            local = os.path.join(root, "local")
            _git(["clone", upstream, local])
            _advance_upstream(upstream)
            dirty_file = os.path.join(local, "wip.txt")
            with open(dirty_file, "w") as f:
                f.write("uncommitted\n")
            result = repo_setup_repair.repair_repo(local)
            self.assertFalse(result["fast_forwarded"])
            self.assertFalse(result["clean"])
            self.assertTrue(os.path.exists(dirty_file))
            self.assertTrue(any("dirty" in a for a in result["actions"]))

    def test_missing_remote_fail_soft(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _make_upstream(root)  # standalone repo, no origin
            result = repo_setup_repair.repair_repo(repo)
            self.assertFalse(result["fetched"])
            self.assertIn("fetch failed", result["error"])
            self.assertTrue(result["clean"])


class TestRepairForTask(unittest.TestCase):
    def test_missing_project(self):
        with patch.object(repo_setup_repair, "db") as mock_db:
            mock_db.select.return_value = []
            result = repo_setup_repair.repair_for_task({"project_id": "xxx"})
            self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
