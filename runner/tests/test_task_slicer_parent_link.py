"""A slice must record its parent in a column, not only in prose.

task_slicer wrote the parent into the note ("parent=<slug>") and into the prompt
("Parent task: <slug>") and nowhere anything could join on.
bankruptcy_decompose.py has always set parent_task_id, and
queue_materializer.py:228 calls it "authoritative" -- the slicer was the one
decomposer that never wrote it.

The cost was a queue that could not resolve its own dependencies. A task waiting
on a DECOMPOSED parent is waiting for that parent's children, and with no join
column there was no way to find them. Measured on the live queue 2026-08-25: of
56 decomposed tasks that something depended on, only 6 had children reachable by
parent_task_id; 10 more had children reachable only by slug prefix, and
dependency resolution treated every one of those as permanently unsatisfied.

A slug-prefix fallback is NOT the answer and these tests do not ask for one:
slugs nest, so `foo`, `foo-slice-1` and `foo-slice-1-sub-2` all prefix-match each
other. Against the live table that heuristic produced 17,346 candidate links of
which 14,217 were ambiguous.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import task_slicer

PARENT = {"id": "parent-uuid-1", "slug": "big-task", "project_id": "p1",
          "kind": "build", "base_branch": "master"}
PARTS = [
    {"slug": "big-task-slice-1", "prompt": "first half", "deps": []},
    {"slug": "big-task-slice-2", "prompt": "second half", "deps": ["big-task-slice-1"]},
]


class _Sliced(unittest.TestCase):
    def run_the_slicer(self, insert_side_effect=None):
        self.inserted = []

        def fake_insert(table, row, **kw):
            if insert_side_effect:
                insert_side_effect(row)
            self.inserted.append(row)
            return [row]

        patches = [
            patch.object(task_slicer.db, "insert", side_effect=fake_insert),
            patch.object(task_slicer.db, "update", return_value=None),
            patch.object(task_slicer, "_slice_exists", return_value=False),
            patch.object(task_slicer, "should_slice", return_value=True),
            patch.object(task_slicer, "ai_slice_task", return_value=list(PARTS)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    setUp = run_the_slicer      # unittest owns the name

    def slice_it(self):
        """The real entry point. parts come from ai_slice_task, stubbed above."""
        return task_slicer.pre_agent_hook(dict(PARENT))


class EverySliceCarriesItsParent(_Sliced):
    def test_parent_task_id_is_set_on_every_slice(self):
        self.slice_it()

        self.assertEqual(len(self.inserted), len(PARTS))
        for row in self.inserted:
            self.assertEqual(row["parent_task_id"], PARENT["id"], row["slug"])

    def test_the_parent_id_is_the_id_and_not_the_slug(self):
        """parent_task_id joins on tasks.id. A slug there links to nothing."""
        self.slice_it()
        for row in self.inserted:
            self.assertNotEqual(row["parent_task_id"], PARENT["slug"])

    def test_the_prose_markers_are_kept_as_well(self):
        """The note and prompt stay: they are what made the backfill possible.

        85 pre-existing slices were relinked from "parent=<slug>" in the note.
        Had the slicer only ever written the column, those rows would have been
        unrecoverable.
        """
        self.slice_it()
        for row in self.inserted:
            self.assertIn("parent=" + PARENT["slug"], row["note"])
            self.assertIn("Parent task: " + PARENT["slug"], row["prompt"])


class TheInsertLadderDropsItLate(_Sliced):
    """_insert_task strips columns to survive an older schema. Order matters."""

    def test_parent_task_id_survives_a_schema_without_deps(self):
        rejected = {"n": 0}

        def reject_deps(row):
            if "deps" in row:
                rejected["n"] += 1
                raise RuntimeError("column deps does not exist")

        self.addCleanup(lambda: None)
        with patch.object(task_slicer, "_slice_exists", return_value=False), \
             patch.object(task_slicer, "should_slice", return_value=True), \
             patch.object(task_slicer, "ai_slice_task", return_value=list(PARTS)):
            self.inserted = []

            def fake_insert(table, row, **kw):
                reject_deps(row)
                self.inserted.append(row)
                return [row]

            with patch.object(task_slicer.db, "insert", side_effect=fake_insert), \
                 patch.object(task_slicer.db, "update", return_value=None):
                self.slice_it()

        self.assertTrue(self.inserted)
        for row in self.inserted:
            self.assertNotIn("deps", row)
            self.assertEqual(row["parent_task_id"], PARENT["id"],
                             "losing deps must not cost the parent link")

    def test_parent_task_id_is_only_dropped_as_the_last_resort(self):
        """A slice that lands without it is invisible to its own parent forever."""
        attempts = []

        def record_then_reject(row):
            attempts.append(sorted(row))
            raise RuntimeError("nope")

        with patch.object(task_slicer, "_slice_exists", return_value=False), \
             patch.object(task_slicer, "should_slice", return_value=True), \
             patch.object(task_slicer, "ai_slice_task", return_value=list(PARTS)), \
             patch.object(task_slicer.db, "update", return_value=None), \
             patch.object(task_slicer.db, "insert",
                          side_effect=lambda t, r, **k: record_then_reject(r)):
            self.slice_it()

        # One part's worth of variants, in order.
        first_part = attempts[:4]
        self.assertEqual(len(first_part), 4, "expected four fallback shapes")
        self.assertIn("parent_task_id", first_part[0])
        self.assertIn("parent_task_id", first_part[1])   # deps dropped
        self.assertIn("parent_task_id", first_part[2])   # base_branch dropped too
        self.assertNotIn("parent_task_id", first_part[3])  # last resort only


if __name__ == "__main__":
    unittest.main()
