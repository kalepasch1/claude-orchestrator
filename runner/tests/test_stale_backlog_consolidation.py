#!/usr/bin/env python3
"""Edge cases of `consolidate_duplicates` — the consolidation half of stale recovery.

`runner/tests/test_stale_backlog_recovery.py` has 46 green cases, five of them on
consolidation: duplicate detection, keep-oldest, the MAX_CONSOLIDATIONS limit, empty
input, single task. What none of them touch is how the grouping decides what counts
as a duplicate at all — and that logic contains a default that can cancel work:

    if str(task.get("state") or "RUNNING").upper() != "RUNNING":
        continue

A task row with **no state field** is therefore treated as RUNNING, becomes eligible
for consolidation, and can be handed to `build_recovery_action(..., "cancel")`. That
is a defensible default (a row mid-write has no state yet, and leaving a real
duplicate running is its own failure) but it is load-bearing and undefended: nothing
asserted it, so a future "tighten the filter" change could silently start cancelling
in-flight work, or silently stop consolidating rows that need it.

The keeper rule has a second undefended edge: `started_at` that will not parse sorts
to `float("inf")` so it "never wins keeper" — but when EVERY row in a group is
unparseable they all tie at infinity, and Python's stable sort makes the keeper
whichever row arrived first. Arbitrary, but deterministic; worth pinning either way,
because the alternative to a pinned arbitrary rule is an unpinned one.

Run: python3 -m unittest runner.tests.test_stale_backlog_consolidation -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import stale_backlog_recovery as sbr


def _t(task_id, slug="dup", started_at=100.0, state="RUNNING", **extra):
    row = {"id": task_id, "slug": slug, "started_at": started_at, **extra}
    if state is not None:
        row["state"] = state
    return row


class StateFilterTest(unittest.TestCase):
    """Which rows are even considered a duplicate."""

    def test_missing_state_is_treated_as_running(self):
        # The load-bearing default. If this ever flips, in-flight rows mid-write
        # stop being consolidated — or start being cancelled.
        out = sbr.consolidate_duplicates([_t("a", started_at=1.0, state=None),
                                          _t("b", started_at=2.0, state=None)])
        self.assertIn("dup", out)
        self.assertEqual(out["dup"]["keeper"]["id"], "a")

    def test_empty_string_state_is_treated_as_running(self):
        out = sbr.consolidate_duplicates([_t("a", started_at=1.0, state=""),
                                          _t("b", started_at=2.0, state="")])
        self.assertIn("dup", out)

    def test_state_match_is_case_insensitive(self):
        out = sbr.consolidate_duplicates([_t("a", started_at=1.0, state="running"),
                                          _t("b", started_at=2.0, state="Running")])
        self.assertIn("dup", out)

    def test_non_running_states_are_not_consolidated(self):
        for state in ("DONE", "QUEUED", "MERGED", "CANCELLED", "STALE"):
            out = sbr.consolidate_duplicates([_t("a", started_at=1.0, state=state),
                                              _t("b", started_at=2.0, state=state)])
            self.assertEqual(out, {}, state)

    def test_a_done_sibling_does_not_make_a_duplicate(self):
        # One RUNNING + one DONE on the same slug is not two concurrent runs.
        out = sbr.consolidate_duplicates([_t("a", started_at=1.0, state="RUNNING"),
                                          _t("b", started_at=2.0, state="DONE")])
        self.assertEqual(out, {})

    def test_only_running_siblings_are_cancelled(self):
        out = sbr.consolidate_duplicates([
            _t("a", started_at=1.0, state="RUNNING"),
            _t("b", started_at=2.0, state="RUNNING"),
            _t("c", started_at=3.0, state="DONE"),
        ])
        self.assertEqual([t["id"] for t in out["dup"]["to_cancel"]], ["b"])


class MalformedInputTest(unittest.TestCase):
    def test_non_dict_entries_are_skipped(self):
        out = sbr.consolidate_duplicates(["string", 42, None, ["list"],
                                          _t("a", started_at=1.0),
                                          _t("b", started_at=2.0)])
        self.assertEqual(out["dup"]["keeper"]["id"], "a")

    def test_rows_without_a_slug_are_skipped(self):
        out = sbr.consolidate_duplicates([{"id": "a", "state": "RUNNING"},
                                          {"id": "b", "state": "RUNNING"}])
        self.assertEqual(out, {})

    def test_none_input_is_fail_soft(self):
        self.assertEqual(sbr.consolidate_duplicates(None), {})

    def test_different_slugs_are_never_grouped(self):
        out = sbr.consolidate_duplicates([_t("a", slug="one"), _t("b", slug="two")])
        self.assertEqual(out, {})

    def test_multiple_slugs_consolidate_independently(self):
        out = sbr.consolidate_duplicates([
            _t("a1", slug="one", started_at=1.0), _t("a2", slug="one", started_at=2.0),
            _t("b1", slug="two", started_at=5.0), _t("b2", slug="two", started_at=4.0),
        ])
        self.assertEqual(out["one"]["keeper"]["id"], "a1")
        self.assertEqual(out["two"]["keeper"]["id"], "b2")


class KeeperOrderingTest(unittest.TestCase):
    """Oldest run is the keeper; everything younger is cancellable."""

    def test_oldest_started_at_is_the_keeper(self):
        out = sbr.consolidate_duplicates([_t("young", started_at=99.0),
                                          _t("old", started_at=1.0),
                                          _t("mid", started_at=50.0)])
        self.assertEqual(out["dup"]["keeper"]["id"], "old")

    def test_cancel_list_is_age_ordered(self):
        out = sbr.consolidate_duplicates([_t("c", started_at=30.0),
                                          _t("a", started_at=10.0),
                                          _t("b", started_at=20.0)])
        self.assertEqual([t["id"] for t in out["dup"]["to_cancel"]], ["b", "c"])

    def test_numeric_string_started_at_is_parsed(self):
        out = sbr.consolidate_duplicates([_t("a", started_at="1.0"),
                                          _t("b", started_at="2.0")])
        self.assertEqual(out["dup"]["keeper"]["id"], "a")

    def test_unparseable_started_at_never_wins_keeper(self):
        out = sbr.consolidate_duplicates([_t("bad", started_at="not-a-time"),
                                          _t("good", started_at=5.0)])
        self.assertEqual(out["dup"]["keeper"]["id"], "good")

    def test_missing_started_at_never_wins_keeper(self):
        rows = [{"id": "bad", "slug": "dup", "state": "RUNNING"},
                _t("good", started_at=5.0)]
        self.assertEqual(sbr.consolidate_duplicates(rows)["dup"]["keeper"]["id"], "good")

    def test_all_unparseable_falls_back_to_input_order(self):
        # Every row ties at +inf; the stable sort keeps the first as keeper. Arbitrary,
        # but deterministic — and an unpinned arbitrary rule is the worse option.
        out = sbr.consolidate_duplicates([_t("first", started_at=None),
                                          _t("second", started_at=None)])
        self.assertEqual(out["dup"]["keeper"]["id"], "first")


class ConsolidationLimitTest(unittest.TestCase):
    def test_at_most_max_consolidations_are_marked(self):
        rows = [_t(f"t{i}", started_at=float(i)) for i in range(sbr.MAX_CONSOLIDATIONS + 5)]
        out = sbr.consolidate_duplicates(rows)
        self.assertEqual(len(out["dup"]["to_cancel"]), sbr.MAX_CONSOLIDATIONS)

    def test_the_truncation_keeps_the_oldest_of_the_younger_runs(self):
        # Truncation must not become "whichever happened to be last in the list":
        # the oldest duplicates are the ones most worth cancelling first.
        rows = [_t(f"t{i}", started_at=float(i)) for i in range(sbr.MAX_CONSOLIDATIONS + 5)]
        out = sbr.consolidate_duplicates(list(reversed(rows)))
        expected = [f"t{i}" for i in range(1, sbr.MAX_CONSOLIDATIONS + 1)]
        self.assertEqual([t["id"] for t in out["dup"]["to_cancel"]], expected)

    def test_the_keeper_is_never_in_the_cancel_list(self):
        rows = [_t(f"t{i}", started_at=float(i)) for i in range(6)]
        out = sbr.consolidate_duplicates(rows)
        keeper_id = out["dup"]["keeper"]["id"]
        self.assertNotIn(keeper_id, [t["id"] for t in out["dup"]["to_cancel"]])

    def test_max_consolidations_is_at_least_one(self):
        self.assertGreaterEqual(sbr.MAX_CONSOLIDATIONS, 1)


class ActionHandoffTest(unittest.TestCase):
    """Consolidation output must be usable by build_recovery_action."""

    def test_every_cancellable_row_builds_a_cancel_action(self):
        out = sbr.consolidate_duplicates([_t("a", started_at=1.0), _t("b", started_at=2.0)])
        for row in out["dup"]["to_cancel"]:
            action = sbr.build_recovery_action(row, "cancel", reason="duplicate_run")
            self.assertIsNotNone(action)
            self.assertEqual(action["target_state"], "CANCELLED")
            self.assertEqual(action["slug"], "dup")

    def test_the_keeper_is_not_given_a_cancel_action(self):
        out = sbr.consolidate_duplicates([_t("a", started_at=1.0), _t("b", started_at=2.0)])
        self.assertEqual(out["dup"]["keeper"]["id"], "a")
        self.assertEqual(len(out["dup"]["to_cancel"]), 1)

    def test_returned_rows_are_the_original_objects_not_copies(self):
        original = _t("a", started_at=1.0)
        out = sbr.consolidate_duplicates([original, _t("b", started_at=2.0)])
        self.assertIs(out["dup"]["keeper"], original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
