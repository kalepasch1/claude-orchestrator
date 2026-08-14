#!/usr/bin/env python3
"""Acceptance test for patch template 918597e30434 (branch-recovery template).

WHAT THE TEMPLATE ACTUALLY SAYS
-------------------------------
Resolved from the `knowledge` store, its readable intent is:

    "Recover tested-but-not-integrated work whose agent branch is missing.
     Goal: recreate the smallest equivalent patch, commit it on
     agent/<slug>, run the project build/tests, and let the canonical merge
     train integrate it."

Its `Intent:` line is a sorted bag of tokens and hex hashes, so the only
behaviour this template asserts is the recovery contract above. This test
therefore validates the NARROWEST aspect of that contract that the existing
suite does not already pin, and nothing more.

WHAT IS ALREADY COVERED (deliberately not repeated here)
--------------------------------------------------------
- `tests/test_patch_templates_branch_recovery.py` covers the pre_claim_hook ->
  branch_recovery orchestration (29 cases).
- `tests/test_template_95fc17a.py` covers `lookup()`'s fail-soft contract.

WHAT THIS PINS
--------------
The seam between them, which nothing owns today: a RECOVERY template must be
round-trippable by id, and `pre_claim_hook` must preserve existing behaviour
while doing it — specifically that it never mutates the caller's task, never
raises, and never double-templates a task that already carries a marker. A
recovery template that cannot be resolved back from its id is a recovery
instruction the recovery flow cannot read, which is the failure mode this
template family exists to prevent.

Registered in tests/PATCH_TEMPLATE_REGISTRY.md.
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import patch_templates as pt  # noqa: E402

TID = "918597e30434"

#: The template's own readable intent, verbatim from the knowledge store.
RECOVERY_INTENT = (
    "Recover tested-but-not-integrated work whose agent branch is missing.\n"
    "Goal: recreate the smallest equivalent patch, commit it on "
    "agent/recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2, "
    "run the project build/tests, and let the canonical merge train integrate it."
)

RECOVERY_TASK = {
    "id": "task-918597",
    "slug": "dropbox-beethoven-audit-addendum-two-session-recon-slice-5",
    "project_id": "beethoven",
    "prompt": "Recover tested-but-not-integrated work whose agent branch is missing.",
}


def _jsonl(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write((row if isinstance(row, str) else json.dumps(row)) + "\n")


class TemplateIsResolvableById(unittest.TestCase):
    """A recovery instruction the recovery flow cannot read is not an instruction."""

    def test_template_resolves_from_the_local_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, [{"ts": 1.0, "template_id": TID,
                           "body": f"PATCH TEMPLATE {TID}\n{RECOVERY_INTENT}"}])
            with patch.object(pt, "_fallback_path", return_value=path):
                row = pt.lookup(TID)
        self.assertEqual(row.get("template_id"), TID)
        self.assertIn("agent/recover-missing-branch", row.get("body", ""),
                      "a recovery template must name the branch to commit on")

    def test_template_resolves_from_the_knowledge_table(self):
        body = f"PATCH TEMPLATE {TID}\n{RECOVERY_INTENT}"
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", return_value=[{"title": "t", "body": body}]):
                row = pt.lookup(TID)
        self.assertEqual(row.get("template_id"), TID)

    def test_duplicate_knowledge_rows_resolve_to_one_template(self):
        # The live store holds this template five times over; lookup must still
        # return a single row rather than a list or the last-write-wins junk.
        body = f"PATCH TEMPLATE {TID}\n{RECOVERY_INTENT}"
        rows = [{"title": "t", "body": body} for _ in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", return_value=rows):
                row = pt.lookup(TID)
        self.assertIsInstance(row, dict)
        self.assertEqual(row.get("template_id"), TID)

    def test_a_body_that_does_not_carry_the_id_is_not_a_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", return_value=[{"body": "some other template"}]):
                self.assertEqual(pt.lookup(TID), {})

    def test_unknown_id_is_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", side_effect=Exception("db down")):
                self.assertEqual(pt.lookup(TID), {})


class PreClaimHookPreservesExistingBehaviour(unittest.TestCase):
    """The task's explicit requirement: preserve existing behavior."""

    def _hook(self, task):
        """Run the hook with all side-effecting collaborators stubbed out."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            with patch.object(pt, "_fallback_path", return_value=path), \
                 patch.object(pt, "_ensure_branch", return_value=None), \
                 patch.object(pt.db, "insert", side_effect=Exception("db down")), \
                 patch.object(pt.db, "select", side_effect=Exception("db down")):
                return pt.pre_claim_hook(task)

    def test_the_callers_task_dict_is_never_mutated(self):
        task = copy.deepcopy(RECOVERY_TASK)
        before = copy.deepcopy(task)
        self._hook(task)
        self.assertEqual(task, before,
                         "pre_claim_hook must return a new dict, not edit the caller's")

    def test_the_original_prompt_is_preserved_inside_the_templated_prompt(self):
        out = self._hook(copy.deepcopy(RECOVERY_TASK))
        self.assertIn(RECOVERY_TASK["prompt"], out["prompt"],
                      "templating must not discard the original request")

    def test_the_templated_prompt_carries_a_resolvable_marker(self):
        out = self._hook(copy.deepcopy(RECOVERY_TASK))
        self.assertIn(pt.MARK, out["prompt"])

    def test_an_already_templated_task_is_returned_unchanged(self):
        task = copy.deepcopy(RECOVERY_TASK)
        task["prompt"] = f"{pt.MARK}{TID}]\n\noriginal request"
        self.assertEqual(self._hook(task), task, "double-templating must be a no-op")

    def test_hook_never_raises_when_every_collaborator_fails(self):
        task = copy.deepcopy(RECOVERY_TASK)
        with patch.object(pt, "_ensure_branch", side_effect=Exception("git gone")), \
             patch.object(pt, "build", side_effect=Exception("build gone")):
            self.assertEqual(pt.pre_claim_hook(task), task,
                             "on failure the hook returns the task untouched")

    def test_a_non_dict_task_is_returned_untouched(self):
        for junk in (None, "task", 42, []):
            self.assertEqual(pt.pre_claim_hook(junk), junk)


class TemplateIdInvariants(unittest.TestCase):
    def test_ids_are_stable_12_hex(self):
        tid1 = pt._id(copy.deepcopy(RECOVERY_TASK))
        tid2 = pt._id(copy.deepcopy(RECOVERY_TASK))
        self.assertEqual(tid1, tid2, "the same task must always hash to the same id")
        self.assertRegex(tid1, r"^[0-9a-f]{12}$")
        self.assertRegex(TID, r"^[0-9a-f]{12}$")

    def test_a_built_template_body_leads_with_its_own_id(self):
        tid, body = pt.build(copy.deepcopy(RECOVERY_TASK))
        self.assertTrue(body.startswith(f"PATCH TEMPLATE {tid}"),
                        "lookup()'s DB path matches on the id appearing in the body")


if __name__ == "__main__":
    unittest.main(verbosity=2)
