"""The driver's STAGES must cover every evidence shape it has a reconciler for.

Run: python3 -m pytest tools/tests/test_reconcile_all_evidence_coverage.py

reconcile_all_evidence.py exists so a recovery task gets ONE ledger with zero
UNKNOWN across every shape of local evidence. Its docstring named six shapes;
STAGES ran three. Stashes and unmerged agent branches each had a reconciler
sitting in the same directory and were never invoked, so the driver reported a
complete run over evidence it had not looked at -- the "missing input
masquerading as clean evidence" its own contract says it prevents.

A missing STAGES entry is invisible by construction: nothing errors, the ledger
just does not mention that class. So the coverage is asserted here rather than
left to review.
"""

import os
import sys
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import reconcile_all_evidence as driver  # noqa: E402


class Args:
    """The subset of argparse output stage_argv() reads."""

    dropbox = ""
    exclude_path = ""
    exclude_branch = ""
    live_slugs = ""
    agent_branch_pattern = ""


class TestStagesCoverage(unittest.TestCase):
    def test_every_stage_script_exists(self):
        for script, _kind in driver.STAGES:
            self.assertTrue(os.path.isfile(os.path.join(TOOLS, script)),
                            "STAGES names a reconciler that is not there: " + script)

    def test_stash_evidence_is_covered(self):
        scripts = [s for s, _ in driver.STAGES]
        self.assertIn(
            "reconcile_stashes.py", scripts,
            "stashes are not covered by the rescue-ref stage -- "
            "`git for-each-ref refs/stash` returns only the tip of the stack",
        )

    def test_unmerged_agent_branches_are_covered(self):
        self.assertIn("reconcile_agent_branches.py",
                      [s for s, _ in driver.STAGES])

    def test_kinds_are_unique(self):
        kinds = [k for _, k in driver.STAGES]
        self.assertEqual(len(kinds), len(set(kinds)),
                         "two stages sharing a kind collide in the dedupe key")

    def test_scripts_are_unique(self):
        scripts = [s for s, _ in driver.STAGES]
        self.assertEqual(len(scripts), len(set(scripts)))


class TestStageArgv(unittest.TestCase):
    """Every stage must be invoked with arguments its own CLI accepts."""

    def argv(self, script, args=None):
        return driver.stage_argv(script, TOOLS, "origin/master", "deadbeef",
                                 "/repo", "/tmp/out.json", args or Args())

    def test_common_flags_are_passed_to_every_stage(self):
        for script, _kind in driver.STAGES:
            argv = self.argv(script)
            for flag in ("--base", "--fingerprint", "--out"):
                self.assertIn(flag, argv, "%s missing %s" % (script, flag))

    def test_stash_stage_gets_only_flags_it_accepts(self):
        argv = self.argv("reconcile_stashes.py")
        # reconcile_stashes.py takes --base/--fingerprint/--out/--depth only.
        for flag in ("--repo", "--dropbox", "--exclude-self", "--pattern"):
            self.assertNotIn(flag, argv)

    def test_agent_branch_stage_forwards_live_slugs(self):
        args = Args()
        args.live_slugs = "slug-a,slug-b"
        argv = self.argv("reconcile_agent_branches.py", args)
        self.assertIn("--live-slugs", argv)
        self.assertIn("slug-a,slug-b", argv)

    def test_agent_branch_stage_omits_live_slugs_when_empty(self):
        self.assertNotIn("--live-slugs", self.argv("reconcile_agent_branches.py"))

    def test_agent_branch_pattern_is_optional(self):
        args = Args()
        args.agent_branch_pattern = "refs/heads/agent/*"
        argv = self.argv("reconcile_agent_branches.py", args)
        self.assertIn("--pattern", argv)
        self.assertIn("refs/heads/agent/*", argv)

    def test_worktree_stage_still_gets_repo_and_dropbox(self):
        args = Args()
        args.dropbox = "/tmp/dropbox"
        argv = self.argv("reconcile_worktree_evidence.py", args)
        self.assertIn("--repo", argv)
        self.assertIn("--dropbox", argv)


class TestMissingReconcilerIsNotClean(unittest.TestCase):
    def test_absent_script_is_recorded_not_skipped(self):
        items, status = driver.run_stage(
            "reconcile_does_not_exist.py", "phantom", TOOLS, "origin/master",
            "deadbeef", "/repo", Args())
        self.assertEqual(status, "missing")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["classification"],
                         "CONFLICTED_NEEDS_FOCUSED_TASK")
        self.assertIn("must not be reported as clean", items[0]["disposition"])


if __name__ == "__main__":
    unittest.main()
