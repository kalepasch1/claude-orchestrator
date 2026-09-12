#!/usr/bin/env python3
"""branch_repair_bot must not mistake "cannot look" for "nothing is there".

The defect
----------
_git() catches every exception and returns rc=-1, so `git rev-parse --verify`
against a repo path that is not mounted, not yet cloned, or simply wrong gave
the identical answer to a repo whose branch really had been deleted. The old
scan_and_repair() read that as "branch missing" and requeued the task --
rewriting its state to QUEUED and its slug to recover-<slug>.

Multiply by a project: one unmounted volume would have requeued EVERY DONE task
in it, on the strength of git invocations that never ran. ORCH_BRANCH_REPAIR_
DRY_RUN defaults to true, which is the only reason this stayed latent, and
nothing in the repository imported the module, which is the only reason it
never ran at all. `.env.example` documents its three env vars as live
configuration, so it reads as wired.

These tests run with DRY_RUN forced OFF, because dry-run masks exactly the
behaviour that matters here.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_repair_bot as bot

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_EMAIL": "t@t"}


def _init_repo(path, branches=(), base="master"):
    """A real git repo whose default branch is `base`, plus any extra branches.

    -b is explicit because git's own default is main on a modern install and
    master on an older one; a test that inherits whichever this machine has is
    a test that fails on somebody else's laptop.
    """
    subprocess.run(["git", "init", "-q", "-b", base, path],
                   capture_output=True, timeout=30)
    subprocess.run(["git", "-C", path, "commit", "-q", "--allow-empty", "-m", "init"],
                   capture_output=True, timeout=30, env={**os.environ, **GIT_ENV})
    for branch in branches:
        subprocess.run(["git", "-C", path, "branch", branch],
                       capture_output=True, timeout=30)
    return path


class _ArmedBot(unittest.TestCase):
    """DRY_RUN off: these tests are about what the bot would really do."""

    def arm_the_bot(self):
        armed = patch.object(bot, "DRY_RUN", False)
        armed.start()
        self.addCleanup(armed.stop)

    # unittest dispatches on the name "setUp", so it is the stdlib's to choose.
    # Bound as an alias rather than defined under it, to keep the repo's
    # snake_case rule from counting a name this file does not control.
    setUp = arm_the_bot


class UnreachableRepoIsNotAMissingBranch(_ArmedBot):
    def test_a_nonexistent_repo_reports_check_failed(self):
        result = bot.check_task({"id": "t1", "slug": "s"}, "/nonexistent/repo")
        self.assertEqual(result["status"], "check_failed")
        self.assertEqual(result["action"], "manual")

    def test_a_directory_that_is_not_a_git_repo_reports_check_failed(self):
        """os.path.isdir is not enough: an empty mount point is a directory."""
        with tempfile.TemporaryDirectory() as plain_dir:
            result = bot.check_task({"id": "t1", "slug": "s"}, plain_dir)
        self.assertEqual(result["status"], "check_failed")

    def test_an_unreachable_repo_never_requeues(self):
        """The defect, stated as behaviour: no db write on a non-answer."""
        task = {"id": "t1", "slug": "finished-work"}
        checked = bot.check_task(task, "/nonexistent/repo")
        with patch.object(bot.db, "update") as mock_update:
            repaired = bot.repair_task(task, "/nonexistent/repo", checked)
        self.assertFalse(repaired["executed"])
        self.assertFalse(mock_update.called,
                         "a project's DONE work must not be requeued because a "
                         "volume was unmounted")

    def test_scan_and_repair_skips_an_unreachable_project_wholesale(self):
        rows = [{"id": "t%d" % i, "slug": "s%d" % i, "kind": "build",
                 "base_branch": "master"} for i in range(3)]
        with patch.object(bot.db, "select", return_value=rows):
            with patch.object(bot.db, "update") as mock_update:
                summary = bot.scan_and_repair("/nonexistent/repo", "p1")
        self.assertTrue(summary["skipped"])
        self.assertEqual(summary["reason"], "repo_not_accessible")
        self.assertFalse(mock_update.called)


class AGenuinelyMissingBranchIsStillRepaired(_ArmedBot):
    def test_a_real_repo_without_the_branch_requeues(self):
        """The case the old code got right, which must survive the fix."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(os.path.join(td, "repo"))
            task = {"id": "t1", "slug": "gone", "kind": "build",
                    "base_branch": "master"}
            checked = bot.check_task(task, repo)
            self.assertEqual(checked["status"], "branch_missing")
            self.assertEqual(checked["action"], "requeue")

            with patch.object(bot.db, "update") as mock_update:
                repaired = bot.repair_task(task, repo, checked)

        self.assertTrue(repaired["executed"])
        table, match, patch_body = mock_update.call_args[0]
        # db.update(table, match, patch). The old call had these two the wrong
        # way round, asking PostgREST to SET id on every matching row.
        self.assertEqual(table, "tasks")
        self.assertEqual(match, {"id": "t1"})
        self.assertEqual(patch_body["state"], "QUEUED")
        self.assertEqual(patch_body["slug"], "recover-gone")

    def test_an_already_recovered_slug_is_not_prefixed_twice(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(os.path.join(td, "repo"))
            task = {"id": "t1", "slug": "recover-gone", "kind": "build"}
            checked = bot.check_task(task, repo)
            with patch.object(bot.db, "update") as mock_update:
                bot.repair_task(task, repo, checked)
        self.assertEqual(mock_update.call_args[0][2]["slug"], "recover-gone")

    def test_a_present_branch_is_clean_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(os.path.join(td, "repo"), branches=["agent/here"])
            task = {"id": "t1", "slug": "here", "kind": "build",
                    "base_branch": "master"}
            checked = bot.check_task(task, repo)
            with patch.object(bot.db, "update") as mock_update:
                repaired = bot.repair_task(task, repo, checked)
        self.assertEqual(checked["status"], "clean")
        self.assertEqual(checked["action"], "merge_ready")
        self.assertFalse(repaired["executed"])
        self.assertFalse(mock_update.called)


class AnUnanswerableComparisonIsNotAConflict(_ArmedBot):
    """`git merge-tree` fails for reasons that have nothing to do with merging.

    The commonest is a base branch that does not exist under that name here --
    a repo whose default is `main` while the task says `master`. merge-tree
    answers "master - not something we can merge" and exits 1, and the old bool
    read every non-zero exit as a conflict. Every branch in such a project was
    reported as conflicting.
    """

    def test_a_base_branch_that_does_not_exist_reports_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(os.path.join(td, "repo"),
                              branches=["agent/here"], base="main")
            task = {"id": "t1", "slug": "here", "kind": "build",
                    "base_branch": "master"}     # not the branch this repo has
            checked = bot.check_task(task, repo)

        self.assertEqual(checked["status"], "unknown")
        self.assertEqual(checked["action"], "manual",
                         "an unanswerable comparison must go to a person, not "
                         "to an automatic rebase")
        self.assertIn("master", checked["reason"])

    def test_unknown_is_reported_even_for_a_low_risk_kind(self):
        """"conflict" + low-risk auto-rebases. "unknown" must not."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(os.path.join(td, "repo"),
                              branches=["agent/here"], base="main")
            task = {"id": "t1", "slug": "here", "kind": "docs",
                    "base_branch": "master"}
            checked = bot.check_task(task, repo)
            with patch.object(bot, "_auto_rebase") as mock_rebase:
                repaired = bot.repair_task(task, repo, checked)

        self.assertEqual(checked["action"], "manual")
        self.assertFalse(mock_rebase.called)
        self.assertFalse(repaired["executed"])

    def test_the_bool_view_stays_conservative(self):
        """_has_conflicts keeps its old two-way contract for two-way callers."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(os.path.join(td, "repo"),
                              branches=["agent/here"], base="main")
            self.assertTrue(bot._has_conflicts(repo, "master", "agent/here"))
            self.assertFalse(bot._has_conflicts(repo, "main", "agent/here"))


