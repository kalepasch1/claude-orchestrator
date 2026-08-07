#!/usr/bin/env python3
"""No recovery task without a recoverable input.

`recover-missing-branch-<slug>` asks an agent to "recreate the smallest equivalent
patch". When the branch is gone and no artifact or stored diff survives, there is
nothing to recreate: the task produces no code, re-detects as a missing branch, and
queues another recovery. 2,450 of the 9,918 code-less tasks came from that loop.

These tests pin the gate AND its fail-soft behaviour — the gate blocking real recovery
would be a worse outcome than the gap it closes.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import recovery_admission


def _run(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)


def _repo_with_branch(tmp, branch=None):
    """A real git repo, optionally carrying agent/<branch>."""
    _run(tmp, "init", "-q", "-b", "master")
    with open(os.path.join(tmp, "f.txt"), "w", encoding="utf-8") as fh:
        fh.write("x\n")
    _run(tmp, "add", "-A")
    _run(tmp, "-c", "user.name=T", "-c", "user.email=t@example.com",
         "commit", "--no-verify", "-q", "-m", "init")
    if branch:
        _run(tmp, "branch", f"agent/{branch}")
    return tmp


class _FakeDB(object):
    """Serves canned rows per table; records nothing else."""

    def __init__(self, **tables):
        self.tables = tables
        self.calls = []

    def select(self, table, params=None):
        self.calls.append((table, params))
        return list(self.tables.get(table, []))


class _ExplodingDB(object):
    def select(self, table, params=None):
        raise RuntimeError("db is down")


class DepthTest(unittest.TestCase):
    def test_depth_counts_the_slug_chain(self):
        P = recovery_admission.RECOVERY_PREFIX
        self.assertEqual(recovery_admission.recovery_depth("build-thing"), 0)
        self.assertEqual(recovery_admission.recovery_depth(f"{P}build-thing"), 1)
        self.assertEqual(recovery_admission.recovery_depth(f"{P}{P}build-thing"), 2)
        self.assertEqual(recovery_admission.recovery_depth(f"{P}{P}{P}build-thing"), 3)

    def test_rework_wrapped_recovery_is_still_recovery(self):
        P = recovery_admission.RECOVERY_PREFIX
        slug = f"rework-7-{P}{P}build-thing"
        self.assertTrue(recovery_admission.is_recovery_slug(slug))
        self.assertEqual(recovery_admission.recovery_depth(slug), 2)
        self.assertEqual(recovery_admission.recovery_root(slug), "build-thing")

    def test_depth_counts_recursion_nested_through_the_repair_path(self):
        """The shape that actually recurses in the live queue.

        `recover-missing-branch-rework-N-recover-missing-branch-x` is a recovery of a
        rework of a recovery. It carries no doubled leading prefix, so a leading-only
        count scores it 1 and the cap never fires — yet this is the dominant shape
        (507 rows) while the literal doubled prefix has 0.
        """
        P = recovery_admission.RECOVERY_PREFIX
        self.assertEqual(recovery_admission.recovery_depth(f"{P}rework-3-{P}build-thing"), 2)
        self.assertEqual(
            recovery_admission.recovery_depth(f"{P}rework-3-{P}rework-9-{P}build-thing"), 3)


class AdmissionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        os.environ.pop("ORCH_RECOVERY_MAX_DEPTH", None)

    def _row(self, slug):
        return {"slug": slug, "project_id": "p1"}

    # 1. Branch exists on origin -> recovery queued.
    def test_branch_exists_allows_recovery(self):
        _repo_with_branch(self.repo, branch="build-thing")
        slug = f"{recovery_admission.RECOVERY_PREFIX}build-thing"
        d = recovery_admission.check(self._row(slug), repo=self.repo, db_mod=_FakeDB())
        self.assertTrue(d.allowed, d.reason)
        self.assertEqual(d.input_kind, "branch")

    # 2. Stored patch_diff exists, branch gone -> recovery queued (the diff IS the input).
    def test_stored_patch_diff_allows_recovery_without_branch(self):
        _repo_with_branch(self.repo)
        slug = f"{recovery_admission.RECOVERY_PREFIX}build-thing"
        db = _FakeDB(task_artifacts=[{"patch_diff": "--- a/x\n+++ b/x\n@@\n+code\n"}])
        d = recovery_admission.check(self._row(slug), repo=self.repo, db_mod=db)
        self.assertTrue(d.allowed, d.reason)
        self.assertEqual(d.input_kind, "stored_diff")

    def test_merged_diff_allows_recovery_without_branch(self):
        _repo_with_branch(self.repo)
        slug = f"{recovery_admission.RECOVERY_PREFIX}build-thing"
        db = _FakeDB(merged_diffs=[{"diff": "--- a/x\n+++ b/x\n@@\n+code\n"}])
        d = recovery_admission.check(self._row(slug), repo=self.repo, db_mod=db)
        self.assertTrue(d.allowed, d.reason)
        self.assertEqual(d.input_kind, "stored_diff")

    def test_artifact_commit_allows_recovery_without_branch(self):
        _repo_with_branch(self.repo)
        sha = _run(self.repo, "rev-parse", "HEAD").stdout.strip()
        slug = f"{recovery_admission.RECOVERY_PREFIX}build-thing"
        db = _FakeDB(tasks=[{"artifact_commit": sha}])
        d = recovery_admission.check(self._row(slug), repo=self.repo, db_mod=db)
        self.assertTrue(d.allowed, d.reason)
        self.assertEqual(d.input_kind, "artifact_commit")

    # 3. No branch, no diff, no commit -> NOT queued; refusal recorded naming the original.
    def test_no_recoverable_input_refuses_and_names_the_original_slug(self):
        _repo_with_branch(self.repo)
        slug = f"{recovery_admission.RECOVERY_PREFIX}build-thing"
        d = recovery_admission.check(self._row(slug), repo=self.repo, db_mod=_FakeDB())
        self.assertFalse(d.allowed)
        self.assertIn(recovery_admission.NO_INPUT_REASON, d.reason)
        self.assertIn("build-thing", d.reason)

    def test_refusal_is_recorded_in_admission_rejections(self):
        _repo_with_branch(self.repo)
        slug = f"{recovery_admission.RECOVERY_PREFIX}build-thing"
        import db as db_mod
        recorded = []
        original = db_mod._record_refusal
        db_mod._record_refusal = lambda row, gate, reason: recorded.append((row, gate, reason))
        try:
            allowed = recovery_admission.enforce(self._row(slug), repo=self.repo,
                                                 db_mod=_FakeDB())
        finally:
            db_mod._record_refusal = original
        self.assertFalse(allowed)
        self.assertEqual(len(recorded), 1)
        row, gate, reason = recorded[0]
        self.assertEqual(gate, recovery_admission.GATE)
        self.assertIn(recovery_admission.NO_INPUT_REASON, reason)
        self.assertIn("build-thing", reason, "the rejection must name the original slug")

    # 4. recover-of-a-recover beyond MAX_DEPTH -> refused, escalated to operator.
    def test_depth_beyond_ceiling_is_refused(self):
        _repo_with_branch(self.repo)
        P = recovery_admission.RECOVERY_PREFIX
        slug = f"{P}{P}{P}build-thing"          # depth 3, ceiling 2
        d = recovery_admission.check(self._row(slug), repo=self.repo, db_mod=_FakeDB())
        self.assertFalse(d.allowed)
        self.assertIn("depth 3", d.reason)
        self.assertIn("operator", d.reason)

    def test_depth_at_ceiling_still_evaluates_inputs(self):
        """Depth 2 is allowed by the cap, so the input precondition decides."""
        P = recovery_admission.RECOVERY_PREFIX
        _repo_with_branch(self.repo, branch="build-thing")
        d = recovery_admission.check(self._row(f"{P}{P}build-thing"),
                                     repo=self.repo, db_mod=_FakeDB())
        self.assertTrue(d.allowed, d.reason)

    def test_ceiling_is_configurable(self):
        _repo_with_branch(self.repo)
        P = recovery_admission.RECOVERY_PREFIX
        os.environ["ORCH_RECOVERY_MAX_DEPTH"] = "1"
        self.addCleanup(os.environ.pop, "ORCH_RECOVERY_MAX_DEPTH", None)
        d = recovery_admission.check(self._row(f"{P}{P}x"), repo=self.repo, db_mod=_FakeDB())
        self.assertFalse(d.allowed)
        self.assertIn("depth 2", d.reason)

    # 5. Canary tasks are not misclassified as failed producers.
    def test_canaries_are_not_recovery_and_are_never_gated(self):
        self.assertTrue(recovery_admission.is_canary("canary-beethoven-0806"))
        self.assertFalse(recovery_admission.is_recovery_slug("canary-beethoven-0806"))
        d = recovery_admission.check(self._row("canary-beethoven-0806"),
                                     repo=self.repo, db_mod=_FakeDB())
        self.assertTrue(d.allowed)
        self.assertIn("not a recovery-class task", d.reason)

    def test_ordinary_tasks_pass_straight_through(self):
        d = recovery_admission.check(self._row("build-a-feature"),
                                     repo=self.repo, db_mod=_FakeDB())
        self.assertTrue(d.allowed)

    # 6. Precondition raises -> queue allowed, alarm raised (fail-soft).
    def test_gate_fails_open_with_an_alarm(self):
        slug = f"{recovery_admission.RECOVERY_PREFIX}build-thing"
        d = recovery_admission.check(self._row(slug), repo=self.repo, db_mod=_ExplodingDB())
        self.assertTrue(d.allowed, "an erroring gate must never block recovery")
        self.assertTrue(d.alarm)

    def test_enforce_allows_and_alarms_when_the_gate_errors(self):
        slug = f"{recovery_admission.RECOVERY_PREFIX}build-thing"
        self.assertTrue(recovery_admission.enforce(self._row(slug), repo=self.repo,
                                                   db_mod=_ExplodingDB()))

    def test_operator_origin_is_never_gated(self):
        """A human directive is a business input, not fleet churn."""
        _repo_with_branch(self.repo)
        slug = f"{recovery_admission.RECOVERY_PREFIX}build-thing"
        row = self._row(slug)
        row["submitted_by_label"] = "kale@smrter.us"
        d = recovery_admission.check(row, repo=self.repo, db_mod=_FakeDB())
        self.assertTrue(d.allowed, d.reason)
        self.assertIn("operator", d.reason)


if __name__ == "__main__":
    unittest.main()
