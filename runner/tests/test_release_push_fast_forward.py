#!/usr/bin/env python3
"""The prod push must fast-forward.

release_train used to push STAGING straight onto the remote prod branch with no
fetch of origin/<prod> and no integration of it beforehand. origin/<prod>
advances constantly, so the push was routinely rejected as a non-fast-forward:
the release failed AND commits that tasks already claimed as MERGED were left
on one machine's disk, never reaching origin.
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import release_train


def _run(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)


def _commit(cwd, name, body, message):
    with open(os.path.join(cwd, name), "w", encoding="utf-8") as fh:
        fh.write(body)
    _run(cwd, "add", "-A")
    _run(cwd, "-c", "user.name=T", "-c", "user.email=t@example.com",
         "commit", "--no-verify", "-m", message)


class _FakeDB:
    """Minimal db stand-in: records writes, serves canned task rows."""

    def __init__(self, tasks=None):
        self.tasks = tasks or []
        self.inserted = []
        self.updated = []

    def select(self, table, params=None):
        return list(self.tasks) if table == "tasks" else []

    def insert(self, table, values):
        self.inserted.append((table, values))
        return {"id": len(self.inserted), **values}

    def update(self, table, match, values):
        self.updated.append((table, match, values))
        return values


class ReleasePushFastForwardTest(unittest.TestCase):
    """Each test gets a real origin + a real clone; nothing is mocked at the git layer."""

    def setUp(self):
        import tempfile, shutil
        self.staging = "orchestrator/dev"
        self.prod = "master"
        self.tmp = tempfile.mkdtemp(prefix="relpush-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.origin = os.path.join(self.tmp, "origin.git")
        _run(self.tmp, "init", "--bare", "--initial-branch", self.prod, self.origin)

        # "other host" clone: the one that advances origin/<prod> behind our back
        self.other = os.path.join(self.tmp, "other")
        _run(self.tmp, "clone", self.origin, self.other)
        _commit(self.other, "base.txt", "base\n", "base")
        _run(self.other, "push", "origin", f"HEAD:{self.prod}")

        # our repo
        self.repo = os.path.join(self.tmp, "repo")
        _run(self.tmp, "clone", self.origin, self.repo)
        _run(self.repo, "branch", self.staging, self.prod)
        self.saved_staging = release_train.STAGING
        release_train.STAGING = self.staging
        self.addCleanup(setattr, release_train, "STAGING", self.saved_staging)

        self.saved_db = release_train.db
        self.db = _FakeDB()
        release_train.db = self.db
        self.addCleanup(setattr, release_train, "db", self.saved_db)

        # Record the self-heal / failed-release side effects instead of hitting the DB.
        self.failed = []
        self.healed = []
        self._patch("_insert_failed_release",
                    lambda project, gate, ahead, from_sha, to_sha, note:
                        self.failed.append({"gate": gate, "note": note, "to_sha": to_sha}))
        self._patch("_self_heal_release_conflict",
                    lambda p, project, repo, prod, log: self.healed.append(log))
        self._patch("_self_heal_build", lambda p, project, repo, ref, log:
                    self.healed.append(f"build:{log}"))
        self._patch("_self_heal_qa", lambda p, project, repo, ref, log:
                    self.healed.append(f"qa:{log}"))

        # Spy on every git invocation so a test can assert what was (not) run.
        self.git_calls = []
        real_git = release_train._git

        def spy(repo, *args, **kwargs):
            self.git_calls.append(list(args))
            return real_git(repo, *args, **kwargs)

        self._patch("_git", spy)

        # Gates are exercised separately; default to green and record the SHA they saw.
        self.gated_shas = []
        self._patch("_rerun_release_gates",
                    lambda repo, sha, tc, rt, bc: (self.gated_shas.append(sha), (True, "", ""))[1])
        self.proved_shas = []
        self._patch("_persist_production_build_proof",
                    lambda repo, sha, cmd: (self.proved_shas.append(sha), (True, cmd))[1])

    def _patch(self, name, value):
        saved = getattr(release_train, name)
        setattr(release_train, name, value)
        self.addCleanup(setattr, release_train, name, saved)

    def _stage_commit(self, name="feature.txt", body="feature\n", message="staged work"):
        """Commit onto the staging branch without disturbing the checked-out tree."""
        import tempfile, shutil
        wt = tempfile.mkdtemp(prefix="stg-wt-")
        _run(self.repo, "worktree", "add", "-f", wt, self.staging)
        _commit(wt, name, body, message)
        _run(self.repo, "worktree", "remove", "--force", wt)
        shutil.rmtree(wt, ignore_errors=True)
        _run(self.repo, "worktree", "prune")

    def _advance_origin_prod(self, name="hotfix.txt", body="hotfix\n"):
        _commit(self.other, name, body, "prod moved under us")
        _run(self.other, "push", "origin", f"HEAD:{self.prod}")

    def _push(self, **kw):
        return release_train._integrate_regate_and_push(
            {"id": "proj-1"}, "demo", self.repo, self.prod, "1", "base-sha", "staging-sha",
            test_cmd="", require_tests=False, build_cmd="echo build", **kw)

    def _origin_log(self):
        return _run(self.origin, "log", "--format=%s", self.prod).stdout

    # 1. origin/prod ahead of STAGING -> integrate, push is a fast-forward, succeeds
    def test_integrates_then_fast_forwards_when_origin_prod_is_ahead(self):
        self._stage_commit()
        self._advance_origin_prod()

        pushed, to_sha, log = self._push()

        self.assertTrue(pushed, log)
        origin_log = self._origin_log()
        self.assertIn("staged work", origin_log)
        self.assertIn("prod moved under us", origin_log)
        # The pushed tip is the integrated tip, and it contains the remote prod tip.
        remote_tip = _run(self.origin, "rev-parse", self.prod).stdout.strip()
        self.assertEqual(remote_tip, to_sha)
        self.assertEqual([to_sha], self.proved_shas)
        self.assertEqual([], self.failed)

    # 2. integration conflicts -> failed release recorded, self-heal queued, NO push, no force
    def test_conflicting_integration_records_failure_and_never_pushes(self):
        self._stage_commit("shared.txt", "staging version\n", "staging edits shared")
        self._advance_origin_prod("shared.txt", "prod version\n")

        pushed, _to_sha, log = self._push()

        self.assertFalse(pushed)
        self.assertTrue(self.healed, "a conflicting prod integration must queue a self-heal")
        self.assertTrue(any(f["gate"] == "refresh" for f in self.failed),
                        f"expected a recorded refresh failure, got {self.failed}")
        self.assertTrue(any(f["note"] for f in self.failed), "failure must carry conflict detail")
        self.assertTrue(log, "the conflict detail must be returned to the caller")
        pushes = [c for c in self.git_calls if c and c[0] == "push"]
        self.assertEqual([], pushes, "no push may be attempted after a failed integration")
        self.assertNotIn("staging edits shared", self._origin_log())

    # 3. gates are re-run against the POST-integration tip
    def test_gates_rerun_against_integrated_tip(self):
        self._stage_commit()
        pre_integration = _run(self.repo, "rev-parse", self.staging).stdout.strip()
        self._advance_origin_prod()

        pushed, to_sha, log = self._push()

        self.assertTrue(pushed, log)
        self.assertEqual(1, len(self.gated_shas),
                         "the integrated tip must be re-verified exactly once")
        self.assertNotEqual(pre_integration, self.gated_shas[0],
                            "re-gating the pre-integration tip certifies a tree we never built")
        self.assertEqual(to_sha, self.gated_shas[0])

    def test_no_regate_when_integration_is_a_no_op(self):
        # Staging already contains prod: nothing new to verify, so no wasted gate run.
        self._stage_commit()
        pushed, _to_sha, log = self._push()
        self.assertTrue(pushed, log)
        self.assertEqual([], self.gated_shas)

    def test_red_post_integration_gate_blocks_the_push(self):
        self._patch("_rerun_release_gates",
                    lambda repo, sha, tc, rt, bc: (False, "build", "post-integration build red"))
        self._stage_commit()
        self._advance_origin_prod()

        pushed, _to_sha, log = self._push()

        self.assertFalse(pushed)
        self.assertIn("build red", log)
        self.assertTrue(any(f["gate"] == "build" for f in self.failed))
        self.assertEqual([], [c for c in self.git_calls if c and c[0] == "push"])
        self.assertNotIn("staged work", self._origin_log())

    def test_missing_exact_build_proof_blocks_the_push(self):
        self._patch("_persist_production_build_proof",
                    lambda repo, sha, cmd: (False, "proof graph write failed"))
        self._stage_commit()

        pushed, _to_sha, log = self._push()

        self.assertFalse(pushed)
        self.assertIn("proof graph", log)
        self.assertTrue(any(f["gate"] == "proof" for f in self.failed))
        self.assertEqual([], [c for c in self.git_calls if c and c[0] == "push"])

    # 4. push fails for a non-conflict reason -> failed release with the real stderr
    def test_non_conflict_push_failure_records_real_stderr(self):
        self._stage_commit()
        _run(self.repo, "remote", "set-url", "origin", os.path.join(self.tmp, "gone.git"))

        pushed, _to_sha, log = self._push()

        self.assertFalse(pushed)
        push_failures = [f for f in self.failed if f["gate"] == "push"]
        self.assertTrue(push_failures, f"expected a push failure row, got {self.failed}")
        self.assertTrue(log.strip(), "the real push stderr must be captured, not a placeholder")
        self.assertTrue(self.healed, "a failed push must queue a self-heal")

    def test_non_fast_forward_is_retried_after_reintegration(self):
        self._stage_commit()
        real_git = release_train._git
        state = {"attempts": 0}

        def flaky(repo, *args, **kwargs):
            self.git_calls.append(list(args))
            if args and args[0] == "push":
                state["attempts"] += 1
                if state["attempts"] == 1:
                    self._advance_origin_prod()
                    return subprocess.CompletedProcess(
                        args, 1, "",
                        "! [rejected] (non-fast-forward)\nerror: failed to push some refs to origin")
            return real_git(repo, *args, **kwargs)

        self._patch("_git", flaky)
        pushed, _to_sha, log = self._push(attempts=2)

        self.assertTrue(pushed, log)
        self.assertEqual(2, state["attempts"], "the rejected push must be retried once")
        self.assertIn("prod moved under us", self._origin_log())
        self.assertIn("staged work", self._origin_log())
        self.assertEqual([], self.failed)

    def test_exhausted_retries_record_a_push_failure(self):
        self._stage_commit()
        real_git = release_train._git

        def always_rejected(repo, *args, **kwargs):
            self.git_calls.append(list(args))
            if args and args[0] == "push":
                return subprocess.CompletedProcess(
                    args, 1, "", "! [rejected] (fetch first)\nerror: failed to push some refs")
            return real_git(repo, *args, **kwargs)

        self._patch("_git", always_rejected)
        pushed, _to_sha, log = self._push(attempts=2)

        self.assertFalse(pushed)
        self.assertIn("rejected", log)
        self.assertTrue(any(f["gate"] == "push" for f in self.failed))


class NonFastForwardDetectionTest(unittest.TestCase):
    def test_recognises_the_rejection_signatures(self):
        for text in ("! [rejected] main -> main (non-fast-forward)",
                     "hint: Updates were rejected because the tip of your current branch is behind",
                     "error: failed to push some refs to 'https://github.com/x/y.git'",
                     "hint: (e.g. 'git pull ...') before pushing again. fetch first"):
            result = subprocess.CompletedProcess([], 1, "", text)
            self.assertTrue(release_train._is_non_fast_forward(result), text)

    def test_does_not_misread_unrelated_failures(self):
        result = subprocess.CompletedProcess(
            [], 128, "", "fatal: could not read from remote repository")
        self.assertFalse(release_train._is_non_fast_forward(result))


class ProductionBuildProofTest(unittest.TestCase):
    def test_records_the_exact_kind_and_command_consumed_by_push_guard(self):
        import build_gate
        import proof_graph
        from unittest.mock import patch

        with patch.object(build_gate, "detect_build_cmd", return_value="npm run build"), \
             patch.object(proof_graph, "record_verification") as record, \
             patch.object(proof_graph, "reusable_verification", return_value={"success": True}) as read:
            ok, note = release_train._persist_production_build_proof(
                "/repo", "a" * 40, "npm run build")

        self.assertTrue(ok, note)
        record.assert_called_once_with("/repo", "a" * 40, "npm run build", "build", True)
        read.assert_called_once_with("/repo", "a" * 40, "npm run build", "build")

    def test_does_not_certify_a_different_command_than_the_one_built(self):
        import build_gate
        from unittest.mock import patch

        with patch.object(build_gate, "detect_build_cmd", return_value="npm run build"):
            ok, note = release_train._persist_production_build_proof(
                "/repo", "a" * 40, "npm run typecheck")

        self.assertFalse(ok)
        self.assertIn("refusing to certify", note)


class WithdrawUnreleasedMergedTest(unittest.TestCase):
    """A failed push must not leave tasks claiming MERGED for commits nobody can see."""

    def setUp(self):
        self.saved_db = release_train.db
        self.addCleanup(setattr, release_train, "db", self.saved_db)

    def test_merged_is_withdrawn_when_the_commit_is_not_on_origin_prod(self):
        db = _FakeDB(tasks=[{"id": "t1", "slug": "reachable", "artifact_commit": "aaa"},
                            {"id": "t2", "slug": "stranded", "artifact_commit": "bbb"},
                            {"id": "t3", "slug": "no-artifact", "artifact_commit": ""}])
        release_train.db = db
        saved_git = release_train._git

        def fake_git(repo, *args, **kwargs):
            if args[:2] == ("rev-parse", "--verify"):
                return subprocess.CompletedProcess(args, 0, "sha\n", "")
            if args[0] == "merge-base":
                reachable = args[2] == "aaa"
                return subprocess.CompletedProcess(args, 0 if reachable else 1, "", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        release_train._git = fake_git
        self.addCleanup(setattr, release_train, "_git", saved_git)

        import merge_train
        from unittest.mock import patch
        with patch.object(merge_train, "ensure_integration_card_result",
                          return_value=merge_train.CARD_CREATED) as ensure:
            withdrawn = release_train._withdraw_unreleased_merged(
                {"id": "proj-1"}, "demo", "/repo", "master", "push rejected")

        self.assertEqual(["stranded"], withdrawn)
        self.assertEqual(1, len(db.updated))
        _table, match, values = db.updated[0]
        self.assertEqual({"id": "t2"}, match)
        self.assertEqual("DONE", values["state"])
        self.assertIn("not on origin/master", values["note"])
        ensure.assert_called_once()
        self.assertEqual("stranded", ensure.call_args.args[1])


class NoForcePushToProductionTest(unittest.TestCase):
    """Forcing a production branch would discard whatever advanced it. Never do it."""

    @staticmethod
    def _force_push_offenders(path):
        """Flag only real arguments — quoted literals — not prose about forcing."""
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        literals = ('"--force-with-lease"', "'--force-with-lease'", '"--force"', "'--force'")
        offenders = []
        for i, line in enumerate(lines, 1):
            if not any(lit in line for lit in literals):
                continue
            # `worktree remove --force` is unrelated to pushing.
            if "worktree" in line:
                continue
            offenders.append((i, line.strip()))
        return offenders

    def test_release_train_contains_no_force_push(self):
        path = os.path.join(os.path.dirname(__file__), "..", "release_train.py")
        offenders = self._force_push_offenders(path)
        self.assertEqual([], offenders,
                         f"force push against a production branch: {offenders}")

    def test_merge_train_contains_no_force_push(self):
        path = os.path.join(os.path.dirname(__file__), "..", "merge_train.py")
        if not os.path.isfile(path):
            self.skipTest("merge_train.py not present")
        offenders = self._force_push_offenders(path)
        self.assertEqual([], offenders, f"force push in merge_train: {offenders}")


if __name__ == "__main__":
    unittest.main()
