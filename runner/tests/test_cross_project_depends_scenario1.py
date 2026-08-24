"""Scenario 1: a task in project A depending on a BARE id resolves within project A.

The existing scenario-1 coverage in test_cross_project_depends.py is
`self.assertTrue(all(d in done for d in deps))` over a hand-built `done` set —
that asserts Python's `in` operator, not the resolver. It would still pass if
db._done_slugs() stopped emitting bare slugs entirely, which is the exact
regression backward compatibility exists to prevent.

These drive the REAL resolver: db._done_slugs() is called with the tasks and
projects tables mocked, and the assertions are about what it emits.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

for _mod in ("supabase", "postgrest", "httpx", "gotrue", "realtime",
             "storage3", "supafunc"):
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except ImportError:
            import types as _types
            sys.modules[_mod] = _types.ModuleType(_mod)

import db  # noqa: E402


PROJECT_A = "pa"
PROJECT_B = "pb"
PROJECTS = [{"id": PROJECT_A, "name": "alpha"}, {"id": PROJECT_B, "name": "beta"}]


def _done_slugs_with(done_rows, projects=PROJECTS):
    """Run the real db._done_slugs() against mocked tables."""
    db.invalidate_done_cache()
    with patch.object(db, "select_all", return_value=done_rows), \
         patch.object(db, "select", return_value=projects):
        try:
            return db._done_slugs()
        finally:
            db.invalidate_done_cache()


class TestScenario1BareDepResolvesWithinItsProject(unittest.TestCase):
    def test_a_completed_task_contributes_its_bare_slug(self):
        # Project A finished `some_task`; a sibling in A depending on the bare id
        # must see it satisfied.
        slugs = _done_slugs_with([{"slug": "some_task", "project_id": PROJECT_A}])
        self.assertIn("some_task", slugs)

    def test_the_dependent_task_in_project_a_is_unblocked(self):
        slugs = _done_slugs_with([{"slug": "some_task", "project_id": PROJECT_A}])
        deps = ["some_task"]
        self.assertTrue(all(d in slugs for d in deps))

    def test_it_also_contributes_the_qualified_form(self):
        # Bare stays for backward compatibility; qualified is added, not swapped.
        slugs = _done_slugs_with([{"slug": "some_task", "project_id": PROJECT_A}])
        self.assertIn("alpha:some_task", slugs)

    def test_an_unfinished_dependency_still_blocks(self):
        # Guards the assertion above from passing vacuously.
        slugs = _done_slugs_with([{"slug": "other_task", "project_id": PROJECT_A}])
        self.assertNotIn("some_task", slugs)
        self.assertFalse(all(d in slugs for d in ["some_task"]))

    def test_a_bare_dep_is_satisfied_by_a_same_named_task_in_another_project(self):
        # Documents the deliberate trade-off: bare ids are matched by slug across
        # the fleet, which is what "backward compatible" means here. Anyone who
        # needs project scoping must qualify the dep — and the qualified form
        # below proves that scoping actually works.
        slugs = _done_slugs_with([{"slug": "some_task", "project_id": PROJECT_B}])
        self.assertIn("some_task", slugs)
        self.assertIn("beta:some_task", slugs)
        self.assertNotIn("alpha:some_task", slugs)

    def test_a_qualified_dep_does_not_match_the_wrong_project(self):
        slugs = _done_slugs_with([{"slug": "some_task", "project_id": PROJECT_B}])
        self.assertFalse(all(d in slugs for d in ["alpha:some_task"]))

    def test_rows_without_a_slug_are_skipped(self):
        slugs = _done_slugs_with([{"slug": None, "project_id": PROJECT_A},
                                  {"project_id": PROJECT_A},
                                  {"slug": "real", "project_id": PROJECT_A}])
        self.assertEqual({s for s in slugs if s.startswith("alpha:")}, {"alpha:real"})

    def test_an_unknown_project_id_still_yields_the_bare_slug(self):
        # A project missing from the projects table must not lose the bare entry,
        # or every dep on that task would block forever.
        slugs = _done_slugs_with([{"slug": "orphan", "project_id": "pz"}])
        self.assertIn("orphan", slugs)
        self.assertNotIn("pz:orphan", slugs)

    def test_no_completed_tasks_yields_an_empty_set_not_none(self):
        self.assertEqual(_done_slugs_with([]), set())


if __name__ == "__main__":
    unittest.main()
