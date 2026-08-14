"""bulk_integrate_shelf must find already-committed agent branches and queue them once.

Everything here runs against a real throwaway git repository — the module's whole job is
reading git state correctly, and a mocked git would only prove the mock works. Only
merge_train is stubbed, so no test can touch the approvals table.
"""
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bulk_integrate_shelf as bis


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, check=True)


class ShelfRepo(unittest.TestCase):
    """master + a shelf of agent branches in known relationships."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="shelf_repo_")
        self.addCleanup(subprocess.run, ["rm", "-rf", self.repo])
        git(self.repo, "init", "-q", "-b", "master")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        for name in ("a.txt", "b.txt", "c.txt"):
            self.write(name, "base\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")

        # two branches touching a.txt -> one stack; one touching c.txt -> its own stack
        self.branch("agent/alpha", "a.txt", "alpha\n")
        self.branch("agent/beta", "a.txt", "beta\n")
        self.branch("agent/gamma", "c.txt", "gamma\n")

        # already merged into master -> must be skipped as integrated
        self.branch("agent/merged", "b.txt", "merged\n")
        git(self.repo, "checkout", "-q", "master")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "merge", "agent/merged")

        # ahead of master but with an empty diff -> nothing to integrate
        git(self.repo, "checkout", "-q", "-b", "agent/empty", "master")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "empty")
        git(self.repo, "checkout", "-q", "master")

    def write(self, name, content):
        with open(os.path.join(self.repo, name), "w") as f:
            f.write(content)

    def branch(self, name, path, content):
        git(self.repo, "checkout", "-q", "-b", name, "master")
        self.write(path, content)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", f"{name} touches {path}")
        git(self.repo, "checkout", "-q", "master")

    def shelf(self):
        return bis.list_shelf_branches(self.repo, "master")


class EnumerationTest(ShelfRepo):
    def test_finds_the_unmerged_agent_branches(self):
        slugs = {b["slug"] for b in self.shelf()}
        self.assertEqual(slugs, {"alpha", "beta", "gamma"})

    def test_already_merged_branch_is_skipped(self):
        self.assertNotIn("merged", {b["slug"] for b in self.shelf()})

    def test_empty_commit_branch_is_skipped(self):
        self.assertNotIn("empty", {b["slug"] for b in self.shelf()})

    def test_reports_ahead_count_and_files(self):
        alpha = next(b for b in self.shelf() if b["slug"] == "alpha")
        self.assertEqual(alpha["ahead"], 1)
        self.assertEqual(alpha["files"], ["a.txt"])
        self.assertEqual(alpha["branch"], "agent/alpha")
        self.assertTrue(alpha["tip"])

    def test_non_agent_branches_are_ignored(self):
        git(self.repo, "checkout", "-q", "-b", "hotfix/not-an-agent", "master")
        self.write("b.txt", "hotfix\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "hotfix")
        git(self.repo, "checkout", "-q", "master")
        self.assertNotIn("not-an-agent", {b["slug"] for b in self.shelf()})

    def test_enumeration_is_stable_across_calls(self):
        self.assertEqual([b["slug"] for b in self.shelf()],
                         [b["slug"] for b in self.shelf()])


class RebaseStackOrderTest(ShelfRepo):
    def order(self):
        return bis.rebase_stack_order(self.shelf())

    def test_every_branch_survives_ordering(self):
        self.assertEqual({b["slug"] for b in self.order()}, {"alpha", "beta", "gamma"})

    def test_branches_sharing_files_land_in_one_stack(self):
        stacks = {b["slug"]: b["stack"] for b in self.order()}
        self.assertEqual(stacks["alpha"], stacks["beta"])
        self.assertNotEqual(stacks["alpha"], stacks["gamma"])

    def test_related_branches_are_emitted_contiguously(self):
        slugs = [b["slug"] for b in self.order()]
        self.assertEqual(abs(slugs.index("alpha") - slugs.index("beta")), 1)

    def test_larger_stack_is_drained_first(self):
        self.assertEqual(self.order()[0]["stack_size"], 2)

    def test_oldest_commit_leads_its_stack(self):
        order = self.order()
        stack = [b for b in order if b["stack_size"] == 2]
        self.assertEqual([b["slug"] for b in stack], ["alpha", "beta"])
        self.assertEqual([b["stack_position"] for b in stack], [0, 1])

    def test_ordering_is_deterministic(self):
        self.assertEqual([b["slug"] for b in self.order()],
                         [b["slug"] for b in self.order()])

    def test_empty_shelf_orders_to_empty(self):
        self.assertEqual(bis.rebase_stack_order([]), [])


class SweepTest(ShelfRepo):
    def sweep(self, merge_train=None, **kw):
        merge_train = merge_train or types.SimpleNamespace(
            ensure_integration_card=MagicMock(return_value=True))
        with patch.dict(sys.modules, {"merge_train": merge_train}):
            report = bis.sweep(repo=self.repo, base="master", project="beethoven", **kw)
        return report, merge_train

    def test_dry_run_queues_nothing(self):
        report, mt = self.sweep(dry_run=True)
        mt.ensure_integration_card.assert_not_called()
        self.assertTrue(report["dry_run"])
        self.assertEqual({r["action"] for r in report["results"]}, {"would-queue"})

    def test_dry_run_still_lists_candidates_in_stack_order(self):
        report, _ = self.sweep(dry_run=True)
        self.assertEqual(len(report["candidates"]), 3)
        self.assertEqual(report["candidates"][0]["stack_size"], 2)

    def test_sweep_queues_each_branch_once(self):
        report, mt = self.sweep()
        self.assertEqual(mt.ensure_integration_card.call_count, 3)
        self.assertEqual(report["queued"], 3)

    def test_queued_card_is_an_integrate_card_naming_the_branch(self):
        _, mt = self.sweep()
        kwargs = mt.ensure_integration_card.call_args.kwargs
        self.assertEqual(kwargs["kind"], "integrate")
        self.assertIn("agent/", kwargs["title"])
        self.assertEqual(kwargs["decided_by"], "canonical-train:bulk-integrate-shelf")

    def test_sweep_never_runs_an_agent(self):
        # The only fleet entry point this module is allowed to touch is the integration
        # card. Anything else means the shelf sweep started re-running agents.
        report, mt = self.sweep()
        self.assertEqual(set(dir(mt)) & {"run_agent", "execute"}, set())
        self.assertTrue(all(r["action"] == "queued" for r in report["results"]))

    def test_second_sweep_is_idempotent(self):
        mt = types.SimpleNamespace(ensure_integration_card=MagicMock(return_value=False))
        report, _ = self.sweep(merge_train=mt)
        self.assertEqual(report["queued"], 0)
        self.assertEqual(report["already_queued"], 3)

    def test_one_failing_branch_does_not_end_the_sweep(self):
        calls = {"n": 0}

        def flaky(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db down")
            return True

        mt = types.SimpleNamespace(ensure_integration_card=MagicMock(side_effect=flaky))
        report, _ = self.sweep(merge_train=mt)
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["queued"], 2)
        self.assertEqual(len(report["results"]), 3)

    def test_limit_caps_the_batch(self):
        report, mt = self.sweep(limit=1)
        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(mt.ensure_integration_card.call_count, 1)

    def test_sweep_on_a_clean_repo_reports_nothing(self):
        git(self.repo, "checkout", "-q", "master")
        for name in ("agent/alpha", "agent/beta", "agent/gamma"):
            git(self.repo, "branch", "-qD", name)
        report, mt = self.sweep()
        self.assertEqual(report["candidates"], [])
        mt.ensure_integration_card.assert_not_called()


class ResolutionTest(ShelfRepo):
    def test_explicit_base_wins(self):
        self.assertEqual(bis.resolve_base(self.repo, "orchestrator/dev"), "orchestrator/dev")

    def test_base_falls_back_to_a_real_local_branch(self):
        self.assertEqual(bis.resolve_base(self.repo, None), "master")

    def test_explicit_project_wins(self):
        self.assertEqual(bis.resolve_project(self.repo, "smarter"), "smarter")

    def test_project_falls_back_to_directory_name_when_db_unavailable(self):
        with patch.dict(sys.modules, {"db": types.SimpleNamespace(
                select=MagicMock(side_effect=RuntimeError("no db")))}):
            self.assertEqual(bis.resolve_project(self.repo, None),
                             os.path.basename(self.repo))


class CliTest(ShelfRepo):
    def test_dry_run_cli_lists_branches_in_stack_order(self):
        script = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "bulk_integrate_shelf.py")
        r = subprocess.run([sys.executable, script, "--repo", self.repo,
                            "--base", "master", "--project", "beethoven", "--dry-run"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("DRY RUN", r.stdout)
        self.assertIn("stack 0 (2 branch(es))", r.stdout)
        for branch in ("agent/alpha", "agent/beta", "agent/gamma"):
            self.assertIn(branch, r.stdout)

    def test_json_output_parses(self):
        import json
        script = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "bulk_integrate_shelf.py")
        r = subprocess.run([sys.executable, script, "--repo", self.repo,
                            "--base", "master", "--project", "beethoven",
                            "--dry-run", "--json"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        report = json.loads(r.stdout)
        self.assertEqual(len(report["candidates"]), 3)
        self.assertTrue(report["dry_run"])


if __name__ == "__main__":
    unittest.main()