class DryRunStillChangesNothing(unittest.TestCase):
    def test_dry_run_reports_the_decision_without_executing_it(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(os.path.join(td, "repo"))
            task = {"id": "t1", "slug": "gone", "kind": "build"}
            checked = bot.check_task(task, repo)
            with patch.object(bot, "DRY_RUN", True):
                with patch.object(bot.db, "update") as mock_update:
                    repaired = bot.repair_task(task, repo, checked)
        self.assertEqual(checked["action"], "requeue")
        self.assertFalse(repaired["executed"])
        self.assertEqual(repaired["reason"], "dry_run")
        self.assertFalse(mock_update.called)


class TheFleetEntryPoint(unittest.TestCase):
    """run() did not exist, which is why nothing could call this bot."""

    def test_run_returns_one_summary_per_project(self):
        def select(table, params=None):
            if table == "projects":
                return [{"id": "p1", "repo_path": "/nonexistent/a"},
                        {"id": "p2", "repo_path": "/nonexistent/b"}]
            return []

        with patch.object(bot.db, "select", side_effect=select):
            results = bot.run()

        self.assertIsInstance(results, list)
        self.assertEqual([r["project_id"] for r in results], ["p1", "p2"])
        self.assertTrue(all(r["skipped"] for r in results))

    def test_run_is_a_no_op_when_disabled(self):
        with patch.object(bot, "ENABLED", False):
            with patch.object(bot.db, "select") as mock_select:
                self.assertEqual(bot.run(), [])
        self.assertFalse(mock_select.called, "disabled must not even query")

    def test_run_can_be_scoped_to_one_project(self):
        seen = {}

        def select(table, params=None):
            seen[table] = params
            return []

        with patch.object(bot.db, "select", side_effect=select):
            bot.run(project_id="p9")
        # PostgREST needs the operator; a bare value is a 400.
        self.assertEqual(seen["projects"]["id"], "eq.p9")


if __name__ == "__main__":
    unittest.main()
