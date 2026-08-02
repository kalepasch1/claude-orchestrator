#!/usr/bin/env python3
"""
test_branch_bootstrap_injection.py - tests for branch_bootstrap_injection.

Covers: is_branch_pre_staged (true/false/fail-soft), bootstrap_slug,
make_bootstrap_task record shape, inject_bootstrap_if_needed ordering,
duplicate suppression, network/DB fail-soft, missing-repo-path handling,
and same-repo (machine-affinity) routing.
Task: improve-pre-decomposition-branch-availability-ve-slice-3
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import branch_bootstrap_injection as bbi


def _make_git_repo(tmpdir, branch="feature-x"):
    """Init a real repo with one commit and the named branch."""
    def run(*args):
        subprocess.run(["git"] + list(args), cwd=tmpdir, capture_output=True, check=True)
    run("init")
    run("config", "user.name", "kalepasch1")
    run("config", "user.email", "kalepasch@gmail.com")
    run("commit", "--allow-empty", "-m", "init")
    run("branch", branch)
    return tmpdir


class TestIsBranchPreStaged(unittest.TestCase):
    def test_none_repo_path(self):
        self.assertFalse(bbi.is_branch_pre_staged(None, "main"))

    def test_empty_repo_path(self):
        self.assertFalse(bbi.is_branch_pre_staged("", "main"))

    def test_nonexistent_repo_path(self):
        self.assertFalse(bbi.is_branch_pre_staged("/nonexistent/path/xyz", "main"))

    def test_none_branch(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(bbi.is_branch_pre_staged(d, None))

    def test_non_repo_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(bbi.is_branch_pre_staged(d, "main"))

    def test_local_branch_exists(self):
        with tempfile.TemporaryDirectory() as d:
            _make_git_repo(d, "feature-x")
            self.assertTrue(bbi.is_branch_pre_staged(d, "feature-x"))

    def test_local_branch_missing(self):
        with tempfile.TemporaryDirectory() as d:
            _make_git_repo(d, "feature-x")
            self.assertFalse(bbi.is_branch_pre_staged(d, "no-such-branch"))

    def test_remote_tracking_ref_counts(self):
        def fake_git(repo, args, timeout=15):
            if args[-1] == "refs/remotes/origin/feature-y":
                return 0, "abc123"
            return 1, ""
        with tempfile.TemporaryDirectory() as d:
            with patch.object(bbi, "_run_git", side_effect=fake_git):
                self.assertTrue(bbi.is_branch_pre_staged(d, "feature-y"))

    def test_worktree_holding_branch_counts(self):
        def fake_git(repo, args, timeout=15):
            if args[0] == "worktree":
                return 0, ("worktree /tmp/wt\nHEAD abc123\n"
                           "branch refs/heads/feature-z\n")
            return 1, ""
        with tempfile.TemporaryDirectory() as d:
            with patch.object(bbi, "_run_git", side_effect=fake_git):
                self.assertTrue(bbi.is_branch_pre_staged(d, "feature-z"))

    def test_git_error_fails_soft(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(bbi, "_run_git", side_effect=RuntimeError("boom")):
                self.assertFalse(bbi.is_branch_pre_staged(d, "main"))


class TestBootstrapSlug(unittest.TestCase):
    def test_deterministic_and_sanitized(self):
        self.assertEqual(bbi.bootstrap_slug("agent/My Task!"),
                         bbi.bootstrap_slug("agent/My Task!"))
        self.assertEqual(bbi.bootstrap_slug("agent/fix-thing"),
                         "branch-bootstrap-agent-fix-thing")

    def test_truncated_to_60(self):
        self.assertLessEqual(len(bbi.bootstrap_slug("x" * 200)), 60)

    def test_none_branch(self):
        self.assertEqual(bbi.bootstrap_slug(None), "branch-bootstrap-unknown")


class TestMakeBootstrapTask(unittest.TestCase):
    def _task(self, **kw):
        t = {"project_id": "p1", "slug": "real-task"}
        t.update(kw)
        return t

    def test_record_shape(self):
        rec = bbi.make_bootstrap_task(self._task(), "git@x:y.git", "main")
        self.assertEqual(rec["kind"], bbi.BOOTSTRAP_KIND)
        self.assertEqual(rec["state"], "QUEUED")
        self.assertEqual(rec["priority"], bbi.BOOTSTRAP_PRIORITY)
        self.assertEqual(rec["project_id"], "p1")
        self.assertEqual(rec["slug"], bbi.bootstrap_slug("main"))

    def test_parent_task_id_when_current_has_id(self):
        rec = bbi.make_bootstrap_task(self._task(id="t42"), "url", "main")
        self.assertEqual(rec["parent_task_id"], "t42")

    def test_no_parent_task_id_pre_insert(self):
        rec = bbi.make_bootstrap_task(self._task(), "url", "main")
        self.assertNotIn("parent_task_id", rec)

    def test_none_on_missing_branch(self):
        self.assertIsNone(bbi.make_bootstrap_task(self._task(), "url", None))

    def test_none_on_missing_project(self):
        self.assertIsNone(bbi.make_bootstrap_task({"slug": "x"}, "url", "main"))

    def test_none_on_none_task(self):
        self.assertIsNone(bbi.make_bootstrap_task(None, "url", "main"))

    def test_env_tuning_in_payload(self):
        with patch.dict(os.environ, {"ORCH_BOOTSTRAP_MAX_RETRIES": "7",
                                     "ORCH_BOOTSTRAP_TIMEOUT": "45"}):
            rec = bbi.make_bootstrap_task(self._task(), "url", "main")
        self.assertIn("7 times", rec["prompt"])
        self.assertIn("45s", rec["prompt"])

    def test_bad_env_values_fall_back(self):
        with patch.dict(os.environ, {"ORCH_BOOTSTRAP_MAX_RETRIES": "not-a-number"}):
            rec = bbi.make_bootstrap_task(self._task(), "url", "main")
        self.assertIn("3 times", rec["prompt"])

    def test_machine_recorded_in_note(self):
        rec = bbi.make_bootstrap_task(self._task(), "url", "main", machine_id="mac-2")
        self.assertIn("machine=mac-2", rec["note"])

    def test_fetch_and_clone_in_payload(self):
        rec = bbi.make_bootstrap_task(self._task(), "git@x:y.git", "dev")
        self.assertIn("git fetch origin dev:dev", rec["prompt"])
        self.assertIn("git clone git@x:y.git", rec["prompt"])
        self.assertIn("rebase", rec["prompt"])


class TestInjectBootstrapIfNeeded(unittest.TestCase):
    """Injection ordering, duplicate suppression, and fail-soft behavior."""

    def setUp(self):
        bbi.reset_stats()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repo = self.tmpdir.name
        self.project = {"id": "p1", "repo_path": self.repo, "default_base": "main"}
        self.row = {"project_id": "p1", "slug": "real-task",
                    "base_branch": "main", "deps": ["other-dep"]}

    def tearDown(self):
        self.tmpdir.cleanup()

    def _patch(self, staged=False, existing=None, insert_ok=True):
        patches = [
            patch.object(bbi.db, "localize_repo_path", side_effect=lambda p: p),
            patch.object(bbi, "is_branch_pre_staged", return_value=staged),
            patch.object(bbi.db, "select",
                         return_value=existing if existing is not None else []),
            patch.object(bbi.db, "insert",
                         return_value=[{"id": "b1"}] if insert_ok else None),
        ]
        return patches

    def _run(self, *patches):
        started = [p.start() for p in patches]
        try:
            return bbi.inject_bootstrap_if_needed(self.row, self.project), started
        finally:
            for p in patches:
                p.stop()

    def test_disabled_via_env(self):
        with patch.dict(os.environ, {"ORCH_BOOTSTRAP_INJECTION_ENABLED": "false"}):
            res = bbi.inject_bootstrap_if_needed(self.row, self.project)
        self.assertFalse(res["injected"])
        self.assertEqual(res["reason"], "disabled")

    def test_bad_input_task_row(self):
        res = bbi.inject_bootstrap_if_needed(None, self.project)
        self.assertFalse(res["injected"])
        self.assertEqual(res["reason"], "bad-input")

    def test_missing_repo_path(self):
        res = bbi.inject_bootstrap_if_needed(self.row, {"id": "p1", "repo_path": ""})
        self.assertFalse(res["injected"])
        self.assertEqual(res["reason"], "missing-repo-path")
        self.assertEqual(self.row["deps"], ["other-dep"])  # untouched

    def test_localize_error_fails_soft(self):
        with patch.object(bbi.db, "localize_repo_path", side_effect=RuntimeError):
            res = bbi.inject_bootstrap_if_needed(self.row, self.project)
        self.assertFalse(res["injected"])
        self.assertEqual(res["reason"], "missing-repo-path")

    def test_pre_staged_skips_injection(self):
        res, _ = self._run(*self._patch(staged=True))
        self.assertFalse(res["injected"])
        self.assertEqual(res["reason"], "pre-staged")
        self.assertEqual(self.row["deps"], ["other-dep"])
        self.assertEqual(bbi.stats()["skipped_pre_staged"], 1)

    def test_fresh_injection_inserts_and_orders_ahead(self):
        res, mocks = self._run(*self._patch(staged=False))
        self.assertTrue(res["injected"])
        insert_mock = mocks[3]
        insert_mock.assert_called_once()
        table, record = insert_mock.call_args[0]
        self.assertEqual(table, "tasks")
        self.assertEqual(record["kind"], bbi.BOOTSTRAP_KIND)
        self.assertEqual(record["priority"], bbi.BOOTSTRAP_PRIORITY)
        # ordering: real task now depends on the bootstrap slug
        self.assertIn(record["slug"], self.row["deps"])
        self.assertIn("other-dep", self.row["deps"])
        self.assertEqual(bbi.stats()["injected"], 1)

    def test_same_machine_routing_via_project(self):
        # host affinity keys on project repo — the bootstrap task must share it
        res, mocks = self._run(*self._patch(staged=False))
        record = mocks[3].call_args[0][1]
        self.assertEqual(record["project_id"], self.row["project_id"])

    def test_duplicate_suppression(self):
        res, mocks = self._run(*self._patch(
            staged=False, existing=[{"id": "b0", "state": "QUEUED"}]))
        self.assertFalse(res["injected"])
        self.assertEqual(res["reason"], "duplicate")
        mocks[3].assert_not_called()  # no second insert
        # still ordered behind the existing bootstrap
        self.assertIn(res["bootstrap_slug"], self.row["deps"])
        self.assertEqual(bbi.stats()["skipped_duplicate"], 1)

    def test_db_select_failure_no_injection(self):
        patches = self._patch(staged=False)
        patches[2] = patch.object(bbi.db, "select", return_value=None)
        res, mocks = self._run(*patches)
        self.assertFalse(res["injected"])
        self.assertEqual(res["reason"], "db-error")
        mocks[3].assert_not_called()
        self.assertEqual(self.row["deps"], ["other-dep"])

    def test_db_select_exception_no_injection(self):
        patches = self._patch(staged=False)
        patches[2] = patch.object(bbi.db, "select", side_effect=RuntimeError("net"))
        res, _ = self._run(*patches)
        self.assertEqual(res["reason"], "db-error")

    def test_insert_failure_leaves_deps_untouched(self):
        res, _ = self._run(*self._patch(staged=False, insert_ok=False))
        self.assertFalse(res["injected"])
        self.assertEqual(res["reason"], "insert-failed")
        self.assertEqual(self.row["deps"], ["other-dep"])

    def test_insert_exception_fails_soft(self):
        patches = self._patch(staged=False)
        patches[3] = patch.object(bbi.db, "insert", side_effect=RuntimeError("net down"))
        res, _ = self._run(*patches)
        self.assertFalse(res["injected"])
        self.assertEqual(res["reason"], "insert-failed")
        self.assertEqual(self.row["deps"], ["other-dep"])

    def test_no_duplicate_dep_append(self):
        self.row["deps"] = ["other-dep", bbi.bootstrap_slug("main")]
        res, _ = self._run(*self._patch(
            staged=False, existing=[{"id": "b0", "state": "QUEUED"}]))
        self.assertEqual(
            self.row["deps"].count(bbi.bootstrap_slug("main")), 1)

    def test_base_branch_falls_back_to_project_default(self):
        self.row.pop("base_branch")
        res, mocks = self._run(*self._patch(staged=False))
        record = mocks[3].call_args[0][1]
        self.assertEqual(record["slug"], bbi.bootstrap_slug("main"))

    def test_never_raises(self):
        with patch.object(bbi, "_enabled", side_effect=RuntimeError("boom")):
            res = bbi.inject_bootstrap_if_needed(self.row, self.project)
        self.assertFalse(res["injected"])
        self.assertTrue(res["reason"].startswith("error:"))


class TestStats(unittest.TestCase):
    def test_stats_copy_and_reset(self):
        bbi.reset_stats()
        s = bbi.stats()
        self.assertEqual(s["injected"], 0)
        s["injected"] = 99  # mutating the copy must not touch the module
        self.assertEqual(bbi.stats()["injected"], 0)


if __name__ == "__main__":
    unittest.main()
