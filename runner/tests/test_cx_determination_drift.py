#!/usr/bin/env python3
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cx_determination_drift as drift


DETS = [
    {"id": "d1", "title": "Old GO", "body": "ship it", "recommendation": "GO",
     "consensus_pct": 0.9, "created_at": "2026-06-01T00:00:00Z"},
    {"id": "d2", "title": "Old HOLD", "body": "pause it", "recommendation": "HOLD",
     "consensus_pct": 0.8, "created_at": "2026-06-01T00:00:00Z"},
]


class TestDeterminationDrift(unittest.TestCase):
    def test_opens_inbox_alert_for_recommendation_change(self):
        inserted = []

        def select(table, params=None):
            if table == "determinations":
                return DETS[:1]
            if table == "inbox":
                return []
            return []

        def replay(det_id):
            self.assertEqual(det_id, "d1")
            return {
                "then": {"recommendation": "GO", "consensus_pct": 0.9},
                "now": {"recommendation": "HOLD", "consensus_pct": 0.88},
                "changed": True,
                "note": "outcome moved",
            }

        with patch.object(drift.db, "select", side_effect=select), \
                patch.object(drift.db, "insert", side_effect=lambda t, r: inserted.append((t, r))), \
                patch.object(drift, "replay_determination", side_effect=replay):
            self.assertEqual(drift.run(sample_limit=1, alert_limit=3, min_age_days=7), 1)

        self.assertEqual(inserted[0][0], "inbox")
        self.assertEqual(inserted[0][1]["kind"], "drift")
        self.assertEqual(inserted[0][1]["status"], "unread")
        self.assertIn("determination_id=d1", inserted[0][1]["body"])

    def test_opens_alert_for_consensus_move_without_recommendation_change(self):
        inserted = []

        def select(table, params=None):
            return DETS[:1] if table == "determinations" else []

        with patch.object(drift.db, "select", side_effect=select), \
                patch.object(drift.db, "insert", side_effect=lambda t, r: inserted.append((t, r))), \
                patch.object(drift, "replay_determination", return_value={
                    "then": {"recommendation": "GO", "consensus_pct": 0.9},
                    "now": {"recommendation": "GO", "consensus_pct": 0.79},
                    "changed": False,
                }):
            self.assertEqual(drift.run(sample_limit=1, alert_limit=3, min_age_days=7), 1)
        self.assertEqual(len(inserted), 1)

    def test_no_alert_when_outcome_holds(self):
        inserted = []

        def select(table, params=None):
            return DETS[:1] if table == "determinations" else []

        with patch.object(drift.db, "select", side_effect=select), \
                patch.object(drift.db, "insert", side_effect=lambda t, r: inserted.append((t, r))), \
                patch.object(drift, "replay_determination", return_value={
                    "then": {"recommendation": "GO", "consensus_pct": 0.9},
                    "now": {"recommendation": "GO", "consensus_pct": 0.85},
                    "changed": False,
                }):
            self.assertEqual(drift.run(sample_limit=1, alert_limit=3, min_age_days=7), 0)
        self.assertEqual(inserted, [])

    def test_alerts_are_bounded(self):
        inserted = []

        def select(table, params=None):
            return DETS if table == "determinations" else []

        with patch.object(drift.db, "select", side_effect=select), \
                patch.object(drift.db, "insert", side_effect=lambda t, r: inserted.append((t, r))), \
                patch.object(drift, "replay_determination", return_value={
                    "then": {"recommendation": "GO", "consensus_pct": 0.9},
                    "now": {"recommendation": "HOLD", "consensus_pct": 0.9},
                    "changed": True,
                }) as replay:
            self.assertEqual(drift.run(sample_limit=2, alert_limit=1, min_age_days=7), 1)
        self.assertEqual(replay.call_count, 1)
        self.assertEqual(len(inserted), 1)

    def test_skips_missing_evidence_and_existing_alerts(self):
        rows = [
            {"id": "empty", "title": "", "body": "", "recommendation": "GO"},
            DETS[0],
        ]

        def select(table, params=None):
            if table == "determinations":
                return rows
            if table == "inbox":
                return [{"id": "already"}]
            return []

        with patch.object(drift.db, "select", side_effect=select), \
                patch.object(drift.db, "insert") as insert, \
                patch.object(drift, "replay_determination") as replay:
            self.assertEqual(drift.run(sample_limit=2, alert_limit=1, min_age_days=7), 0)
        replay.assert_not_called()
        insert.assert_not_called()

    def test_replay_context_suppresses_committee_writes_then_restores(self):
        calls = []
        original_insert = drift.committees.db.insert

        def fake_insert(*args, **kwargs):
            calls.append((args, kwargs))

        drift.committees.db.insert = fake_insert
        try:
            with drift._readonly_committee_replay():
                drift.committees.db.insert("committee_reviews", {"x": 1})
            drift.committees.db.insert("after", {"x": 2})
        finally:
            drift.committees.db.insert = original_insert

        self.assertEqual(calls, [(("after", {"x": 2}), {})])


if __name__ == "__main__":
    unittest.main()
