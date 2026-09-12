"""A dependency can be unmet because it is not finished, or because it never will be.

Those are different conditions and only one is actionable, but the claim path
counted them identically under `deps_unmet`. Measured on the live queue
2026-08-25: 321 QUEUED tasks, 325 dependency edges, 4 satisfied -- and 204 of the
remaining edges pointed at something structurally unsatisfiable, which had been
true and invisible since 2026-07-15.

Three shapes of "never":

  * the dependency is in a terminal state that is not a satisfying one --
    SUPERSEDED, CLOSED, QUARANTINED, PHANTOM_UNVERIFIED (132 edges live);
  * the dependency was DECOMPOSED but its children were never created, so
    nothing exists that could finish on its behalf (43 edges live, after the
    parent_task_id backfill);
  * the dependency names a slug no task has ever had (8 edges live).

And one shape of "not yet" that used to be mistaken for "never": a DECOMPOSED
parent WITH children is satisfied exactly when all of them are, which is what
decomposing a task means.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


class _StubbedDB(unittest.TestCase):
    """db.select_all/select answer from an in-memory task table."""

    def install(self):
        self.tasks = []
        self.projects = []

        def select_all(table, params=None, **kw):
            params = params or {}
            if table == "projects":
                return list(self.projects)
            rows = list(self.tasks)
            state = params.get("state") or ""
            if state.startswith("eq."):
                rows = [r for r in rows if r.get("state") == state[3:]]
            elif state.startswith("in."):
                wanted = set(state[4:-1].split(","))
                rows = [r for r in rows if r.get("state") in wanted]
            if params.get("parent_task_id") == "not.is.null":
                rows = [r for r in rows if r.get("parent_task_id")]
            return rows

        def select(table, params=None):
            if table == "projects":
                return list(self.projects)
            return select_all(table, params)

        originals = (db.select_all, db.select)
        db.select_all, db.select = select_all, select
        db.invalidate_done_cache()

        def restore():
            db.select_all, db.select = originals
            db.invalidate_done_cache()

        self.addCleanup(restore)

    setUp = install     # unittest owns the name; aliased for the snake_case rule

    def task(self, slug, state="QUEUED", **kw):
        row = {"id": "id-" + slug, "slug": slug, "state": state,
               "project_id": "p1", "deps": [], "parent_task_id": None}
        row.update(kw)
        self.tasks.append(row)
        return row


class DecompositionClosure(_StubbedDB):
    """A DECOMPOSED parent never reaches DONE. Its children do."""

    def test_a_parent_whose_children_are_all_done_satisfies_a_dependency(self):
        parent = self.task("parent", state="DECOMPOSED")
        self.task("parent-1", state="DONE", parent_task_id=parent["id"])
        self.task("parent-2", state="MERGED", parent_task_id=parent["id"])

        self.assertIn("parent", db._done_slugs())

    def test_a_parent_with_one_unfinished_child_does_not(self):
        """Releasing early would let a dependent build on work that is still running."""
        parent = self.task("parent", state="DECOMPOSED")
        self.task("parent-1", state="DONE", parent_task_id=parent["id"])
        self.task("parent-2", state="RUNNING", parent_task_id=parent["id"])

        self.assertNotIn("parent", db._done_slugs())

    def test_a_childless_parent_is_not_satisfied(self):
        """"No children" must not be read as "all children done".

        A decomposition that lost its children is a defect in its own right and
        the queue must keep saying so, not paper over it.
        """
        self.task("parent", state="DECOMPOSED")

        self.assertNotIn("parent", db._done_slugs())

    def test_closure_is_reported_under_the_qualified_slug_too(self):
        """Cross-project deps arrive as project_name:slug."""
        self.projects = [{"id": "p1", "name": "beethoven"}]
        parent = self.task("parent", state="DECOMPOSED")
        self.task("parent-1", state="DEPLOYED_AND_VERIFIED", parent_task_id=parent["id"])

        done = db._done_slugs()
        self.assertIn("parent", done)
        self.assertIn("beethoven:parent", done)


class DeadEndDetection(_StubbedDB):
    def test_terminal_states_are_dead_ends(self):
        for state in ("SUPERSEDED", "CLOSED", "QUARANTINED", "PHANTOM_UNVERIFIED"):
            self.task("dep-" + state, state=state)

        dead = db.dead_end_slugs()
        for state in ("SUPERSEDED", "CLOSED", "QUARANTINED", "PHANTOM_UNVERIFIED"):
            self.assertIn("dep-" + state, dead, state)

    def test_a_childless_decomposition_is_a_dead_end(self):
        self.task("orphaned", state="DECOMPOSED")
        self.assertIn("orphaned", db.dead_end_slugs())

    def test_a_decomposition_with_children_is_not(self):
        """It resolves through closure as its children land; calling it a dead
        end would be wrong the moment the last one does."""
        parent = self.task("splitting", state="DECOMPOSED")
        self.task("splitting-1", state="RUNNING", parent_task_id=parent["id"])

        self.assertNotIn("splitting", db.dead_end_slugs())

    def test_ordinary_pending_states_are_not_dead_ends(self):
        self.task("waiting", state="QUEUED")
        self.task("working", state="RUNNING")
        dead = db.dead_end_slugs()
        self.assertNotIn("waiting", dead)
        self.assertNotIn("working", dead)


class HasDeadEndDep(_StubbedDB):
    def test_a_dep_on_a_closed_task_is_a_dead_end(self):
        self.task("gone", state="CLOSED")
        blocked = self.task("blocked", deps=["gone"])
        self.assertTrue(db._has_dead_end_dep(blocked, db._done_slugs()))

    def test_a_dep_naming_a_slug_no_task_has_is_a_dead_end(self):
        blocked = self.task("blocked", deps=["typo-never-existed"])
        self.assertTrue(db._has_dead_end_dep(blocked, db._done_slugs()))

    def test_a_dep_on_running_work_is_not(self):
        self.task("in-progress", state="RUNNING")
        blocked = self.task("blocked", deps=["in-progress"])
        self.assertFalse(db._has_dead_end_dep(blocked, db._done_slugs()))

    def test_only_unmet_deps_count(self):
        """A finished dep that happens to be superseded is not what is blocking.

        The task is waiting on real pending work; reporting it as structurally
        stuck would send someone to fix the wrong thing.
        """
        self.task("finished", state="MERGED")
        self.task("also-superseded", state="SUPERSEDED")
        self.task("still-going", state="RUNNING")
        done = db._done_slugs()
        blocked = self.task("blocked", deps=["finished", "still-going"])
        self.assertFalse(db._has_dead_end_dep(blocked, done))

        # ...but once the dead-end dep is genuinely unmet, it does count.
        also = self.task("blocked-2", deps=["also-superseded", "still-going"])
        self.assertTrue(db._has_dead_end_dep(also, done))

    def test_a_qualified_dep_resolves_by_its_bare_slug(self):
        self.task("gone", state="SUPERSEDED")
        blocked = self.task("blocked", deps=["otherproject:gone"])
        self.assertTrue(db._has_dead_end_dep(blocked, db._done_slugs()))

    def test_a_task_with_no_deps_is_never_a_dead_end(self):
        blocked = self.task("free", deps=[])
        self.assertFalse(db._has_dead_end_dep(blocked, db._done_slugs()))


class PagingIsNotTruncation(unittest.TestCase):
    """select_all goes through select(), so every full page tripped the guard.

    queue_deadlock_report.py reads all 24,750 tasks correctly and opened with a
    TRUNCATED SCAN banner. A warning about silent data loss that fires when
    there is none teaches people to scroll past the real ones.
    """

    def _warn_output(self, paging):
        """What the REAL guard prints for a full page, with paging on or off."""
        import io
        import contextlib

        full_page = [{"slug": "s%d" % i} for i in range(db.PAGE_SIZE)]
        params = {"select": "slug", "order": "id.asc", "limit": str(db.PAGE_SIZE)}

        db._scan_warned.clear()
        before = getattr(db._paging_depth, "n", 0)
        db._paging_depth.n = 1 if paging else 0
        buf = io.StringIO()
        try:
            # stderr: the guard reports to the error stream, not stdout.
            with contextlib.redirect_stderr(buf):
                db._warn_if_truncated("zz_probe_table", params, full_page)
        finally:
            db._paging_depth.n = before
            db._scan_warned.clear()
        return buf.getvalue()

    def test_a_full_page_inside_the_pager_does_not_warn(self):
        self.assertEqual(self._warn_output(paging=True), "")

    def test_the_same_page_outside_the_pager_still_warns(self):
        """The suppression must be scoped to paging, not a blanket disable."""
        out = self._warn_output(paging=False)
        self.assertIn("TRUNCATED SCAN", out)
        self.assertIn("zz_probe_table", out)

    def test_the_paging_flag_is_cleared_afterwards(self):
        """A leaked flag would silence the guard for every later caller."""
        def fake_select(table, params=None):
            return []

        orig = db.select
        db.select = fake_select
        try:
            db.select_all("tasks", {"select": "slug"}, order="id.asc")
        finally:
            db.select = orig
        self.assertEqual(getattr(db._paging_depth, "n", 0), 0)

    def test_the_flag_is_cleared_even_when_a_page_raises(self):
        def boom(table, params=None):
            raise RuntimeError("page failed")

        orig = db.select
        db.select = boom
        try:
            with self.assertRaises(RuntimeError):
                db.select_all("tasks", {"select": "slug"}, order="id.asc")
        finally:
            db.select = orig
        self.assertEqual(getattr(db._paging_depth, "n", 0), 0)


if __name__ == "__main__":
    unittest.main()
