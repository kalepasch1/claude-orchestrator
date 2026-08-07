#!/usr/bin/env python3
"""MERGED must mean the commit reached the integration branch.

Measured 2026-08-06 across 24 recent beethoven MERGED rows with a non-null artifact_commit:
17% were in master, 42% were not ancestors of master, 41% did not exist on origin at all.
The original audit correctly caught evidence-free rows, but using production as the target
also misclassified every legitimate staging commit waiting for the release train. These
tests pin the two-phase state model: MERGED means staging-reachable; production is certified
later as DEPLOYED_AND_VERIFIED.

The audit's fix — populate artifact_commit — did not help, because presence is not
reachability. These tests pin reachability, and pin equally hard that an infrastructure
failure must NOT be read as a phantom (the mirror-image bug, which would mass-downgrade real
merges the first time a fetch times out).

Uses real throwaway git repos: the whole point is the git ancestry question, and mocking it
would only test the mock.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import merge_truth


def _run(*args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


def _commit(repo, name, content="x"):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(content)
    _run("git", "add", "-A", cwd=repo)
    _run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", name, cwd=repo)
    return _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()


class _Repo(unittest.TestCase):
    """A repo with master (prod) and a side branch that was never merged."""

    def setUp(self):
        merge_truth.invalidate_fetch_cache()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        _run("git", "init", "-q", "-b", "master", cwd=self.repo)
        self.on_master = _commit(self.repo, "a.txt")
        _run("git", "checkout", "-q", "-b", "side", cwd=self.repo)
        self.on_side = _commit(self.repo, "b.txt")
        _run("git", "checkout", "-q", "master", cwd=self.repo)


class TestVerifyMergeReachable(_Repo):

    def test_commit_on_prod_is_ok(self):
        v, why = merge_truth.verify_merge_reachable(self.repo, self.on_master, "master",
                                                    fetch=False)
        self.assertEqual(v, merge_truth.OK, why)

    def test_commit_only_on_side_branch_is_phantom(self):
        """A real commit that never reached the requested integration ref is still phantom."""
        v, why = merge_truth.verify_merge_reachable(self.repo, self.on_side, "master",
                                                    fetch=False)
        self.assertEqual(v, merge_truth.PHANTOM, why)
        self.assertIn("not an ancestor", why)

    def test_commit_on_staging_is_ok_before_production(self):
        """The release train may legitimately leave MERGED work on staging for a batch."""
        v, why = merge_truth.verify_merge_reachable(self.repo, self.on_side, "side",
                                                    fetch=False)
        self.assertEqual(v, merge_truth.OK, why)

    def test_nonexistent_commit_is_phantom(self):
        """41% of the audited rows: a sha that exists nowhere."""
        v, why = merge_truth.verify_merge_reachable(
            self.repo, "0" * 40, "master", fetch=False)
        self.assertEqual(v, merge_truth.PHANTOM, why)
        self.assertIn("does not exist", why)

    def test_empty_artifact_commit_is_phantom(self):
        for sha in ("", None, "   "):
            with self.subTest(sha=sha):
                v, why = merge_truth.verify_merge_reachable(self.repo, sha, "master",
                                                            fetch=False)
                self.assertEqual(v, merge_truth.PHANTOM, why)

    def test_presence_of_a_sha_is_not_acceptance(self):
        """The 2026-08-04 regression in one assertion: populated != reachable."""
        self.assertTrue(self.on_side)  # non-empty, i.e. the old gate would have passed it
        v, _ = merge_truth.verify_merge_reachable(self.repo, self.on_side, "master",
                                                  fetch=False)
        self.assertNotEqual(v, merge_truth.OK)

    # ── infra errors must never masquerade as phantoms ──

    def test_missing_repo_is_infra_error_not_phantom(self):
        v, _ = merge_truth.verify_merge_reachable("/no/such/repo", self.on_master, "master",
                                                  fetch=False)
        self.assertEqual(v, merge_truth.INFRA_ERROR)

    def test_unknown_target_branch_is_infra_error_not_phantom(self):
        """We cannot ask the question — that is not the same as the answer being no."""
        v, _ = merge_truth.verify_merge_reachable(self.repo, self.on_master, "nope",
                                                  fetch=False)
        self.assertEqual(v, merge_truth.INFRA_ERROR)

    def test_missing_target_branch_config_is_infra_error(self):
        v, _ = merge_truth.verify_merge_reachable(self.repo, self.on_master, None, fetch=False)
        self.assertEqual(v, merge_truth.INFRA_ERROR)

    def test_fetch_timeout_is_infra_error_not_phantom(self):
        """Rule 4. A timed-out fetch must never flip a real merge to PHANTOM_UNVERIFIED."""
        with patch.object(merge_truth, "_git",
                          side_effect=subprocess.TimeoutExpired("git", 60)):
            v, why = merge_truth.verify_merge_reachable(self.repo, self.on_master, "master",
                                                        fetch=True)
        self.assertEqual(v, merge_truth.INFRA_ERROR, why)

    def test_fetch_failure_is_infra_error_not_phantom(self):
        """No 'origin' remote here, so the fetch genuinely fails."""
        v, _ = merge_truth.verify_merge_reachable(self.repo, self.on_master, "master",
                                                  fetch=True)
        self.assertEqual(v, merge_truth.INFRA_ERROR)


class TestGateMergedPatch(_Repo):

    def setUp(self):
        super().setUp()
        self.task = {"id": "t1", "slug": "some-task", "project_id": "p1"}
        alarm = patch.object(merge_truth, "raise_phantom_alarm", return_value=True)
        self.alarm = alarm.start()
        self.addCleanup(alarm.stop)

    def _gate(self, patch_body):
        return merge_truth.gate_merged_patch(self.task, patch_body, repo=self.repo,
                                             prod_branch="master", fetch=False)

    def test_non_merged_patch_passes_through_untouched(self):
        body = {"state": "DONE", "note": "n"}
        self.assertEqual(self._gate(body), body)
        self.alarm.assert_not_called()

    def test_reachable_merged_is_allowed(self):
        body = {"state": "MERGED", "artifact_commit": self.on_master}
        self.assertEqual(self._gate(body)["state"], "MERGED")
        self.alarm.assert_not_called()

    def test_staging_reachable_merged_is_allowed_before_prod(self):
        out = merge_truth.gate_merged_patch(
            self.task, {"state": "MERGED", "artifact_commit": self.on_side},
            repo=self.repo, prod_branch="side", fetch=False)
        self.assertEqual(out["state"], "MERGED")
        self.alarm.assert_not_called()

    def test_unreachable_merged_becomes_phantom_unverified(self):
        out = self._gate({"state": "MERGED", "artifact_commit": self.on_side})
        self.assertEqual(out["state"], merge_truth.PHANTOM_STATE)
        self.assertIn("not an ancestor", out["note"])
        self.assertIn(self.on_side[:12], out["note"])
        self.alarm.assert_called_once()

    def test_merged_without_sha_becomes_phantom_unverified(self):
        """batch_fusion wrote MERGED with no artifact_commit at all."""
        out = self._gate({"state": "MERGED"})
        self.assertEqual(out["state"], merge_truth.PHANTOM_STATE)
        self.alarm.assert_called_once()

    def test_infra_error_writes_nothing(self):
        """Returning None is the contract for 'leave the row alone'."""
        with patch.object(merge_truth, "verify_merge_reachable",
                          return_value=(merge_truth.INFRA_ERROR, "network down")):
            out = self._gate({"state": "MERGED", "artifact_commit": self.on_master})
        self.assertIsNone(out)
        self.alarm.assert_not_called()

    def test_note_records_which_check_failed_and_the_sha(self):
        out = self._gate({"state": "MERGED", "artifact_commit": "0" * 40, "note": "orig"})
        self.assertIn("does not exist", out["note"])
        self.assertIn("0" * 12, out["note"])
        self.assertIn("integration_branch=master", out["note"])
        self.assertIn("orig", out["note"], "original note must be preserved")

    def test_falls_back_to_task_artifact_commit(self):
        self.task["artifact_commit"] = self.on_master
        self.assertEqual(self._gate({"state": "MERGED"})["state"], "MERGED")

    def test_lowercase_state_is_still_gated(self):
        out = merge_truth.gate_merged_patch(
            self.task, {"state": "merged", "artifact_commit": self.on_side},
            repo=self.repo, prod_branch="master", fetch=False)
        self.assertEqual(out["state"], merge_truth.PHANTOM_STATE)


class TestResolveTarget(unittest.TestCase):

    def setUp(self):
        self.task = {"project_id": "p1"}
        self.project = {
            "id": "p1", "repo_path": "/repo", "staging_branch": "stale/staging",
            "default_base": "master", "prod_branch": "master",
        }

    def test_dev_mode_uses_runtime_staging_branch_over_stale_project_value(self):
        with patch.object(merge_truth, "_project_row", return_value=self.project), \
             patch.dict(os.environ, {
                 "ORCH_CODE_MERGE_TARGET": "dev",
                 "ORCH_STAGING_BRANCH": "orchestrator/dev",
             }):
            self.assertEqual(
                merge_truth.resolve_target(self.task),
                ("/repo", "orchestrator/dev", None),
            )

    def test_direct_prod_mode_uses_the_same_base_as_merge_train(self):
        with patch.object(merge_truth, "_project_row", return_value=self.project), \
             patch.dict(os.environ, {
                 "ORCH_CODE_MERGE_TARGET": "prod",
                 "ORCH_STAGING_BRANCH": "orchestrator/dev",
             }):
            self.assertEqual(
                merge_truth.resolve_target(self.task),
                ("/repo", "master", None),
            )


class TestGuardedTaskUpdate(_Repo):

    def test_infra_error_performs_no_db_write(self):
        writes = []
        with patch.object(merge_truth.db, "update",
                          side_effect=lambda *a, **k: writes.append(a)), \
             patch.object(merge_truth, "gate_merged_patch", return_value=None):
            result = merge_truth.guarded_task_update({"id": "t1"}, {"state": "MERGED"})
        self.assertIsNone(result)
        self.assertEqual(writes, [], "wrote to the DB despite an infra error")

    def test_allowed_patch_is_written(self):
        writes = []
        with patch.object(merge_truth.db, "update",
                          side_effect=lambda *a, **k: writes.append(a)), \
             patch.object(merge_truth, "gate_merged_patch",
                          return_value={"state": "MERGED"}):
            merge_truth.guarded_task_update({"id": "t1"}, {"state": "MERGED"})
        self.assertEqual(len(writes), 1)


class TestReconcilerIsReadOnly(_Repo):

    def test_reconcile_never_mutates(self):
        """Operators must be able to ask the question without the answer changing anything."""
        tasks = [{"id": "t1", "slug": "a", "project_id": "p1",
                 "artifact_commit": self.on_side, "updated_at": "2026-08-06"},
                 {"id": "t2", "slug": "b", "project_id": "p1",
                  "artifact_commit": "0" * 40, "updated_at": "2026-08-06"}]
        projects = [{"id": "p1", "name": "beethoven", "repo_path": self.repo,
                     "staging_branch": "side", "prod_branch": "master",
                     "default_base": "master"}]

        def _sel(table, params=None):
            return tasks if table == "tasks" else projects

        writes = []
        with patch.object(merge_truth.db, "select", side_effect=_sel), \
             patch.object(merge_truth.db, "update",
                          side_effect=lambda *a, **k: writes.append(a)), \
             patch.object(merge_truth.db, "insert",
                          side_effect=lambda *a, **k: writes.append(a)):
            report = merge_truth.reconcile(fetch=False)

        self.assertEqual(writes, [], "reconciler mutated state")
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 2)
        self.assertEqual(report["real"], 1)
        self.assertEqual(report["phantom"], 1)
        self.assertEqual(report["real_share"], 0.5)
        self.assertEqual(report["offenders"][0]["slug"], "b")

    def test_infra_errors_excluded_from_share(self):
        """Unknown is not bad. Counting infra errors as phantoms would overstate the problem."""
        tasks = [{"id": "t1", "slug": "a", "project_id": "p1",
                  "artifact_commit": self.on_master, "updated_at": "x"},
                 {"id": "t2", "slug": "b", "project_id": "p2",
                  "artifact_commit": "abc", "updated_at": "x"}]
        projects = [{"id": "p1", "name": "beethoven", "repo_path": self.repo,
                     "staging_branch": "master", "prod_branch": "master",
                     "default_base": "master"},
                    {"id": "p2", "name": "broken", "repo_path": "/no/such/repo",
                     "staging_branch": "orchestrator/dev", "prod_branch": "main",
                     "default_base": "main"}]

        def _sel(table, params=None):
            return tasks if table == "tasks" else projects

        with patch.object(merge_truth.db, "select", side_effect=_sel):
            report = merge_truth.reconcile(fetch=False)

        self.assertEqual(report["real"], 1)
        self.assertEqual(report["unverifiable"], 1)
        self.assertEqual(report["real_share"], 1.0)


class TestAlarmDedupe(unittest.TestCase):

    def test_existing_open_alarm_suppresses_a_second(self):
        with patch.object(merge_truth.db, "select", return_value=[{"id": "a1"}]), \
             patch.object(merge_truth.db, "insert") as ins:
            self.assertFalse(merge_truth.raise_phantom_alarm({"id": "t"}, "sha", "why"))
        ins.assert_not_called()

    def test_first_alarm_is_written_with_the_expected_kind(self):
        with patch.object(merge_truth.db, "select", return_value=[]), \
             patch.object(merge_truth.db, "insert") as ins:
            self.assertTrue(merge_truth.raise_phantom_alarm({"id": "t"}, "sha", "why"))
        table, row = ins.call_args[0][0], ins.call_args[0][1]
        self.assertEqual(table, "orch_gate_alarms")
        self.assertEqual(row["kind"], "phantom_merge_blocked")

    def test_alarm_failure_is_fail_soft(self):
        with patch.object(merge_truth.db, "select", side_effect=RuntimeError("db down")):
            self.assertFalse(merge_truth.raise_phantom_alarm({"id": "t"}, "sha", "why"))


class TestEveryWriterIsGated(unittest.TestCase):
    """Guard against a new (or restored) ungated MERGED writer.

    Seven sites wrote state='MERGED': merge_train (x2, via _task_patch), integration_sweeper,
    quarantine_remediation, continuous_merger, sweep_reconciler, batch_fusion. Each must now
    reach the DB through merge_truth.
    """

    RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    WRITERS = ("merge_train.py", "integration_sweeper.py", "quarantine_remediation.py",
               "continuous_merger.py", "sweep_reconciler.py", "batch_fusion.py")

    def test_each_known_writer_imports_merge_truth(self):
        for name in self.WRITERS:
            with self.subTest(module=name):
                src = open(os.path.join(self.RUNNER, name)).read()
                self.assertIn("merge_truth", src,
                              f"{name} writes MERGED but does not route through merge_truth")

    def test_no_raw_merged_update_outside_the_gate(self):
        """A raw db.update(...state=MERGED...) in a writer means the gate was bypassed."""
        import re
        pattern = re.compile(
            r"db(?:_module)?\.update\(\s*[\"']tasks[\"'][^)]{0,400}?[\"']MERGED[\"']",
            re.S)
        for name in self.WRITERS:
            with self.subTest(module=name):
                src = open(os.path.join(self.RUNNER, name)).read()
                self.assertIsNone(pattern.search(src),
                                  f"{name} still writes MERGED directly, bypassing merge_truth")


if __name__ == "__main__":
    unittest.main()
