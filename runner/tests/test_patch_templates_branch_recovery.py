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


if __name__ == "__main__":
    unittest.main()
