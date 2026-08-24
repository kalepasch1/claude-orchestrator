#!/usr/bin/env python3
"""The conflict-redo loop must be bounded, and must never destroy committed work.

WHAT THIS COVERS THAT NOTHING ELSE DID
--------------------------------------
`approval_merge.run()`'s CONFLICT branch carries two invariants and neither was tested.

1. **Bounded retries.** A stale branch that conflicts is rebuilt on fresh base up to
   MERGE_CONFLICT_REDO_CAP; past the cap the task goes to CONFLICT for a human. The
   existing cap tests (test_merge_train.py, test_patch_template_conflict_handling.py)
   assert the `train:` marker — that is merge_train's path, not this one.

2. **Archive, never destroy.** The redo frees the branch NAME so the worktree can be
   rebuilt. The code carries an explicit 2026-08-04 note that this once force-deleted
   the branch and took the agent's commits with it, which then had to be regenerated as
   recover-missing-branch-<slug> tasks. The fix routes through
   `branch_durability.safe_delete`, which archives the tip under refs/archive/ first.

   Nothing asserted that. A refactor could reintroduce `git branch -D` and every test in
   the repo would still pass while real work went into the bin.

WHY INVARIANT 2 IS CHECKED STRUCTURALLY
---------------------------------------
Driving `run()` to the CONFLICT branch means faking the whole card/task/project scan,
the paused-host guard, the done->merged sweep and the merge-train filters — a harness
far larger and more brittle than the thing under test, and one that would go green for
the wrong reason the moment any of those guards moved.

So the durability invariant is asserted against the parsed source instead: the CONFLICT
branch must reference safe_delete and must not contain a raw destructive delete. That is
narrower than a behavioural test, and it is the check that actually fails if someone
reintroduces the deletion — which is the regression worth catching. The bounding logic
(`_bounded_int`) IS directly callable and is tested behaviourally below.
"""
import ast
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import approval_merge  # noqa: E402

SOURCE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "approval_merge.py")


def _conflict_branch_source():
    """The body of the `if result == "CONFLICT":` block inside run(), as source text."""
    with open(SOURCE_PATH, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)
    run = next(n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "run")
    for node in ast.walk(run):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if "CONFLICT" in test and "result" in test:
            return "\n".join(ast.unparse(stmt) for stmt in node.body)
    raise AssertionError("could not locate the CONFLICT branch in approval_merge.run()")


class TestTheConflictBranchExists(unittest.TestCase):
    def test_the_branch_is_findable(self):
        """If this fails the other structural assertions are vacuous, so it is explicit."""
        self.assertTrue(_conflict_branch_source().strip())


class TestNeverDestroysCommittedWork(unittest.TestCase):
    def setUp(self):
        self.body = _conflict_branch_source()

    def test_the_redo_routes_through_the_durability_guard(self):
        self.assertIn("safe_delete", self.body,
                      "conflict redo no longer calls branch_durability.safe_delete; "
                      "the branch tip would not be archived")

    def test_the_durability_module_is_imported_in_the_branch(self):
        self.assertIn("branch_durability", self.body)

    def test_no_raw_force_delete_of_a_branch(self):
        """The exact regression: `git branch -D` discards the agent's commits."""
        for forbidden in ("'-D'", '"-D"', "'branch', '-D'", "-delete"):
            self.assertNotIn(forbidden, self.body,
                             f"conflict redo contains a destructive delete ({forbidden})")

    def test_no_reset_hard_or_clean_in_the_redo(self):
        for forbidden in ("reset', '--hard", "clean', '-fd", "--hard", "-fdx"):
            self.assertNotIn(forbidden, self.body,
                             f"conflict redo would discard work via {forbidden}")

    def test_the_guard_failure_path_declines_to_delete(self):
        """If branch_durability cannot be imported, nothing may be deleted anyway."""
        self.assertIn("NOT deleting", self.body)


class TestTheLoopIsBounded(unittest.TestCase):
    def setUp(self):
        self.body = _conflict_branch_source()

    def test_the_retry_counter_is_incremented(self):
        """Without this the redo loop never terminates."""
        self.assertIn("transient_retries", self.body)
        self.assertIn("tr + 1", self.body.replace("tr+1", "tr + 1"))

    def test_the_cap_is_consulted(self):
        self.assertIn("MERGE_CONFLICT_REDO_CAP", self.body)

    def test_exhausting_the_cap_marks_the_task_conflict(self):
        self.assertIn("CONFLICT", self.body)
        self.assertIn("conflict-exhausted", self.body)

    def test_exhausting_the_cap_does_not_delete_the_branch(self):
        """At the cap the branch is handed to a human, so it must still exist."""
        after_cap = self.body.split("exhausted redo cap", 1)
        if len(after_cap) == 2:
            self.assertNotIn("safe_delete", after_cap[1])


class TestCapConfiguration(unittest.TestCase):
    """The bounding logic is directly callable, so this part is behavioural."""

    def _cap(self):
        return approval_merge._bounded_int("MERGE_CONFLICT_REDO_CAP", 2,
                                           ceiling=approval_merge._MAX_REDO_CAP)

    def test_the_default_cap_is_used_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MERGE_CONFLICT_REDO_CAP", None)
            self.assertEqual(self._cap(), 2)

    def test_a_configured_cap_is_honoured(self):
        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "3"}):
            self.assertEqual(self._cap(), 3)

    def test_a_runaway_cap_is_bounded(self):
        """Misconfiguration must not turn a bounded loop into an unbounded one."""
        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "9999"}):
            self.assertEqual(self._cap(), approval_merge._MAX_REDO_CAP)

    def test_a_garbage_cap_falls_back_to_the_default(self):
        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "lots"}):
            self.assertEqual(self._cap(), 2)

    def test_a_negative_cap_is_floored_at_zero(self):
        """Zero means 'never redo, escalate immediately' — not 'redo forever'."""
        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "-5"}):
            self.assertEqual(self._cap(), 0)

    def test_the_ceiling_constant_is_small(self):
        self.assertLessEqual(approval_merge._MAX_REDO_CAP, 10)


if __name__ == "__main__":
    unittest.main()
