#!/usr/bin/env python3
"""The cost SLO must measure a TIME window, not "the last N rows".

`cost_slo` computes $/merge per app and drives `cost_bias`, which biases model routing
toward cheaper tiers. It read `SLO_WINDOW` (default 300) OUTCOMES ordered newest-first —
a ROW COUNT, not a time window. So "the last 300 outcomes" was about an hour on a busy
project and several months on a quiet one, the same `target_usd_per_merge` meant different
things per project, and the loop tightened or relaxed a routing knob by comparing
incomparable windows.

It was also saturating in production. merge-train logs carry repeated
"TRUNCATED SCAN cost_slo.py:22 -> outcomes returned exactly its limit (300)", so on the
busiest projects — precisely the ones whose cost matters — the window silently shrank to
whatever the most recent 300 rows happened to cover, and a spike in ACTIVITY was
indistinguishable from a spike in COST.

Proof: python3 -m pytest runner/tests/test_cost_slo_window.py -q
"""
import datetime
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cost_slo  # noqa: E402


def _outcome(usd=1.0, integrated=True, created_at="2026-08-20T00:00:00+00:00"):
    return {"usd": usd, "integrated": integrated, "created_at": created_at}


class _DB:
    def __init__(self, outcomes=(), projects=(), slos=()):
        self.outcomes = list(outcomes)
        self.projects = list(projects)
        self.slos = list(slos)
        self.queries = []
        self.updates = []
        self.inserts = []

    def select(self, table, params=None):
        self.queries.append((table, dict(params or {})))
        if table == "outcomes":
            return list(self.outcomes)
        if table == "projects":
            return list(self.projects)
        if table == "cost_slos":
            return list(self.slos)
        return []

    def update(self, table, match, patch):
        self.updates.append((table, match, patch))
        return [match]

    def insert(self, table, row):
        self.inserts.append((table, row))
        return row


class TestWindowIsTimeBased(unittest.TestCase):
    def test_the_query_filters_on_created_at(self):
        db = _DB(outcomes=[_outcome()])
        with patch.object(cost_slo, "db", db):
            cost_slo._actual_cpm("beethoven")
        params = db.queries[0][1]
        self.assertIn("created_at", params)
        self.assertTrue(params["created_at"].startswith("gte."))

    def test_a_wider_window_asks_for_an_earlier_cutoff(self):
        db = _DB(outcomes=[_outcome()])
        with patch.object(cost_slo, "db", db):
            cost_slo._actual_cpm("beethoven", hours=1)
            cost_slo._actual_cpm("beethoven", hours=720)
        self.assertLess(db.queries[1][1]["created_at"], db.queries[0][1]["created_at"])

    def test_the_row_limit_is_a_safety_bound_not_the_window(self):
        self.assertLessEqual(cost_slo.WINDOW, 1000,
                             "a limit above the PostgREST cap is fiction")
        self.assertGreater(cost_slo.WINDOW_HOURS, 0)

    def test_the_measured_window_is_reported(self):
        db = _DB(outcomes=[_outcome(created_at="2026-08-01T00:00:00+00:00"),
                           _outcome(created_at="2026-08-20T00:00:00+00:00")])
        with patch.object(cost_slo, "db", db):
            measured = cost_slo._actual_cpm("beethoven")
        self.assertEqual(measured["samples"], 2)
        self.assertEqual(measured["since"], "2026-08-01T00:00:00+00:00")
        self.assertEqual(measured["window_hours"], cost_slo.WINDOW_HOURS)

    def test_cutoff_is_fail_soft_on_junk(self):
        for bad in (None, "abc", 0, -5):
            self.assertIsInstance(cost_slo._cutoff_iso(bad), str, bad)

    def test_cutoff_is_in_the_past(self):
        cutoff = cost_slo._cutoff_iso(1)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.assertLess(cutoff, now)


