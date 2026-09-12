#!/usr/bin/env python3
"""Shelf decisions must carry the evidence that produced them.

Origin: the task 'prompt-evolution-bandit' was shelved with the note "shelved by
queue-velocity PID (low EV, integral too high)" and a follow-up task asked WHY.
It could not be answered: the note was a constant f-string with no
interpolation, so no confidence, threshold, integral or depth was ever recorded.

These tests pin the evidence onto the decision so the next such question is
answerable from the row alone.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_velocity  # noqa: E402

BASE = "shelved by queue-velocity PID (low EV, integral too high)"


class ShelveReasonTests(unittest.TestCase):
    def test_keeps_the_original_sentence(self):
        # Existing note-matching downstream must keep working.
        self.assertTrue(queue_velocity._shelve_reason({}).startswith(BASE))

    def test_records_task_confidence(self):
        note = queue_velocity._shelve_reason({"confidence": 0.21})
        self.assertIn("confidence=0.21", note)

    def test_records_null_confidence_distinguishably(self):
        # nullsfirst ordering means a NULL-confidence task is shelved FIRST;
        # "no score" and "low score" are different diagnoses.
        note = queue_velocity._shelve_reason({"confidence": None})
        self.assertIn("confidence=None", note)

    def test_records_controller_evidence(self):
        note = queue_velocity._shelve_reason(
            {"confidence": 0.1},
            {"trigger": "I-action/integral", "integral": 950,
             "integral_threshold": 800, "depth": 803, "effective_depth": 790,
             "shelve_count": 40, "rank": 3})
        for expected in ("trigger=I-action/integral", "integral=950",
                         "integral_threshold=800", "depth=803",
                         "effective_depth=790", "shelve_count=40", "rank=3"):
            self.assertIn(expected, note)

    def test_omits_absent_evidence_keys(self):
        note = queue_velocity._shelve_reason({"confidence": 0.1},
                                             {"integral": 900})
        self.assertIn("integral=900", note)
        self.assertNotIn("depth=", note)

    def test_fail_soft_on_garbage_inputs(self):
        for task in (None, {}, {"confidence": object()}):
            self.assertTrue(queue_velocity._shelve_reason(task).startswith(BASE))
        self.assertTrue(
            queue_velocity._shelve_reason({}, "not-a-dict").startswith(BASE))


class ShelveLowEvTests(unittest.TestCase):
    """The note actually written to the row must carry the evidence."""

    def setUp(self):
        self.updates = []
        self.rows = [
            {"id": "a", "slug": "prompt-evolution-bandit", "confidence": 0.05,
             "project_id": "p1", "pinned": False},
            {"id": "b", "slug": "other-task", "confidence": 0.12,
             "project_id": "p1", "pinned": False},
        ]
        self._saved = {
            "select": queue_velocity.db.select,
            "update": queue_velocity.db.update,
            "recovery": queue_velocity._recovery_action,
        }
        queue_velocity.db.select = lambda *_a, **_k: self.rows
        queue_velocity.db.update = lambda _t, where, values: self.updates.append(
            (where, values))
        queue_velocity._recovery_action = lambda _t: ("shelve", "not recoverable")

    def tearDown(self):
        queue_velocity.db.select = self._saved["select"]
        queue_velocity.db.update = self._saved["update"]
        queue_velocity._recovery_action = self._saved["recovery"]

    def test_written_note_carries_the_evidence(self):
        queue_velocity._shelve_lowest_ev(
            2, evidence={"trigger": "I-action/integral", "integral": 950,
                         "integral_threshold": 800, "depth": 803,
                         "effective_depth": 790})
        self.assertEqual(len(self.updates), 2)
        note = self.updates[0][1]["note"]
        self.assertIn("confidence=0.05", note)
        self.assertIn("integral=950", note)
        self.assertIn("trigger=I-action/integral", note)

    def test_rank_reflects_shelve_order(self):
        queue_velocity._shelve_lowest_ev(2, evidence={"integral": 900})
        self.assertIn("rank=0", self.updates[0][1]["note"])
        self.assertIn("rank=1", self.updates[1][1]["note"])

    def test_state_is_still_shelved(self):
        queue_velocity._shelve_lowest_ev(2, evidence={"integral": 900})
        for _where, values in self.updates:
            self.assertEqual(values["state"], "SHELVED")

    def test_evidence_is_optional(self):
        # Backwards compatible: callers passing nothing still work.
        shelved = queue_velocity._shelve_lowest_ev(2)
        self.assertEqual(shelved, 2)
        self.assertTrue(self.updates[0][1]["note"].startswith(BASE))

    def test_pinned_tasks_are_still_never_shelved(self):
        # Guard against regressing the express-lane protection.
        self.rows[0]["pinned"] = True
        shelved = queue_velocity._shelve_lowest_ev(2, evidence={"integral": 900})
        self.assertEqual(shelved, 1)
        self.assertEqual(len(self.updates), 1)
        self.assertEqual(self.updates[0][0]["id"], "b")

    def test_recovered_tasks_are_still_kept(self):
        queue_velocity._recovery_action = lambda _t: ("recovered", "branch exists")
        self.assertEqual(queue_velocity._shelve_lowest_ev(2, evidence={}), 0)
        self.assertEqual(self.updates, [])

    def test_infra_error_is_still_fail_soft(self):
        queue_velocity._recovery_action = lambda _t: ("infra_error", "db down")
        self.assertEqual(queue_velocity._shelve_lowest_ev(2, evidence={}), 0)
        self.assertEqual(self.updates, [])


if __name__ == "__main__":
    unittest.main()
