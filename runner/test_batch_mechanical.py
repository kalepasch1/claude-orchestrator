#!/usr/bin/env python3
"""Tests for batch_mechanical.py - mechanical task batching optimization.

Regression: Cold-start overhead on cheap tasks defeats budget. Batching independent
mechanical tasks (lint, format, rename, doc) in one pass reduces wasted model warmup.
Tests verify safety rules: no dependencies, no dependers, same project, mechanical-only.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import batch_mechanical as bm


def _mechanical_tasks(count, project="proj-1"):
    """COUNT queued mechanical tasks in one project, ready for find_batches().

    Prompts alternate between two genuinely mechanical phrasings so
    model_router.MECHANICAL matches every one of them; anything it does not match is
    filtered out before grouping and the batch silently comes up short.
    """
    phrasings = [("lint", "lint code"), ("format", "format code")]
    tasks = []
    for index in range(count):
        prefix, prompt = phrasings[index % len(phrasings)]
        tasks.append({"id": index + 1, "slug": f"{prefix}-{index + 1}",
                      "project_id": project, "prompt": prompt, "deps": [],
                      "state": "QUEUED", "kind": "mechanical", "base_branch": "main"})
    return tasks


class MechanicalClassificationTests(unittest.TestCase):
    """Tests for _is_mechanical(prompt) - must correctly identify mechanical work."""

    def test_rename_task_is_mechanical(self):
        """Rename tasks are mechanical."""
        self.assertTrue(bm._is_mechanical("rename all Color to Palette"))
        self.assertTrue(bm._is_mechanical("Rename UserID -> UserId for consistency"))

    def test_format_and_lint_tasks_are_mechanical(self):
        """Format/lint are classic mechanical work."""
        self.assertTrue(bm._is_mechanical("format the imports in src/"))
        self.assertTrue(bm._is_mechanical("run prettier on the CSS"))
        self.assertTrue(bm._is_mechanical("lint the TypeScript for unused vars"))

    def test_dark_mode_and_theme_are_mechanical(self):
        """UI polish work (theme, palette, dark mode) is mechanical."""
        self.assertTrue(bm._is_mechanical("convert remaining light styles to dark palette"))
        self.assertTrue(bm._is_mechanical("update the tailwind theme colors"))
        self.assertTrue(bm._is_mechanical("Apply tailwind theme updates"))

    def test_doc_and_comment_work_is_mechanical(self):
        """Documentation and comment cleanup is mechanical."""
        self.assertTrue(bm._is_mechanical("add docstring comments to functions"))
        self.assertTrue(bm._is_mechanical("add comments to error handling"))
        self.assertTrue(bm._is_mechanical("update changelog for v1.2.0 release"))

    def test_plural_and_verb_forms_of_the_keywords_match(self):
        """The keywords were singular-only, which \b makes exact.

        `\\bcomment\\b` does not match "comments" and `\\btypo\\b` does not match
        "typos" -- so "add comments to error handling" and "fix typos in the readme",
        the ordinary way people write these chores, matched nothing. Genuinely
        mechanical work was then neither routed to the cheap tier nor picked up for
        batching. Under-classifying is the safe direction, which is why it survived;
        it was still the rule failing on the most common spelling of its own words.
        """
        for prompt in ("add comments to error handling",
                       "fix typos in the readme",
                       "rename the columns",
                       "renaming the payment fields",
                       "update the docstrings",
                       "formatting the config files"):
            self.assertTrue(bm._is_mechanical(prompt), prompt)

    def test_the_wider_keywords_do_not_swallow_substantive_work(self):
        """Explicit suffixes, not \\w* -- "commentary" is not a comment chore."""
        for prompt in ("write commentary on the distributed ledger design",
                       "refactor the settlement protocol",
                       "design a novel consensus algorithm"):
            self.assertFalse(bm._is_mechanical(prompt), prompt)

    def test_version_bump_is_mechanical(self):
        """Dependency and version management is mechanical."""
        self.assertTrue(bm._is_mechanical("bump version to 2.1.0"))
        self.assertTrue(bm._is_mechanical("remove duplicate imports in test files"))

    def test_long_prompt_fails_mechanical_classification(self):
        """Prompts longer than MECH_MAX_PROMPT are never mechanical (feature work is long)."""
        long_prompt = "x" * (bm.MECH_MAX_PROMPT + 1)
        self.assertFalse(bm._is_mechanical(long_prompt))

    def test_heavy_signal_overrides_mechanical_keyword(self):
        """A heavy keyword disqualifies mechanical classification."""
        self.assertFalse(bm._is_mechanical(
            "rename the payment schema to support distributed transactions"))
        self.assertFalse(bm._is_mechanical(
            "rewrite the auth crypto for format"))

    def test_empty_prompt_is_not_mechanical(self):
        """Empty/None prompts are not mechanical."""
        self.assertFalse(bm._is_mechanical(""))
        self.assertFalse(bm._is_mechanical(None))

    def test_non_mechanical_prompt(self):
        """Standard prompts without mechanical keywords are not mechanical."""
        self.assertFalse(bm._is_mechanical("add a new feature for user preferences"))
        self.assertFalse(bm._is_mechanical("implement the settlement engine"))

    def test_mechanical_case_insensitive(self):
        """Mechanical keywords are case-insensitive."""
        self.assertTrue(bm._is_mechanical("RENAME all the things"))
        self.assertTrue(bm._is_mechanical("FoRmAt the code"))
        self.assertTrue(bm._is_mechanical("lint checking"))


class ProtectionRulesTests(unittest.TestCase):
    """Tests for _protected(task) - must never batch protected task types."""

    def test_canary_tasks_are_protected(self):
        """Canary tasks must run independently for attribution."""
        self.assertTrue(bm._protected({"kind": "canary", "slug": "canary-test"}))

    def test_canary_in_slug_is_protected(self):
        """Tasks with 'canary' in the slug are protected."""
        self.assertTrue(bm._protected({"slug": "some-canary-feature", "kind": "mechanical"}))
        self.assertTrue(bm._protected({"slug": "canary-foo", "kind": "feature"}))

    def test_recovery_tasks_are_protected(self):
        """Recovery/evidence tasks need independent attribution."""
        self.assertTrue(bm._protected({"slug": "recover-missing-branch-xyz", "kind": "recovery"}))
        self.assertTrue(bm._protected({"slug": "qafix-timeout-bug", "kind": "mechanical"}))
        self.assertTrue(bm._protected({"slug": "relfix-deploy-blocker", "kind": "mechanical"}))
        self.assertTrue(bm._protected({"slug": "rework-payment-flow", "kind": "mechanical"}))
        self.assertTrue(bm._protected({"slug": "buildfix-ts-error", "kind": "mechanical"}))
        self.assertTrue(bm._protected({"slug": "deployfix-vercel", "kind": "mechanical"}))

    def test_normal_mechanical_is_not_protected(self):
        """Normal mechanical tasks without protected prefixes can be batched."""
        self.assertFalse(bm._protected({"slug": "lint-unused", "kind": "mechanical"}))
        self.assertFalse(bm._protected({"slug": "format-imports", "kind": "feature"}))

    def test_none_task_is_not_protected(self):
        """None/empty tasks default to not protected."""
        self.assertFalse(bm._protected(None))
        self.assertFalse(bm._protected({}))

    def test_missing_slug_field_is_safe(self):
        """Missing slug field should not crash, defaults to safe."""
        self.assertFalse(bm._protected({"kind": "mechanical"}))


class FindBatchesTests(unittest.TestCase):
    """Tests for find_batches() - the core batching logic."""

    def setUp(self):
        self.mock_select = MagicMock()

    @patch('batch_mechanical.db.select')
    def test_no_tasks_returns_empty_dict(self, mock_select):
        """Empty queue returns no batches."""
        mock_select.return_value = []
        result = bm.find_batches()
        self.assertEqual(result, {})

    @patch('batch_mechanical.db.select')
    def test_single_mechanical_task_not_batched_below_min(self, mock_select):
        """Single task below MIN_GROUP threshold is not batched."""
        tasks = [
            {"id": 1, "slug": "lint-1", "project_id": "proj-1", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"}
        ]
        mock_select.side_effect = [
            tasks,  # tasks query
            []      # depended query
        ]
        result = bm.find_batches()
        self.assertEqual(result, {})

    @patch('batch_mechanical.db.select')
    def test_min_group_tasks_are_batched(self, mock_select):
        """When group size >= MIN_GROUP, tasks are included."""
        tasks = [
            {"id": 1, "slug": "lint-1", "project_id": "proj-1", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 2, "slug": "format-1", "project_id": "proj-1", "prompt": "format code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 3, "slug": "rename-1", "project_id": "proj-1", "prompt": "rename vars",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
        ]
        mock_select.side_effect = [
            tasks,  # tasks query
            []      # depended query
        ]
        result = bm.find_batches()
        self.assertIn("proj-1", result)
        self.assertEqual(len(result["proj-1"]), 3)

    @patch('batch_mechanical.db.select')
    def test_tasks_with_deps_are_excluded(self, mock_select):
        """Tasks that have upstream dependencies are never batched."""
        tasks = [
            {"id": 1, "slug": "lint-1", "project_id": "proj-1", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 2, "slug": "feature-2", "project_id": "proj-1", "prompt": "feature work",
             "deps": ["lint-1"], "state": "QUEUED", "kind": "feature"},  # has deps
            {"id": 3, "slug": "rename-1", "project_id": "proj-1", "prompt": "rename vars",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
        ]
        mock_select.side_effect = [
            tasks,  # tasks query
            []      # depended query
        ]
        result = bm.find_batches()
        # feature-2 is excluded (has deps), so only lint-1 and rename-1 remain (2 < MIN_GROUP)
        self.assertEqual(result, {})

    @patch('batch_mechanical.db.select')
    def test_tasks_that_are_depended_on_are_excluded(self, mock_select):
        """Tasks that something depends on cannot be batched (ordering matters)."""
        tasks = [
            {"id": 1, "slug": "lint-1", "project_id": "proj-1", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 2, "slug": "feature-2", "project_id": "proj-1", "prompt": "feature work",
             "deps": ["lint-1"], "state": "QUEUED", "kind": "feature"},
            {"id": 3, "slug": "rename-1", "project_id": "proj-1", "prompt": "rename vars",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
        ]
        # Simulate the depended query which scans all tasks
        depended_tasks = [
            {"deps": ["lint-1"]}  # feature-2 depends on lint-1
        ]
        mock_select.side_effect = [
            tasks,
            depended_tasks
        ]
        result = bm.find_batches()
        # lint-1 is depended on, feature-2 has deps, only rename-1 is eligible (1 < MIN_GROUP)
        self.assertEqual(result, {})

    @patch('batch_mechanical.db.select')
    def test_batch_max_limit_applied(self, mock_select):
        """Groups larger than BATCH_MAX are truncated."""
        tasks = [
            {"id": i, "slug": f"mech-{i}", "project_id": "proj-1", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"}
            for i in range(bm.BATCH_MAX + 5)
        ]
        mock_select.side_effect = [
            tasks,
            []
        ]
        result = bm.find_batches()
        self.assertIn("proj-1", result)
        self.assertEqual(len(result["proj-1"]), bm.BATCH_MAX)

    @patch('batch_mechanical.db.select')
    def test_protected_tasks_excluded(self, mock_select):
        """Protected tasks (recovery, canary) are never batched."""
        tasks = [
            {"id": 1, "slug": "recover-missing-1", "project_id": "proj-1",
             "prompt": "recover branch", "deps": [], "state": "QUEUED", "kind": "recovery"},
            {"id": 2, "slug": "lint-1", "project_id": "proj-1", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 3, "slug": "format-1", "project_id": "proj-1", "prompt": "format code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 4, "slug": "rename-1", "project_id": "proj-1", "prompt": "rename vars",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
        ]
        mock_select.side_effect = [
            tasks,
            []
        ]
        result = bm.find_batches()
        # recover-missing-1 excluded, lint/format/rename included (3 tasks >= MIN_GROUP)
        self.assertIn("proj-1", result)
        self.assertEqual(len(result["proj-1"]), 3)
        slugs = [t["slug"] for t in result["proj-1"]]
        self.assertNotIn("recover-missing-1", slugs)

    @patch('batch_mechanical.db.select')
    def test_never_rebatch_batches(self, mock_select):
        """Tasks starting with 'batch-mech-' are never re-batched."""
        tasks = [
            {"id": 1, "slug": "batch-mech-old-2", "project_id": "proj-1",
             "prompt": "mech work", "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 2, "slug": "lint-1", "project_id": "proj-1", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 3, "slug": "format-1", "project_id": "proj-1", "prompt": "format code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 4, "slug": "rename-1", "project_id": "proj-1", "prompt": "rename vars",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
        ]
        mock_select.side_effect = [
            tasks,
            []
        ]
        result = bm.find_batches()
        self.assertIn("proj-1", result)
        slugs = [t["slug"] for t in result["proj-1"]]
        self.assertNotIn("batch-mech-old-2", slugs)

    @patch('batch_mechanical.db.select')
    def test_groups_by_project_id(self, mock_select):
        """Tasks are grouped by project_id; no cross-project batches."""
        tasks = [
            {"id": 1, "slug": "lint-1", "project_id": "proj-1", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 2, "slug": "format-1", "project_id": "proj-1", "prompt": "format code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 6, "slug": "rename-1", "project_id": "proj-1", "prompt": "rename vars",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 3, "slug": "lint-2", "project_id": "proj-2", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 4, "slug": "format-2", "project_id": "proj-2", "prompt": "format code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 5, "slug": "rename-2", "project_id": "proj-2", "prompt": "rename vars",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
        ]
        mock_select.side_effect = [
            tasks,
            []
        ]
        result = bm.find_batches()
        self.assertIn("proj-1", result)
        self.assertIn("proj-2", result)
        self.assertEqual(len(result["proj-1"]), 3)
        self.assertEqual(len(result["proj-2"]), 3)


class AnalyzeTests(unittest.TestCase):
    """Tests for analyze() - returns summary of batching opportunities."""

    @patch('batch_mechanical.db.select')
    def test_analyze_returns_list(self, mock_select):
        """analyze() returns a list of batch summaries."""
        tasks = [
            {"id": 1, "slug": "lint-1", "project_id": "proj-1", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 2, "slug": "format-1", "project_id": "proj-1", "prompt": "format code",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
            {"id": 3, "slug": "rename-1", "project_id": "proj-1", "prompt": "rename vars",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
        ]
        mock_select.side_effect = [
            tasks,
            []
        ]
        result = bm.analyze()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["project_id"], "proj-1")
        self.assertEqual(result[0]["count"], 3)
        self.assertEqual(set(result[0]["slugs"]), {"lint-1", "format-1", "rename-1"})

    @patch('batch_mechanical.db.select')
    def test_analyze_empty_batches(self, mock_select):
        """analyze() returns empty list when no batches found."""
        mock_select.return_value = []
        result = bm.analyze()
        self.assertEqual(result, [])


class ApplyTests(unittest.TestCase):
    """Tests for apply() - actually creates batch tasks and marks originals as folded."""

    @patch('batch_mechanical.db.update')
    @patch('batch_mechanical.db.insert')
    @patch('batch_mechanical.db.select')
    def test_apply_creates_batch_task(self, mock_select, mock_insert, mock_update):
        """apply() inserts a new batch task."""
        tasks = [
            {"id": 1, "slug": "lint-1", "project_id": "proj-1", "prompt": "lint code",
             "deps": [], "state": "QUEUED", "kind": "mechanical", "base_branch": "main"},
            {"id": 2, "slug": "format-1", "project_id": "proj-1", "prompt": "format code",
             "deps": [], "state": "QUEUED", "kind": "mechanical", "base_branch": "main"},
            {"id": 3, "slug": "rename-1", "project_id": "proj-1", "prompt": "rename vars",
             "deps": [], "state": "QUEUED", "kind": "mechanical", "base_branch": "main"},
        ]
        mock_select.side_effect = [
            tasks,
            []
        ]
        mock_insert.return_value = None
        mock_update.return_value = None

        result = bm.apply()

        self.assertEqual(result, 1)
        mock_insert.assert_called_once()
        # Check that the batch task was inserted with correct structure
        call_args = mock_insert.call_args
        self.assertEqual(call_args[0][0], "tasks")
        batch_data = call_args[0][1]
        self.assertIn("batch-mech-", batch_data["slug"])
        self.assertEqual(batch_data["project_id"], "proj-1")
        self.assertEqual(batch_data["kind"], "mechanical")
        self.assertEqual(batch_data["state"], "QUEUED")

    @patch('batch_mechanical.db.update')
    @patch('batch_mechanical.db.insert')
    @patch('batch_mechanical.db.select')
    def test_apply_marks_originals_as_done(self, mock_select, mock_insert, mock_update):
        """apply() marks original tasks as DONE with MERGED-INTO note."""
        # A group must reach bm.MIN_GROUP to be worth batching (default 3, tunable
        # via BATCH_MIN). Both of these tests supplied TWO tasks, so find_batches()
        # returned {} and apply() did nothing -- mock_insert.call_args was None and
        # the assertions below crashed on it rather than failing. Built from the
        # constant so an operator tuning BATCH_MIN cannot silently re-break them.
        tasks = _mechanical_tasks(bm.MIN_GROUP)
        mock_select.side_effect = [
            tasks,
            []
        ]
        mock_insert.return_value = None
        mock_update.return_value = None

        bm.apply()

        # Check that all original tasks were marked as DONE.
        #
        # `table, where = args` used to raise ValueError here: db.update takes THREE
        # positional arguments (table, where, updates) and the unpack expected two,
        # so it crashed before reaching the line below that already knew about the
        # third. The name this test carries -- marks originals as DONE -- was never
        # actually asserted; it only ever checked that the table was "tasks".
        self.assertEqual(mock_update.call_count, bm.MIN_GROUP)
        updated_ids = set()
        for call in mock_update.call_args_list:
            args, kwargs = call
            table, where, updates = args[0], args[1], args[2]
            self.assertEqual(table, "tasks")
            self.assertEqual(updates["state"], "DONE")
            self.assertIn("folded into", updates["note"])
            updated_ids.add(where["id"])
        self.assertEqual(updated_ids, {t["id"] for t in tasks},
                         "every folded original must be taken out of the queue")

    @patch('batch_mechanical.db.update')
    @patch('batch_mechanical.db.insert')
    @patch('batch_mechanical.db.select')
    def test_apply_no_batches_found(self, mock_select, mock_insert, mock_update):
        """apply() returns 0 when no batches are found."""
        mock_select.return_value = []
        result = bm.apply()
        self.assertEqual(result, 0)
        mock_insert.assert_not_called()
        mock_update.assert_not_called()

    @patch('batch_mechanical.db.update')
    @patch('batch_mechanical.db.insert')
    @patch('batch_mechanical.db.select')
    def test_apply_combined_prompt_structure(self, mock_select, mock_insert, mock_update):
        """apply() creates a well-structured combined prompt."""
        # A group must reach bm.MIN_GROUP to be worth batching (default 3, tunable
        # via BATCH_MIN). Both of these tests supplied TWO tasks, so find_batches()
        # returned {} and apply() did nothing -- mock_insert.call_args was None and
        # the assertions below crashed on it rather than failing. Built from the
        # constant so an operator tuning BATCH_MIN cannot silently re-break them.
        tasks = _mechanical_tasks(bm.MIN_GROUP)
        mock_select.side_effect = [
            tasks,
            []
        ]
        mock_insert.return_value = None
        mock_update.return_value = None

        bm.apply()

        call_args = mock_insert.call_args
        batch_data = call_args[0][1]
        combined_prompt = batch_data["prompt"]

        # Verify the combined prompt includes task info and clear structure
        self.assertIn("Complete ALL", combined_prompt)
        for task in tasks:
            self.assertIn(task["slug"], combined_prompt)
            self.assertIn(task["prompt"], combined_prompt)


class EdgeCasesTests(unittest.TestCase):
    """Edge cases and error conditions."""

    def test_is_mechanical_with_special_chars(self):
        """Mechanical classification handles special characters."""
        self.assertTrue(bm._is_mechanical("rename x -> y in config.yaml"))
        self.assertTrue(bm._is_mechanical("format_code() -> format(code)"))

    def test_protected_with_malformed_task(self):
        """_protected() handles malformed task dicts gracefully."""
        self.assertFalse(bm._protected({"slug": None}))
        self.assertFalse(bm._protected({"kind": None}))
        self.assertFalse(bm._protected({"slug": 123}))  # non-string slug

    @patch('batch_mechanical.db.select')
    def test_find_batches_with_none_values(self, mock_select):
        """find_batches() handles None values in task fields."""
        tasks = [
            {"id": 1, "slug": "lint-1", "project_id": "proj-1", "prompt": "lint code",
             "deps": None, "state": "QUEUED", "kind": "mechanical"},
            {"id": 2, "slug": "format-1", "project_id": "proj-1", "prompt": "format code",
             "deps": [], "state": "QUEUED", "kind": None},
            {"id": 3, "slug": "rename-1", "project_id": "proj-1", "prompt": "rename vars",
             "deps": [], "state": "QUEUED", "kind": "mechanical"},
        ]
        mock_select.side_effect = [
            tasks,
            []
        ]
        result = bm.find_batches()
        # Should complete without error
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
