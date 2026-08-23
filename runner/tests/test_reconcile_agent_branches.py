#!/usr/bin/env python3
"""
test_reconcile_agent_branches.py — pins the rule that kept being got wrong.

Several reconcile tasks in this repo stalled on "still conflicts after N redos". The
cause was treating an unmerged remote branch as recoverable value and re-importing its
files, which forks one change onto two branches and guarantees the train a conflict.
The branch is already durable provenance. These tests make that non-negotiable.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reconcile_agent_branches as rab  # noqa: E402


class NoisePathTests(unittest.TestCase):
    def test_build_and_scratch_output_is_noise(self):
        for p in ("node_modules/x/i.js", "dist/b.js", "coverage/lcov.info",
                  ".runtime/logs/a.log", "batch_chunks/c3/out.json", "__pycache__/m.pyc",
                  ".commit.sh", ".commit-message.txt",
                  ".recovery-intent-backlog-batch-beethoven-215245e.txt",
                  ".markdownlint.json", "docs/backlog-batch-beethoven-5aaa5de-stub.md",
                  "runner/a.pyc"):
            self.assertTrue(rab.is_noise_path(p), p)

    def test_real_source_is_not_noise(self):
        for p in ("runner/lane_guard.py", "runner/tests/test_approval_digest_batching.py",
                  "web/server/utils/fleetHealth.ts", "docs/architecture.md",
                  "APPROVAL_DIGEST_BATCHING.md"):
            self.assertFalse(rab.is_noise_path(p), p)

    def test_signal_paths_strips_noise_and_tolerates_junk(self):
        self.assertEqual(
            rab.signal_paths(["node_modules/x.js", "runner/a.py", "", None, 7]),
            ["runner/a.py"])
        self.assertEqual(rab.signal_paths(None), [])


class ClassifyTests(unittest.TestCase):
    def test_merged_is_already_present_and_retains_nothing(self):
        v, _r, keeps = rab.classify_branch("agent/x", merged=True)
        self.assertEqual(v, rab.ALREADY_PRESENT)
        self.assertFalse(keeps)

    def test_unmerged_adding_nothing_new_is_superseded(self):
        v, _r, keeps = rab.classify_branch("agent/x")
        self.assertEqual(v, rab.SUPERSEDED_BY_NEWER)
        self.assertFalse(keeps)

    def test_a_branch_adding_only_noise_is_superseded_not_recoverable(self):
        v, _r, _k = rab.classify_branch(
            "agent/x", adds_paths_absent_from_base=[".commit.sh", "coverage/lcov.info"])
        self.assertEqual(v, rab.SUPERSEDED_BY_NEWER)

    def test_unmerged_with_real_source_stays_with_the_train(self):
        """THE rule: the remote branch is the provenance. Never re-import it."""
        v, reason, keeps = rab.classify_branch(
            "agent/approval-digest-batching",
            adds_paths_absent_from_base=["runner/tests/test_approval_digest_batching.py"])
        self.assertEqual(v, rab.ACTIVE_IN_ANOTHER_TASK)
        self.assertTrue(keeps)
        self.assertIn("do not", reason)
        self.assertNotEqual(v, rab.RECOVERABLE_VALUE)

    def test_a_live_task_wins_so_work_is_never_duplicated(self):
        v, _r, _k = rab.classify_branch("agent/x", has_live_task=True,
                                        adds_paths_absent_from_base=["runner/a.py"])
        self.assertEqual(v, rab.ACTIVE_IN_ANOTHER_TASK)

    def test_conflicted_is_queued_not_forced(self):
        v, _r, keeps = rab.classify_branch("agent/x", conflicted=True)
        self.assertEqual(v, rab.CONFLICTED_NEEDS_FOCUSED_TASK)
        self.assertTrue(keeps)

    def test_merged_beats_conflicted(self):
        v, _r, _k = rab.classify_branch("agent/x", merged=True, conflicted=True)
        self.assertEqual(v, rab.ALREADY_PRESENT)

    def test_an_unnamed_ref_escalates_instead_of_vanishing(self):
        v, _r, keeps = rab.classify_branch("   ")
        self.assertEqual(v, rab.CONFLICTED_NEEDS_FOCUSED_TASK)
        self.assertTrue(keeps)

    def test_never_raises_on_garbage(self):
        for bad in (None, 0, object()):
            v, _r, _k = rab.classify_branch(bad)
            self.assertIn(v, rab.VERDICTS)


class ReconcileTests(unittest.TestCase):
    def test_every_item_is_classified_and_none_are_unknown(self):
        s = rab.reconcile([
            {"ref": "agent/a", "merged": True},
            {"ref": "agent/b"},
            {"ref": "agent/c", "adds_paths_absent_from_base": ["runner/c.py"]},
            {"ref": "agent/d", "conflicted": True},
        ])
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["unknown"], 0)
        self.assertEqual(sum(s["by_verdict"].values()), s["total"])
        self.assertEqual(s["by_verdict"][rab.ALREADY_PRESENT], 1)
        self.assertEqual(s["by_verdict"][rab.SUPERSEDED_BY_NEWER], 1)
        self.assertEqual(s["by_verdict"][rab.ACTIVE_IN_ANOTHER_TASK], 1)
        self.assertEqual(s["by_verdict"][rab.CONFLICTED_NEEDS_FOCUSED_TASK], 1)

    def test_retains_exactly_the_items_still_holding_value(self):
        s = rab.reconcile([
            {"ref": "agent/merged", "merged": True},
            {"ref": "agent/keeps", "adds_paths_absent_from_base": ["runner/x.py"]},
        ])
        self.assertEqual(s["retained"], ["agent/keeps"])

    def test_empty_input_is_a_valid_zero_unknown_reconciliation(self):
        s = rab.reconcile([])
        self.assertEqual((s["total"], s["unknown"], s["retained"]), (0, 0, []))

    def test_the_live_beethoven_shape_reconciles_with_zero_unknown(self):
        """1011 merged / 86 adding nothing / 98 carrying source — the real 2026-08 counts."""
        obs = ([{"ref": f"agent/m{i}", "merged": True} for i in range(1011)]
               + [{"ref": f"agent/n{i}"} for i in range(86)]
               + [{"ref": f"agent/s{i}", "adds_paths_absent_from_base": ["runner/x.py"]}
                  for i in range(98)])
        s = rab.reconcile(obs)
        self.assertEqual(s["total"], 1195)
        self.assertEqual(s["unknown"], 0)
        self.assertEqual(s["by_verdict"][rab.ALREADY_PRESENT], 1011)
        self.assertEqual(s["by_verdict"][rab.SUPERSEDED_BY_NEWER], 86)
        self.assertEqual(s["by_verdict"][rab.ACTIVE_IN_ANOTHER_TASK], 98)
        self.assertEqual(s["by_verdict"][rab.RECOVERABLE_VALUE], 0)


if __name__ == "__main__":
    unittest.main()
