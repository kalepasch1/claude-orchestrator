#!/usr/bin/env python3
"""Integration tests: patch_templates.pre_claim_hook invokes branch recovery
when a task's branch is missing, and leaves existing behaviour unchanged.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import patch_templates as pt
import patch_recovery as pr
import branch_recovery as br

SLUG = "fix-widget-border"
REPO = "/fake/repo"
BASE = "main"

TASK = {
    "id": "task-1",
    "slug": SLUG,
    "project_id": "proj-1",
    "prompt": "Fix widget border radius to match design spec",
}

PROJECT_ROW = {
    "id": "proj-1",
    "name": "my-project",
    "repo_path": REPO,
    "default_base": BASE,
}


def _proc(returncode=0, stdout="", stderr=""):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# _ensure_branch
# ---------------------------------------------------------------------------

class EnsureBranchSkipTest(unittest.TestCase):
    def test_no_slug_is_noop(self):
        task = {**TASK, "slug": ""}
        with patch.object(pt, "_get_project") as gp, \
             patch("patch_recovery.detect_branch") as db_:
            pt._ensure_branch(task)
        gp.assert_not_called()
        db_.assert_not_called()

    def test_no_repo_path_is_noop(self):
        with patch.object(pt, "_get_project", return_value={"repo_path": ""}), \
             patch("patch_recovery.detect_branch") as db_:
            pt._ensure_branch(TASK)
        db_.assert_not_called()

    def test_repo_dir_not_on_disk_is_noop(self):
        with patch.object(pt, "_get_project", return_value={"repo_path": "/nonexistent"}), \
             patch("os.path.isdir", return_value=False), \
             patch("patch_recovery.detect_branch") as db_:
            pt._ensure_branch(TASK)
        db_.assert_not_called()


class EnsureBranchFoundTest(unittest.TestCase):
    def test_branch_already_present_no_recovery_called(self):
        detection = {"found": True, "location": "local", "branch": f"agent/{SLUG}", "path": None}
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", return_value=detection), \
             patch("patch_recovery.recover") as rec, \
             patch("patch_recovery.regenerate_from_intent") as regen:
            pt._ensure_branch(TASK)
        rec.assert_not_called()
        regen.assert_not_called()


class EnsureBranchMissingRecoveryTest(unittest.TestCase):
    """Branch missing → recover() is tried first."""

    _detection = {"found": False, "location": None, "branch": f"agent/{SLUG}", "path": None}

    def test_recover_called_with_correct_args(self):
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", return_value=self._detection), \
             patch("patch_recovery.recover",
                   return_value={"ok": True, "method": "patch_replay",
                                 "branch": f"agent/{SLUG}"}) as rec, \
             patch("patch_recovery.regenerate_from_intent") as regen:
            pt._ensure_branch(TASK)
        rec.assert_called_once_with(REPO, SLUG, BASE, project="proj-1")
        regen.assert_not_called()

    def test_recover_success_stops_pipeline(self):
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", return_value=self._detection), \
             patch("patch_recovery.recover",
                   return_value={"ok": True, "method": "reflog",
                                 "branch": f"agent/{SLUG}"}), \
             patch("patch_recovery.regenerate_from_intent") as regen:
            pt._ensure_branch(TASK)
        regen.assert_not_called()

    def test_recover_failure_triggers_regenerate(self):
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", return_value=self._detection), \
             patch("patch_recovery.recover",
                   return_value={"ok": False, "method": "none",
                                 "reason": "all methods exhausted"}), \
             patch("patch_recovery.regenerate_from_intent",
                   return_value={"ok": True, "method": "cache_replay",
                                 "branch": f"agent/{SLUG}"}) as regen:
            pt._ensure_branch(TASK)
        regen.assert_called_once()

    def test_regenerate_called_with_template_id_and_intent(self):
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", return_value=self._detection), \
             patch("patch_recovery.recover",
                   return_value={"ok": False, "method": "none", "reason": "nothing"}), \
             patch("patch_recovery.regenerate_from_intent",
                   return_value={"ok": True, "method": "intent_stub",
                                 "branch": f"agent/{SLUG}"}) as regen:
            pt._ensure_branch(TASK)
        args, kwargs = regen.call_args
        repo_arg, slug_arg, base_arg, words_arg = args
        self.assertEqual(repo_arg, REPO)
        self.assertEqual(slug_arg, SLUG)
        self.assertEqual(base_arg, BASE)
        self.assertIsInstance(words_arg, list)
        self.assertIn("template_id", kwargs)

    def test_all_recovery_fails_does_not_raise(self):
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", return_value=self._detection), \
             patch("patch_recovery.recover",
                   return_value={"ok": False, "method": "none", "reason": "exhausted"}), \
             patch("patch_recovery.regenerate_from_intent",
                   return_value={"ok": False, "method": "failed", "reason": "no stub"}):
            pt._ensure_branch(TASK)  # must not raise

    def test_exception_in_patch_recovery_does_not_raise(self):
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", side_effect=RuntimeError("db error")):
            pt._ensure_branch(TASK)  # must not raise


# ---------------------------------------------------------------------------
# pre_claim_hook end-to-end: recovery is invoked when branch is missing
# ---------------------------------------------------------------------------

class PreClaimHookIntegrationTest(unittest.TestCase):
    """Verify that pre_claim_hook triggers branch recovery on a missing branch."""

    _detection_missing = {"found": False, "location": None,
                          "branch": f"agent/{SLUG}", "path": None}
    _detection_present = {"found": True, "location": "local",
                          "branch": f"agent/{SLUG}", "path": None}

    def test_missing_branch_recovered_then_template_injected(self):
        """End-to-end: missing branch → recover() called → template injected."""
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", return_value=self._detection_missing), \
             patch("patch_recovery.recover",
                   return_value={"ok": True, "method": "patch_replay",
                                 "branch": f"agent/{SLUG}"}) as rec, \
             patch("patch_recovery.regenerate_from_intent") as regen, \
             patch.object(pt, "db") as mdb:
            mdb.select.return_value = []
            mdb.update.return_value = None
            result = pt.pre_claim_hook(TASK)

        rec.assert_called_once()
        regen.assert_not_called()
        # Template should be injected
        self.assertIn("[patch-template:", result["prompt"])
        self.assertIn("Fix widget border radius", result["prompt"])

    def test_branch_present_no_recovery_called(self):
        """Existing branch: recovery not triggered, template still injected."""
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", return_value=self._detection_present), \
             patch("patch_recovery.recover") as rec, \
             patch("patch_recovery.regenerate_from_intent") as regen, \
             patch.object(pt, "db") as mdb:
            mdb.select.return_value = []
            mdb.update.return_value = None
            result = pt.pre_claim_hook(TASK)

        rec.assert_not_called()
        regen.assert_not_called()
        self.assertIn("[patch-template:", result["prompt"])

    def test_already_templated_task_returned_unchanged(self):
        """Task that already has [patch-template: skips recovery and templating."""
        existing = {**TASK, "prompt": "[patch-template:abc123]\nDo the thing"}
        with patch("patch_recovery.detect_branch") as db_, \
             patch("patch_recovery.recover") as rec:
            result = pt.pre_claim_hook(existing)

        db_.assert_not_called()
        rec.assert_not_called()
        self.assertEqual(result, existing)

    def test_recovery_fail_then_regenerate_still_produces_template(self):
        """Recovery fails, regeneration succeeds: template still produced."""
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", return_value=self._detection_missing), \
             patch("patch_recovery.recover",
                   return_value={"ok": False, "method": "none", "reason": "nothing"}), \
             patch("patch_recovery.regenerate_from_intent",
                   return_value={"ok": True, "method": "cache_replay",
                                 "branch": f"agent/{SLUG}"}) as regen, \
             patch.object(pt, "db") as mdb:
            mdb.select.return_value = []
            mdb.update.return_value = None
            result = pt.pre_claim_hook(TASK)

        regen.assert_called_once()
        self.assertIn("[patch-template:", result["prompt"])

    def test_recovery_fully_fails_task_still_returns_with_template(self):
        """Even when all recovery fails, the task is returned with template injected."""
        with patch.object(pt, "_get_project", return_value=PROJECT_ROW), \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", return_value=self._detection_missing), \
             patch("patch_recovery.recover",
                   return_value={"ok": False, "method": "none", "reason": "exhausted"}), \
             patch("patch_recovery.regenerate_from_intent",
                   return_value={"ok": False, "method": "failed", "reason": "no stub"}), \
             patch.object(pt, "db") as mdb:
            mdb.select.return_value = []
            mdb.update.return_value = None
            result = pt.pre_claim_hook(TASK)

        self.assertIn("[patch-template:", result["prompt"])
        self.assertIn("Fix widget border radius", result["prompt"])


# ---------------------------------------------------------------------------
# branch_recovery.recover_missing_branches — batch merge-train recovery
# ---------------------------------------------------------------------------

def _entries(n, repo="/fake/repo", project="beethoven"):
    return [{"slug": f"lost-{i}", "repo": repo, "base": "master",
             "project": project} for i in range(n)]


def _batch_patches(apply_result=None, recover_result=None,
                   exists=False, is_repo=True):
    """Common patch stack for batch tests; returns the context managers."""
    apply_result = apply_result or {"ok": True, "method": "library"}
    recover_result = recover_result or {"ok": False, "method": "none",
                                        "reason": "exhausted"}
    return [
        patch.object(br, "_is_git_repo", return_value=is_repo),
        patch.object(br, "_branch_exists_local", return_value=exists),
        patch.object(br, "_mark_task_state", return_value=True),
        patch("patch_recovery._apply_diff_to_branch",
              return_value=apply_result),
        patch("patch_recovery.recover", return_value=recover_result),
    ]


class RecoverMissingBranchesBatchTest(unittest.TestCase):
    """Acceptance: >=80% of 5+ synthetic missing branches end MERGED or
    QUARANTINED, and edge cases (empty, all-fail, existing, isolation)."""

    def _run(self, missing, library=None, patches=None, **kwargs):
        patches = patches if patches is not None else _batch_patches()
        with patches[0], patches[1], patches[2] as mark, patches[3], patches[4]:
            result = br.recover_missing_branches(missing, library, **kwargs)
        return result, mark

    def test_five_missing_branches_reach_terminal_state(self):
        missing = _entries(5)
        library = {f"lost-{i}": "diff --git a/f b/f\n+x" for i in range(5)}
        stats, mark = self._run(missing, library)
        self.assertEqual(stats["reviewed"], 5)
        terminal = stats["merged"] + stats["quarantined"]
        self.assertGreaterEqual(terminal / stats["reviewed"], 0.8)
        self.assertEqual(stats["merged"], 5)
        self.assertEqual(stats["skipped"], 0)
        self.assertEqual(mark.call_count, 5)
        for c in mark.call_args_list:
            self.assertEqual(c.args[1], "MERGED")

    def test_mixed_outcomes_still_meet_recovery_bar(self):
        """4 library hits apply, 1 has no library entry and recover() fails."""
        missing = _entries(5)
        library = {f"lost-{i}": "diff --git a/f b/f\n+x" for i in range(4)}
        stats, _ = self._run(missing, library)
        self.assertEqual(stats["merged"], 4)
        self.assertEqual(stats["quarantined"], 1)
        terminal = stats["merged"] + stats["quarantined"]
        self.assertGreaterEqual(terminal / stats["reviewed"], 0.8)

    def test_empty_list_returns_zero_stats(self):
        stats, mark = self._run([])
        self.assertEqual(
            {k: stats[k] for k in ("reviewed", "merged", "quarantined", "skipped")},
            {"reviewed": 0, "merged": 0, "quarantined": 0, "skipped": 0})
        mark.assert_not_called()

    def test_none_missing_is_noop(self):
        stats, _ = self._run(None)
        self.assertEqual(stats["reviewed"], 0)

    def test_all_fail_all_quarantined_no_raise(self):
        missing = _entries(6)
        library = {e["slug"]: "diff --git a/f b/f\n+x" for e in missing}
        patches = _batch_patches(
            apply_result={"ok": False, "method": "library", "reason": "apply failed"})
        stats, mark = self._run(missing, library, patches=patches)
        self.assertEqual(stats["quarantined"], 6)
        self.assertEqual(stats["merged"], 0)
        for c in mark.call_args_list:
            self.assertEqual(c.args[1], "QUARANTINED")

    def test_existing_branches_are_skipped(self):
        missing = _entries(3)
        patches = _batch_patches(exists=True)
        stats, mark = self._run(missing, patches=patches)
        self.assertEqual(stats["skipped"], 3)
        self.assertEqual(stats["merged"] + stats["quarantined"], 0)
        mark.assert_not_called()

    def test_other_project_entries_are_skipped(self):
        missing = _entries(2, project="beethoven") + _entries(2, project="pareto-2080")[0:2]
        for e in missing[2:]:
            e["slug"] += "-other"
        library = {e["slug"]: "diff --git a/f b/f\n+x" for e in missing}
        stats, _ = self._run(missing, library, project="beethoven")
        self.assertEqual(stats["merged"], 2)
        self.assertEqual(stats["skipped"], 2)

    def test_low_similarity_library_hit_falls_back_to_recover(self):
        missing = _entries(1)
        library = {"lost-0": {"diff": "diff --git a/f b/f\n+x", "similarity": 0.3}}
        recover_ok = {"ok": True, "method": "patch_replay", "branch": "agent/lost-0"}
        patches = _batch_patches(recover_result=recover_ok)
        with patches[0], patches[1], patches[2], \
             patches[3] as apply_mock, patches[4] as rec:
            stats = br.recover_missing_branches(missing, library, threshold=0.8)
        apply_mock.assert_not_called()
        rec.assert_called_once()
        self.assertEqual(stats["merged"], 1)

    def test_library_exception_is_fail_soft(self):
        def boom(_slug):
            raise RuntimeError("RPC infra outage")
        missing = _entries(2)
        stats, _ = self._run(missing, boom)  # recover() also fails -> quarantined
        self.assertEqual(stats["quarantined"], 2)

    def test_malformed_entries_are_skipped_not_raised(self):
        missing = ["just-a-string", {"repo": "/fake/repo"}, {"slug": "no-repo"}]
        stats, _ = self._run(missing)
        self.assertEqual(stats["skipped"], 3)

    def test_invalid_git_path_quarantines(self):
        missing = _entries(1)
        patches = _batch_patches(is_repo=False)
        stats, _ = self._run(missing, patches=patches)
        self.assertEqual(stats["quarantined"], 1)

    def test_focused_test_failure_quarantines_with_output(self):
        missing = _entries(1)
        missing[0]["test_cmd"] = ["pytest", "-x"]
        library = {"lost-0": "diff --git a/f b/f\n+x"}
        patches = _batch_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch.object(br, "_run_focused_tests",
                          return_value=(False, "1 failed")):
            stats = br.recover_missing_branches(missing, library)
        self.assertEqual(stats["quarantined"], 1)
        self.assertIn("1 failed", stats["details"][0]["reason"])

    def test_threshold_env_var_is_respected(self):
        missing = _entries(1)
        library = {"lost-0": {"diff": "diff --git a/f b/f\n+x", "similarity": 0.5}}
        patches = _batch_patches()
        with patch.dict(os.environ,
                        {"ORCH_MISSING_BRANCH_RECOVERY_THRESHOLD": "0.4"}), \
             patches[0], patches[1], patches[2], patches[3] as apply_mock, patches[4]:
            stats = br.recover_missing_branches(missing, library)
        apply_mock.assert_called_once()
        self.assertEqual(stats["merged"], 1)

    def test_db_mark_failure_does_not_abort_loop(self):
        missing = _entries(3)
        library = {e["slug"]: "diff --git a/f b/f\n+x" for e in missing}
        patches = _batch_patches()
        with patches[0], patches[1], patches[3], patches[4], \
             patch("db.update", side_effect=RuntimeError("db down")):
            stats = br.recover_missing_branches(missing, library)
        self.assertEqual(stats["merged"], 3)


if __name__ == "__main__":
    unittest.main()
