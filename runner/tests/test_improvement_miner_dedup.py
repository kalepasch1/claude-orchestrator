"""Escalation must coalesce on intent instead of minting duplicate slugs.

The bug: `_enqueue_exploration`'s default collaborators filtered on
`intent_key=eq.<key>` and wrote `row["intent_key"] = key`. The `tasks` table has
NO `intent_key` column — verified against the live schema, which has `note` and
not `intent_key` — so both calls raised PostgREST "column does not exist", and
both sites wrap the call in `except Exception`. The read therefore returned None
(never a duplicate, always insert) and the write then failed too. Escalation has
never actually enqueued anything, and could not have coalesced if it had.

`enqueue_task.py` already solved the same problem by embedding the key in `note`
as `[enqueue-intent:<key>]` and filtering on that marker, so the fix reuses its
helpers rather than adding a second scheme. The queue currently holds slugs
duplicated 99 and 98 times; this is the mechanism that is supposed to stop that.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import improvement_miner as im  # noqa: E402
import enqueue as enq  # noqa: E402


class NoteMarkerTestCase(unittest.TestCase):
    def test_marker_is_appended_and_round_trips(self):
        import enqueue_task
        note = im._note_with_intent("original note", "proj::base::")
        self.assertIn("original note", note)
        self.assertEqual(enqueue_task._intent_from_note(note), "proj::base::")

    def test_marker_is_never_appended_twice(self):
        """Two markers would make _intent_from_note return whichever came first."""
        once = im._note_with_intent("n", "k1")
        twice = im._note_with_intent(once, "k1")
        self.assertEqual(once, twice)
        self.assertEqual(twice.count("[enqueue-intent:"), 1)

    def test_an_empty_note_still_carries_the_marker(self):
        import enqueue_task
        for empty in (None, "", "   "):
            note = im._note_with_intent(empty, "k")
            self.assertEqual(enqueue_task._intent_from_note(note), "k")


class EscalationCoalesceTestCase(unittest.TestCase):
    """Drives enqueue.enqueue_task with fakes; no DB."""

    def setUp(self):
        self.rows = []          # stands in for the tasks table
        self.bumped = []

    def find_open(self, key):
        import enqueue_task
        for row in self.rows:
            if enqueue_task._intent_from_note(row.get("note")) == key:
                return row
        return None

    def insert(self, record, key):
        row = dict(record)
        row.pop("assumptions", None)
        row.pop("intent_key", None)
        row["note"] = im._note_with_intent(row.get("note"), key)
        row["id"] = len(self.rows) + 1
        self.rows.append(row)
        return row["id"]

    def bump(self, existing):
        self.bumped.append(existing.get("id"))
        existing["attempt"] = int(existing.get("attempt") or 0) + 1

    def enqueue(self, slug, project_id="p1"):
        return enq.enqueue_task(
            {"project_id": project_id, "slug": slug, "note": "explore"},
            find_open_by_intent=self.find_open, insert=self.insert, bump=self.bump)

    def test_the_same_intent_enqueued_twice_creates_one_row(self):
        first = self.enqueue("explore-hot-surface")
        second = self.enqueue("explore-hot-surface")
        self.assertEqual(first.action, "created")
        self.assertEqual(second.action, "coalesced")
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.rows[0]["attempt"], 1)

    def test_escalating_the_same_surface_a_hundred_times_creates_one_row(self):
        """The live shape: cont-e8ca57b5 has 100 rows, all from one day."""
        for _ in range(100):
            self.enqueue("cont-e8ca57b5")
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(len(self.bumped), 99)

    def test_fanout_suffixes_collapse_to_one_intent(self):
        """-slice-N / -group-N are decomposition, not distinct intents."""
        self.enqueue("explore-surface-slice-1")
        self.enqueue("explore-surface-slice-2")
        self.assertEqual(len(self.rows), 1)

    def test_distinct_intents_are_not_collapsed(self):
        """The guard must not merge unrelated work."""
        self.enqueue("explore-surface-a")
        self.enqueue("explore-surface-b")
        self.assertEqual(len(self.rows), 2)

    def test_the_same_slug_in_another_project_is_a_separate_intent(self):
        self.enqueue("explore-shared", project_id="p1")
        self.enqueue("explore-shared", project_id="p2")
        self.assertEqual(len(self.rows), 2)

    def test_no_row_is_ever_written_with_an_intent_key_column(self):
        """`tasks` has no such column; writing it is what silently failed."""
        self.enqueue("explore-hot-surface")
        for row in self.rows:
            self.assertNotIn("intent_key", row)
            self.assertIn("note", row)


if __name__ == "__main__":
    unittest.main()
