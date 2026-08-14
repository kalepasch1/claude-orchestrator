#!/usr/bin/env python3
"""Slicing a prompt with no implementation intent manufactures garbage.

Regression suite for backlog-batch-beethoven-18fa8e4 (2026-08-06). That parent prompt
was 100% retrieval scaffolding — PATCH TEMPLATE + hex, an "Intent:" token soup, SOURCE
similarity lines, an ORCHESTRATION PIPELINE CONTRACT block, and generic advice. It
tripped should_slice() on length alone and was cut into five children that were not
tasks: slice-3's entire prompt was "Locate the existing owner module/function before
adding new files." and slice-4's began "- 2.". One unworkable task became five, each
burning its own attempts and agentic-repair cycles.

The prompts below are verbatim shapes from that task family, not invented examples.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import task_slicer


# Verbatim shape of backlog-batch-beethoven-18fa8e4-slice-1's prompt.
SCAFFOLD_ONLY = """\
- PATCH TEMPLATE b28aba37e6cd
Intent: 0343183 056af630dd5f 07062319 07190257 148d45efebad 1565ms 170834ms 20251001
Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.
- 3.
- project: beethoven
- SOURCE: beethoven/deployfix-beethoven-07190257
SUMMARY: ## ORCHESTRATION PIPELINE CONTRACT
- strategy planner: google:gemini-2.5-flash (qpd leader q=6.6 $0.0 (n=1))
- preflight triage: local:kimi-k2.7-code:cloud (qpd leader q=7.62 $0.0 (n=57))
- learned route: pipeline_scout -> deepseek:deepseek-v4-flash, q=4.4
- Reuse matching project helpers and naming conventions.
- Implementation slots: 1.
- Add or update the narrowest test/check that proves the requested behavior.
- Preflight scope concern: None determinable.
"""

# A real task: long and bulleted, but every line says something specific.
REAL_INTENT = """\
Un-pause batch_fusion in runner/batch_fusion.py so that queued mechanical tasks are
actually grouped instead of merely counted.
- Raise the batch ceiling from 5 to 10 and add a target floor of 5 per session.
- Group strictly by project_id; a batch must never span two repositories.
- Mechanical kinds should fuse on co-location alone rather than requiring a non-empty
  file-set overlap for every pair, which is what made fusion inert in practice.
