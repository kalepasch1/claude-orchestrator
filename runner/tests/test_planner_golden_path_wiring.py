#!/usr/bin/env python3
"""golden_path was dead code — Wave C Part 4's compounding half was never wired.

`runner/golden_path.py` shipped complete, tested and dependency-free, and a repo-wide
grep found it imported by nothing. Part 7's disposition memory (suppression) was wired
into `planner.plan()`; Part 4's golden paths and strategy-aware generation were not, so
the fleet kept starting shards from the most SIMILAR prior diff rather than the
best-OUTCOME one, and kept discovering AMOE flows and state gates as review findings.

These pin the wiring contract: context is APPENDED (never substituted), it is
idempotent across re-plans, an unapproved structure is refused loudly, and every
failure mode leaves the plan exactly as it was.

Run: python3 -m unittest runner.tests.test_planner_golden_path_wiring -v
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import golden_path
import planner

APPROVED = {"structure": "sweepstakes", "vertical": "sweepstakes", "approved": True,
            "jurisdictions": ["NY", "FL"]}

SHARDS = [{"slug": f"shard-{i}", "vertical": "sweepstakes", "merged": True,
           "repair_attempts": i, "first_pass": i == 0} for i in range(8)]


def _tasks(n=2):
    return [{"slug": f"t{i}", "prompt": f"do thing {i}"} for i in range(n)]


class AppendsContextTest(unittest.TestCase):
    def test_approved_structure_is_prepended_to_every_prompt(self):
        tasks = planner._apply_golden_path(_tasks(3), strategy=APPROVED, shards=SHARDS)
        for t in tasks:
            self.assertIn("APPROVED STRUCTURE: sweepstakes", t["prompt"])

    def test_original_prompt_is_preserved(self):
        tasks = planner._apply_golden_path(_tasks(2), strategy=APPROVED, shards=SHARDS)
        for i, t in enumerate(tasks):
            self.assertIn(f"do thing {i}", t["prompt"])

    def test_structural_requirements_reach_the_prompt(self):
        tasks = planner._apply_golden_path(_tasks(1), strategy=APPROVED, shards=SHARDS)
        self.assertIn("alternate method of entry", tasks[0]["prompt"])
        self.assertIn("per-state eligibility gating", tasks[0]["prompt"])

    def test_jurisdictions_reach_the_prompt(self):
        tasks = planner._apply_golden_path(_tasks(1), strategy=APPROVED, shards=SHARDS)
        self.assertIn("JURISDICTIONS: NY, FL", tasks[0]["prompt"])

    def test_empty_prompt_is_populated_not_skipped(self):
        tasks = planner._apply_golden_path([{"slug": "t", "prompt": ""}],
                                           strategy=APPROVED, shards=SHARDS)
        self.assertIn("APPROVED STRUCTURE", tasks[0]["prompt"])

    def test_task_count_is_never_changed(self):
        tasks = planner._apply_golden_path(_tasks(5), strategy=APPROVED, shards=SHARDS)
        self.assertEqual(len(tasks), 5)


class IdempotenceTest(unittest.TestCase):
    def test_replanning_does_not_stack_blocks(self):
        once = planner._apply_golden_path(_tasks(1), strategy=APPROVED, shards=SHARDS)
        twice = planner._apply_golden_path(once, strategy=APPROVED, shards=SHARDS)
        self.assertEqual(twice[0]["prompt"].count("APPROVED STRUCTURE:"), 1)


class RefusalTest(unittest.TestCase):
    """No approved structure means no context — and it must say so."""

    def test_unapproved_structure_adds_nothing(self):
        strategy = dict(APPROVED, approved=False)
        tasks = planner._apply_golden_path(_tasks(1), strategy=strategy, shards=SHARDS)
        self.assertNotIn("APPROVED STRUCTURE", tasks[0]["prompt"])
        self.assertEqual(tasks[0]["prompt"], "do thing 0")

    def test_missing_structure_adds_nothing(self):
        tasks = planner._apply_golden_path(_tasks(1), strategy={}, shards=SHARDS)
        self.assertEqual(tasks[0]["prompt"], "do thing 0")

    def test_non_dict_strategy_adds_nothing(self):
        for junk in ("string", 42, [], None):
            tasks = planner._apply_golden_path(_tasks(1), strategy=junk, shards=SHARDS)
            self.assertEqual(tasks[0]["prompt"], "do thing 0")


class ThinEvidenceTest(unittest.TestCase):
    """A vertical with too few merged shards has no golden path — but still has a structure."""

    def test_no_template_still_yields_structure_context(self):
        tasks = planner._apply_golden_path(_tasks(1), strategy=APPROVED, shards=[])
        self.assertIn("APPROVED STRUCTURE", tasks[0]["prompt"])
        self.assertNotIn("GOLDEN PATH:", tasks[0]["prompt"])

    def test_sufficient_shards_name_a_golden_path(self):
        template = golden_path.template_for(SHARDS, "sweepstakes")
        self.assertIsNotNone(template)
        tasks = planner._apply_golden_path(_tasks(1), strategy=APPROVED, shards=SHARDS)
        self.assertIn("GOLDEN PATH:", tasks[0]["prompt"])
        self.assertIn(template["slug"], tasks[0]["prompt"])

    def test_golden_path_is_outcome_ranked_not_similarity_ranked(self):
        # shard-0 merged first-pass with zero repairs: the best OUTCOME, and the one
        # a similarity ranking would have no reason to prefer.
        self.assertEqual(golden_path.template_for(SHARDS, "sweepstakes")["slug"], "shard-0")


class FailSoftTest(unittest.TestCase):
    def test_golden_path_import_failure_leaves_plan_unchanged(self):
        with patch.object(golden_path, "strategy_context", side_effect=RuntimeError("boom")):
            tasks = planner._apply_golden_path(_tasks(2), strategy=APPROVED, shards=SHARDS)
        self.assertEqual([t["prompt"] for t in tasks], ["do thing 0", "do thing 1"])

    def test_empty_task_list_is_returned_as_is(self):
        self.assertEqual(planner._apply_golden_path([], strategy=APPROVED, shards=SHARDS), [])

    def test_db_lookups_are_fail_soft(self):
        with patch("db.select", side_effect=RuntimeError("db down")):
            self.assertEqual(planner._approved_strategy("beethoven"), {})
            self.assertEqual(planner._merged_shards("beethoven"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