class TestTruncationIsVisible(unittest.TestCase):
    def test_a_full_page_is_reported_as_truncated(self):
        db = _DB(outcomes=[_outcome() for _ in range(cost_slo.WINDOW)])
        with patch.object(cost_slo, "db", db):
            measured = cost_slo._actual_cpm("beethoven")
        self.assertTrue(measured["truncated"],
                        "a decision on a silently-shortened window looked complete")

    def test_a_partial_page_is_not_truncated(self):
        db = _DB(outcomes=[_outcome() for _ in range(3)])
        with patch.object(cost_slo, "db", db):
            self.assertFalse(cost_slo._actual_cpm("beethoven")["truncated"])

    def test_truncation_reaches_the_action(self):
        db = _DB(outcomes=[_outcome(usd=99.0) for _ in range(cost_slo.WINDOW)],
                 projects=[{"id": "p1", "name": "beethoven", "cost_bias": 0}])
        with patch.object(cost_slo, "db", db):
            actions = cost_slo.run(apply=False)
        self.assertTrue(actions)
        self.assertTrue(actions[0]["truncated"])

    def test_the_action_carries_the_window_it_decided_on(self):
        db = _DB(outcomes=[_outcome(usd=99.0)],
                 projects=[{"id": "p1", "name": "beethoven", "cost_bias": 0}])
        with patch.object(cost_slo, "db", db):
            actions = cost_slo.run(apply=False)
        self.assertEqual(actions[0]["window_hours"], cost_slo.WINDOW_HOURS)
        self.assertEqual(actions[0]["samples"], 1)


class TestArithmeticUnchanged(unittest.TestCase):
    """Preserve existing behavior: only the window changed, not the economics."""

    def test_cpm_is_spend_over_merges(self):
        db = _DB(outcomes=[_outcome(usd=3.0, integrated=True),
                           _outcome(usd=1.0, integrated=False)])
        with patch.object(cost_slo, "db", db):
            measured = cost_slo._actual_cpm("beethoven")
        self.assertEqual(measured["spend"], 4.0)
        self.assertEqual(measured["merges"], 1)
        self.assertEqual(measured["cpm"], 4.0)

    def test_zero_merges_reports_spend_with_no_cpm(self):
        db = _DB(outcomes=[_outcome(usd=5.0, integrated=False)])
        with patch.object(cost_slo, "db", db):
            measured = cost_slo._actual_cpm("beethoven")
        self.assertIsNone(measured["cpm"])
        self.assertEqual(measured["spend"], 5.0)

    def test_no_rows_means_no_signal(self):
        with patch.object(cost_slo, "db", _DB(outcomes=[])):
            self.assertIsNone(cost_slo._actual_cpm("beethoven"))

    def test_an_app_with_no_signal_is_skipped_not_penalised(self):
        db = _DB(outcomes=[], projects=[{"id": "p1", "name": "quiet", "cost_bias": 0}])
        with patch.object(cost_slo, "db", db):
            self.assertEqual(cost_slo.run(apply=False), [])
        self.assertEqual(db.updates, [])

    def test_over_target_tightens_the_bias(self):
        db = _DB(outcomes=[_outcome(usd=50.0)],
                 projects=[{"id": "p1", "name": "beethoven", "cost_bias": 0}])
        with patch.object(cost_slo, "db", db):
            actions = cost_slo.run(apply=False)
        self.assertEqual(actions[0]["bias"], "0->1")

    def test_under_target_relaxes_the_bias(self):
        db = _DB(outcomes=[_outcome(usd=0.01)],
                 projects=[{"id": "p1", "name": "beethoven", "cost_bias": 2}])
        with patch.object(cost_slo, "db", db):
            actions = cost_slo.run(apply=False)
        self.assertEqual(actions[0]["bias"], "2->1")

    def test_apply_false_writes_nothing(self):
        db = _DB(outcomes=[_outcome(usd=50.0)],
                 projects=[{"id": "p1", "name": "beethoven", "cost_bias": 0}])
        with patch.object(cost_slo, "db", db):
            cost_slo.run(apply=False)
        self.assertEqual(db.updates, [])

    def test_apply_true_writes_the_bias(self):
        db = _DB(outcomes=[_outcome(usd=50.0)],
                 projects=[{"id": "p1", "name": "beethoven", "cost_bias": 0}])
        with patch.object(cost_slo, "db", db):
            cost_slo.run(apply=True)
        self.assertEqual(db.updates[0][2], {"cost_bias": 1})

    def test_a_hard_ceiling_breach_files_an_approval(self):
        db = _DB(outcomes=[_outcome(usd=50.0)],
                 projects=[{"id": "p1", "name": "beethoven", "cost_bias": 0}],
                 slos=[{"app": "beethoven", "target_usd_per_merge": 1.0,
                        "hard_ceiling_usd_per_merge": 10.0}])
        with patch.object(cost_slo, "db", db):
            cost_slo.run(apply=False)
        self.assertTrue(any(t == "approvals" for t, _ in db.inserts))


if __name__ == "__main__":
    unittest.main()
