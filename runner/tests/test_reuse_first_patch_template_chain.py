#!/usr/bin/env python3
"""The narrowest test of the reuse-first / patch-template chain.

Behaviour under test — one sentence
-----------------------------------
When a solved implementation already exists, the prompt the coder finally sees
must name it ("REUSE FIRST … SOURCE: <project>/<slug>") *and* carry the patch
template with its `[patch-template:<id>]` marker, with the operator's original
request still intact underneath — and running the chain again must change
nothing.

Why this and not another unit test
----------------------------------
`reuse_first`, `merged_diff_library` and `patch_templates` each have thorough
unit coverage. What nothing covered is their **composition**, which is the only
thing the slice-2 patch template actually asserts. `runner.py` calls them in a
fixed order:

    reuse_first.pre_claim_hook  →  patch_transplant.pre_claim_hook  →  patch_templates.pre_claim_hook

Both the first and the last stage prepend to `task["prompt"]` and each guards on
its own marker. Nothing verified that the second prepend preserves the first, or
that a replay is idempotent — and a replay is the normal case, because a
requeued task is re-hooked on every claim.

The chain also has one asymmetry worth pinning: `reuse_first` persists its
rewrite with `db.update`, `patch_templates` deliberately does not (the
2026-07-11 fix that stopped prompts being permanently corrupted). If the
template stage ever started writing back, the stored prompt would accumulate a
template per claim. That is asserted here too.

Pass/fail is unambiguous: every assertion is an exact substring or count.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import patch_templates
import reuse_first

ORIGINAL_PROMPT = "Implement the compounding codegen platform spine pipeline structure."
PRIOR = {
    "project": "smarter",
    "source_slug": "cont-1042d0",
    "summary": "continuation compactor reuse for session windows",
    "similarity": 0.41,
}


def _task():
    return {"id": "task-1", "slug": "wave-c-slice-2", "project_id": "beethoven",
            "kind": "build", "prompt": ORIGINAL_PROMPT}


class TestReuseFirstPatchTemplateChain(unittest.TestCase):
    """The two prompt-rewriting hooks must compose, not clobber."""

    def _run_chain(self, task, db_updates):
        """Run the two prompt-rewriting stages in runner.py's order."""

        def fake_update(table, where, values):
            db_updates.append((table, where, values))
            return True

        with patch.object(reuse_first, "find_reusable", return_value=PRIOR), \
             patch.object(reuse_first.db, "update", side_effect=fake_update), \
             patch.object(reuse_first.db, "insert", return_value=True), \
             patch.object(patch_templates, "_store", return_value=None):
            task = reuse_first.pre_claim_hook(task)
            task = patch_templates.pre_claim_hook(task)
        return task

    def test_final_prompt_carries_reuse_pointer_template_and_original_request(self):
        updates = []
        result = self._run_chain(_task(), updates)
        prompt = result["prompt"]

        # 1. the prior solution is named, so the coder adapts instead of rebuilding
        self.assertIn("REUSE FIRST", prompt)
        self.assertIn("SOURCE: smarter/cont-1042d0", prompt)
        # 2. the patch template survived the second prepend, marker included
        self.assertIn("PATCH TEMPLATE", prompt)
        self.assertIn(patch_templates.MARK, prompt)
        # 3. the operator's actual request is still there
        self.assertIn(ORIGINAL_PROMPT, prompt)

    def test_each_directive_appears_exactly_once(self):
        result = self._run_chain(_task(), [])
        prompt = result["prompt"]
        self.assertEqual(prompt.count("REUSE FIRST"), 1)
        self.assertEqual(prompt.count(patch_templates.MARK), 1)
        self.assertEqual(prompt.count(ORIGINAL_PROMPT), 1)

    def test_replaying_the_chain_is_idempotent(self):
        once = self._run_chain(_task(), [])
        twice = self._run_chain(dict(once), [])
        self.assertEqual(once["prompt"], twice["prompt"])

    def test_template_stage_never_writes_the_prompt_back_to_the_db(self):
        """Regression guard for the 2026-07-11 prompt-corruption fix."""
        updates = []
        self._run_chain(_task(), updates)
        # reuse_first persists its rewrite; the template stage must not.
        self.assertEqual(len(updates), 1)
        table, _where, values = updates[0]
        self.assertEqual(table, "tasks")
        self.assertNotIn(patch_templates.MARK, str(values.get("prompt", "")))

    def test_chain_is_a_no_op_when_no_prior_solution_matches(self):
        with patch.object(reuse_first, "find_reusable", return_value=None), \
             patch.object(patch_templates, "_store", return_value=None):
            task = reuse_first.pre_claim_hook(_task())
            task = patch_templates.pre_claim_hook(task)
        self.assertNotIn("REUSE FIRST", task["prompt"])
        self.assertIn("PATCH TEMPLATE", task["prompt"])
        self.assertIn(ORIGINAL_PROMPT, task["prompt"])


if __name__ == "__main__":
    unittest.main()
