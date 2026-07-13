import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cx_determination_drift


def _det(det_id, title="Some determination", app="beethoven"):
    return {"id": det_id, "title": title, "recommendation": "GO", "consensus_pct": 0.8, "app": app}


class NoDriftTest(unittest.TestCase):
    def test_no_alert_when_recommendation_and_consensus_stable(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [],                    # _already_checked_ids: determination_outcomes
            [_det("d1")],          # _sample_older_determinations: determinations
        ]
        fake_committees = MagicMock()
        fake_committees.replay_determination.return_value = {
            "then": {"recommendation": "GO", "consensus_pct": 0.8},
            "now": {"recommendation": "GO", "consensus_pct": 0.82},
            "changed": False,
            "note": "outcome holds",
        }

        with patch.object(cx_determination_drift, "db", fake_db), \
             patch.object(cx_determination_drift, "committees", fake_committees):
            out = cx_determination_drift.run()

        self.assertEqual(out["checked"], 1)
        self.assertEqual(out["drifted"], 0)
        inbox_calls = [c for c in fake_db.insert.call_args_list if c.args[0] == "inbox"]
        self.assertEqual(len(inbox_calls), 0)


class RecommendationFlipTest(unittest.TestCase):
    def test_drift_alert_opened_when_recommendation_flips(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [],
            [_det("d2")],
        ]
        fake_committees = MagicMock()
        fake_committees.replay_determination.return_value = {
            "then": {"recommendation": "GO", "consensus_pct": 0.8},
            "now": {"recommendation": "HOLD", "consensus_pct": 0.8},
            "changed": True,
            "note": "outcome moved",
        }

        with patch.object(cx_determination_drift, "db", fake_db), \
             patch.object(cx_determination_drift, "committees", fake_committees):
            out = cx_determination_drift.run()

        self.assertEqual(out["drifted"], 1)
        inbox_calls = [c for c in fake_db.insert.call_args_list if c.args[0] == "inbox"]
        self.assertEqual(len(inbox_calls), 1)
        self.assertEqual(inbox_calls[0].args[1]["kind"], "drift")


class ConsensusMoveTest(unittest.TestCase):
    def test_drift_alert_opened_when_consensus_moves_by_at_least_point_one(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [],
            [_det("d3")],
        ]
        fake_committees = MagicMock()
        fake_committees.replay_determination.return_value = {
            "then": {"recommendation": "GO", "consensus_pct": 0.8},
            "now": {"recommendation": "GO", "consensus_pct": 0.9},
            "changed": True,
            "note": "outcome moved",
        }

        with patch.object(cx_determination_drift, "db", fake_db), \
             patch.object(cx_determination_drift, "committees", fake_committees):
            out = cx_determination_drift.run()

        self.assertEqual(out["drifted"], 1)
        inbox_calls = [c for c in fake_db.insert.call_args_list if c.args[0] == "inbox"]
        self.assertEqual(len(inbox_calls), 1)

    def test_no_alert_when_consensus_moves_by_less_than_point_one(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [],
            [_det("d4")],
        ]
        fake_committees = MagicMock()
        fake_committees.replay_determination.return_value = {
            "then": {"recommendation": "GO", "consensus_pct": 0.8},
            "now": {"recommendation": "GO", "consensus_pct": 0.85},
            "changed": False,
            "note": "outcome holds",
        }

        with patch.object(cx_determination_drift, "db", fake_db), \
             patch.object(cx_determination_drift, "committees", fake_committees):
            out = cx_determination_drift.run()

        self.assertEqual(out["drifted"], 0)
        inbox_calls = [c for c in fake_db.insert.call_args_list if c.args[0] == "inbox"]
        self.assertEqual(len(inbox_calls), 0)


class BoundedSamplingTest(unittest.TestCase):
    def test_only_a_bounded_number_are_processed_even_if_more_exist(self):
        many_dets = [_det(f"d{i}") for i in range(50)]
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [],         # nothing already checked
            many_dets,  # far more than MAX_PER_RUN available
        ]
        fake_committees = MagicMock()
        fake_committees.replay_determination.return_value = {
            "then": {"recommendation": "GO", "consensus_pct": 0.8},
            "now": {"recommendation": "GO", "consensus_pct": 0.8},
            "changed": False,
            "note": "outcome holds",
        }

        with patch.object(cx_determination_drift, "db", fake_db), \
             patch.object(cx_determination_drift, "committees", fake_committees):
            out = cx_determination_drift.run()

        self.assertLessEqual(out["checked"], cx_determination_drift.MAX_PER_RUN)
        self.assertEqual(fake_committees.replay_determination.call_count,
                          cx_determination_drift.MAX_PER_RUN)


class FailSoftTest(unittest.TestCase):
    def test_one_bad_determination_does_not_stop_others_or_crash_run(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [],
            [_det("bad1"), _det("good1")],
        ]
        fake_committees = MagicMock()

        def _replay(det_id):
            if det_id == "bad1":
                raise RuntimeError("boom")
            return {
                "then": {"recommendation": "GO", "consensus_pct": 0.8},
                "now": {"recommendation": "HOLD", "consensus_pct": 0.8},
                "changed": True,
                "note": "outcome moved",
            }

        fake_committees.replay_determination.side_effect = _replay

        with patch.object(cx_determination_drift, "db", fake_db), \
             patch.object(cx_determination_drift, "committees", fake_committees):
            out = cx_determination_drift.run()  # must not raise

        self.assertEqual(out["checked"], 1)
        self.assertEqual(out["drifted"], 1)
        inbox_calls = [c for c in fake_db.insert.call_args_list if c.args[0] == "inbox"]
        self.assertEqual(len(inbox_calls), 1)


if __name__ == "__main__":
    unittest.main()
