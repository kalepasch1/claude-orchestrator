#!/usr/bin/env python3
"""legal_triage is a 300-second periodic job that could do nothing, forever, twice over.

STARVATION. run() selected `limit` pending legal cards in server-chosen order and then
skipped, in Python, any that already carried a legal_risk_level. Elevated and novel cards
stay pending on purpose — that is what the triage is for — so they accumulate, and they
are precisely the rows that are already classified. Once `limit` of them could fill a
page, every run fetched 40 finished cards, skipped all 40, classified nothing, and
printed "classified 0" while new cards sat unreachable behind them.

CRASH LOOP. The db.update was the one unguarded call in a function where every other
failure degrades. A single card whose write fails raised out of run(), killed the
periodic job, and the scheduler restarted it 300s later onto the same card. Ordering the
drain oldest-first makes that strictly worse: the poison row sits permanently at the
front.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import legal_triage


def _card(i, level=None):
    return {"id": f"a{i}", "title": f"card {i}", "why": "boilerplate ToS update",
            "legal_risk_level": level}


class _Db:
    """Captures the query legal_triage issues, and the writes it attempts."""

    def __init__(self, rows, fail_ids=()):
        self.rows, self.fail_ids = rows, set(fail_ids)
        self.queries, self.updates = [], []

    def select(self, table, params):
        self.queries.append(params)
        if params.get("select") == "id":          # the backlog probe
            return [r for r in self.rows if not r.get("legal_risk_level")]
        rows = self.rows
        if params.get("legal_risk_level") == "is.null":
            rows = [r for r in rows if not r.get("legal_risk_level")]
        return rows[:int(params.get("limit", len(rows) or 1))]

    def update(self, table, where, values):
        if where.get("id") in self.fail_ids:
            raise RuntimeError("row is poison")
        self.updates.append((where.get("id"), values))
        return [{"id": where.get("id")}]


class DrainReachesTheBacklog(unittest.TestCase):

    def setUp(self):
        # Keep the model out of it: legal_filter decides, deterministically.
        patcher = mock.patch.object(legal_triage.legal_filter,
                                    "requires_owner_approval", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_already_classified_cards_cannot_crowd_out_new_ones(self):
        """The regression. 40 classified cards ahead of one new card used to mean the new
        card was never reached, on every run, forever."""
        rows = [_card(i, "elevated") for i in range(40)] + [_card(99)]
        db = _Db(rows)
        with mock.patch.object(legal_triage, "db", db):
            out = legal_triage.run(limit=40)
        self.assertEqual(out["tagged"], 1, "the unclassified card was not reached")
        self.assertEqual([u[0] for u in db.updates], ["a99"])

    def test_the_unclassified_filter_is_pushed_into_the_query(self):
        """Filtering after the LIMIT is what made starvation possible at all."""
        db = _Db([_card(1)])
        with mock.patch.object(legal_triage, "db", db):
            legal_triage.run(limit=40)
        self.assertEqual(db.queries[0].get("legal_risk_level"), "is.null")

    def test_the_drain_is_oldest_first(self):
        db = _Db([_card(1)])
        with mock.patch.object(legal_triage, "db", db):
            legal_triage.run(limit=40)
        self.assertEqual(db.queries[0].get("order"), "created_at.asc")

    def test_the_remaining_backlog_is_reported(self):
        """A queue that cannot keep up should say so, not print a busy-looking zero."""
        db = _Db([_card(i) for i in range(5)])
        with mock.patch.object(legal_triage, "db", db):
            out = legal_triage.run(limit=2)
        self.assertIn("backlog", out)


class OnePoisonRowDoesNotKillTheJob(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(legal_triage.legal_filter,
                                    "requires_owner_approval", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_failing_update_does_not_raise_out_of_run(self):
        """The crash loop: this used to propagate, kill the periodic job, and be retried
        onto the same card every 300 seconds."""
        db = _Db([_card(1), _card(2), _card(3)], fail_ids={"a1"})
        with mock.patch.object(legal_triage, "db", db):
            out = legal_triage.run(limit=10)   # must not raise
        self.assertEqual(out["tagged"], 2)

    def test_work_behind_the_poison_row_still_gets_done(self):
        """Head-of-line: everything after the bad card used to be unreachable."""
        db = _Db([_card(1), _card(2), _card(3)], fail_ids={"a1"})
        with mock.patch.object(legal_triage, "db", db):
            legal_triage.run(limit=10)
        self.assertEqual([u[0] for u in db.updates], ["a2", "a3"])

    def test_the_failure_is_recorded_not_swallowed(self):
        """A drain that stalls invisibly is the failure this wave exists to end."""
        db = _Db([_card(1), _card(2)], fail_ids={"a1"})
        with mock.patch.object(legal_triage, "db", db):
            out = legal_triage.run(limit=10)
        self.assertEqual([f[0] for f in out["failed"]], ["a1"])

    def test_a_card_that_failed_to_write_is_not_counted_as_cleared(self):
        """Reporting a routine auto-approval that never landed would be a false record
        of a legal decision."""
        with mock.patch.object(legal_triage.legal_filter,
                               "requires_owner_approval", return_value=False), \
             mock.patch.dict(os.environ, {"LEGAL_AUTO_APPROVE_ROUTINE": "true"}):
            db = _Db([_card(1)], fail_ids={"a1"})
            with mock.patch.object(legal_triage, "db", db), \
                 mock.patch.object(legal_triage, "AUTO_APPROVE", True), \
                 mock.patch.dict(sys.modules, {"model_policy": None, "model_gateway": None}):
                out = legal_triage.run(limit=10)
        self.assertEqual(out["cleared"], 0)
        self.assertEqual(out["tagged"], 0)


class ConservativeClassificationIsUnchanged(unittest.TestCase):
    """The safety property this module exists for must survive the drain fix."""

    def test_a_hard_regulatory_card_is_forced_to_novel_and_never_auto_cleared(self):
        db = _Db([_card(1)])
        with mock.patch.object(legal_triage.legal_filter,
                               "requires_owner_approval", return_value=True), \
             mock.patch.object(legal_triage, "db", db), \
             mock.patch.object(legal_triage, "AUTO_APPROVE", True):
            out = legal_triage.run(limit=10)
        self.assertEqual(db.updates[0][1]["legal_risk_level"], "novel")
        self.assertNotIn("status", db.updates[0][1])
        self.assertEqual(out["cleared"], 0)


if __name__ == "__main__":
    unittest.main()