- Split evenly so eleven tasks become six and five rather than ten and one.
- Keep drain_mode semantics for the speculative generators exactly as they are.
- Fail soft: a malformed queue row must cost a tick, never the whole scheduler.
"""


def _task(prompt, slug="backlog-batch-beethoven-18fa8e4", note="", kind="build"):
    return {"id": "abc123", "slug": slug, "prompt": prompt, "note": note,
            "kind": kind, "project_id": "p1", "base_branch": "master"}


class HasImplementationIntentTest(unittest.TestCase):
    def test_scaffolding_only_prompt_has_no_intent(self):
        self.assertFalse(task_slicer.has_implementation_intent(SCAFFOLD_ONLY))

    def test_real_prompt_has_intent(self):
        self.assertTrue(task_slicer.has_implementation_intent(REAL_INTENT))

    def test_empty_and_none_are_safe(self):
        for value in ("", None, "   \n\n  "):
            self.assertFalse(task_slicer.has_implementation_intent(value))

    def test_intent_token_soup_is_not_mistaken_for_prose(self):
        soup = ("Intent: 07062319 07071626 acceptance adapt agentic alter analysis "
                "artifacts because beethoven before behavior below blocks branch broad")
        self.assertFalse(task_slicer.has_implementation_intent(soup))

    def test_bare_enumerators_contribute_nothing(self):
        self.assertFalse(task_slicer.has_implementation_intent("- 2.\n3.\n- 4.\n"))

    def test_generic_advice_contributes_nothing(self):
        advice = "\n".join([
            "- Preserve existing behavior, make the smallest mergeable diff.",
            "- Locate the existing owner module/function before adding new files.",
            "- Reuse matching project helpers and naming conventions.",
            "- Add or update the narrowest test/check that proves the requested behavior.",
        ])
        self.assertFalse(task_slicer.has_implementation_intent(advice))

    def test_has_any_intent_accepts_a_terse_but_specific_prompt(self):
        # The weaker gate used for model-authored slices must not impose a length floor.
        self.assertTrue(task_slicer.has_any_intent("Add a --dry-run flag to runner/janitor.py."))
        self.assertFalse(task_slicer.has_any_intent("Acceptance: preserve existing behavior"))


class ShouldSliceTest(unittest.TestCase):
    def test_refuses_to_slice_a_scaffolding_only_prompt(self):
        # Long enough and bulleted enough to have tripped the old length/bullet heuristic.
        prompt = SCAFFOLD_ONLY * 4
        self.assertGreaterEqual(prompt.count("\n- "), 6)
        self.assertFalse(task_slicer.should_slice(_task(prompt)))

    def test_still_slices_a_genuinely_long_real_task(self):
        prompt = REAL_INTENT + "\n" + REAL_INTENT
        self.assertTrue(task_slicer.should_slice(_task(prompt)))

    def test_existing_guards_unchanged(self):
        self.assertFalse(task_slicer.should_slice(_task(REAL_INTENT * 3, note="auto-sliced-before-agent: x")))
        self.assertFalse(task_slicer.should_slice(_task(REAL_INTENT * 3, slug="qafix-something")))
        self.assertFalse(task_slicer.should_slice(_task(REAL_INTENT * 3, slug="parent-slice-1")))
        self.assertFalse(task_slicer.should_slice("not-a-dict"))

    def test_short_real_prompt_is_still_not_sliced(self):
        self.assertFalse(task_slicer.should_slice(_task("Fix the typo in README.md.")))


class SliceTaskTest(unittest.TestCase):
    def test_scaffolding_only_prompt_yields_no_slices(self):
        # The exact failure: five children, none of them a task.
        self.assertEqual(task_slicer.slice_task(_task(SCAFFOLD_ONLY * 4)), [])

    def test_chunks_are_contiguous_not_round_robin(self):
        # Round-robin put step 1 in slice-1 and step 2 in slice-2, each without the
        # other's context. Contiguous blocks preserve the authored order.
        prompt = "\n".join(f"- Step {i}: edit runner/module_{i}.py and update its test."
                           for i in range(1, 11))
        parts = task_slicer.slice_task(_task(prompt))
        self.assertGreaterEqual(len(parts), 2)
        first = parts[0]["prompt"]
        self.assertIn("Step 1", first)
        self.assertIn("Step 2", first)
        self.assertNotIn("Step 10", first)

    def test_every_chunk_lands_exactly_once(self):
        prompt = "\n".join(f"- Step {i}: edit runner/module_{i}.py and update its test."
                           for i in range(1, 11))
        parts = task_slicer.slice_task(_task(prompt))
        joined = "\n".join(p["prompt"] for p in parts)
        for i in range(1, 11):
            self.assertEqual(joined.count(f"Step {i}:"), 1, f"Step {i} duplicated or lost")

    def test_slices_are_numbered_without_gaps(self):
        prompt = "\n".join(f"- Step {i}: edit runner/module_{i}.py and update its test."
                           for i in range(1, 11))
        parts = task_slicer.slice_task(_task(prompt))
        expected = [f"backlog-batch-beethoven-18fa8e4-slice-{i + 1}" for i in range(len(parts))]
        self.assertEqual([p["slug"] for p in parts], expected)

    def test_deps_chain_sequentially(self):
        prompt = "\n".join(f"- Step {i}: edit runner/module_{i}.py and update its test."
                           for i in range(1, 11))
        parts = task_slicer.slice_task(_task(prompt))
        self.assertEqual(parts[0]["deps"], [])
        for prev, cur in zip(parts, parts[1:]):
            self.assertEqual(cur["deps"], [prev["slug"]])

    def test_boilerplate_groups_are_dropped_from_a_mixed_prompt(self):
        mixed = REAL_INTENT + "\n" + SCAFFOLD_ONLY
        parts = task_slicer.slice_task(_task(mixed))
        self.assertTrue(parts)
        for part in parts:
            self.assertTrue(task_slicer.has_any_intent(part["prompt"]),
                            f"boilerplate-only slice inserted: {part['prompt'][:80]!r}")

    def test_small_but_real_steps_are_never_discarded(self):
        # The per-group gate must not silently drop requested work just for being terse.
        prompt = "\n".join(f"- Step {i}: edit runner/module_{i}.py." for i in range(1, 11))
        joined = "\n".join(p["prompt"] for p in task_slicer.slice_task(_task(prompt)))
        for i in range(1, 11):
            self.assertIn(f"Step {i}:", joined)

    def test_single_surviving_group_is_not_a_decomposition(self):
        # One real sentence plus pure scaffolding must run whole, not as a 1-child "split".
        parts = task_slicer.slice_task(_task(
            "Add commits_behind to the runner heartbeat payload.\n" + SCAFFOLD_ONLY))
        self.assertNotEqual(len(parts), 1)

    def test_never_exceeds_max_parts(self):
        prompt = "\n".join(f"- Step {i}: edit runner/module_{i}.py and update its test."
                           for i in range(1, 41))
        parts = task_slicer.slice_task(_task(prompt))
        self.assertLessEqual(len(parts), task_slicer.MAX_PARTS)


class PreAgentHookTest(unittest.TestCase):
    def test_hook_declines_a_scaffolding_only_task_without_touching_the_db(self):
        # No db stub is installed: if the hook tried to write, this would raise.
        self.assertFalse(task_slicer.pre_agent_hook(_task(SCAFFOLD_ONLY * 4)))


if __name__ == "__main__":
    unittest.main()
