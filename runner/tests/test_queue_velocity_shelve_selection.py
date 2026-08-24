"""The I-action must shelve the CHEAPEST queued work, not an arbitrary slice of it.

The bug these tests pin, measured on the live queue: `confidence` is NULL for the entire
head of the QUEUED set, so ordering by `confidence.asc.nullsfirst` alone left every
candidate TIED and the server broke the tie arbitrarily. "Shelve the lowest-EV work" was
in practice "shelve an arbitrary slice" — which is how
dropbox-pareto-life-goal-autonomy-stack-p6-earnings-only-interface reached attempt 22
while never-attempted tasks sat beside it untouched: each shelve discarded its 22 attempts
of spend, it was recovered, and it was re-selected on the next pass.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import queue_velocity


class ShelveSelectionTest(unittest.TestCase):

    def _run(self, tasks, count=10, ceiling=None):
        """Run one shelve pass over *tasks*. Returns (shelved_ids, select_params)."""
        seen = {}
        updates = []

        def fake_select(table, params):
            seen.update(params)
            return list(tasks)

        def fake_update(table, where, patch_):
            updates.append((where.get("id"), patch_.get("state")))
            return {}

        ceiling = queue_velocity.SHELVE_ATTEMPT_CEILING if ceiling is None else ceiling
        with patch.object(queue_velocity.db, "select", fake_select), \
             patch.object(queue_velocity.db, "update", fake_update), \
             patch.object(queue_velocity, "SHELVE_ATTEMPT_CEILING", ceiling), \
             patch.object(queue_velocity, "_recovery_action", return_value=("shelve", "n/a")):
            queue_velocity._shelve_lowest_ev(count)
        return [i for i, state in updates if state == "SHELVED"], seen

    # ── the ordering defect ──────────────────────────────────────────────────

    def test_attempt_is_the_tiebreak_when_confidence_is_null(self):
        """Without this the NULL block has no order at all and the server picks."""
        _shelved, params = self._run([])
        self.assertEqual(params.get("order"), "confidence.asc.nullsfirst,attempt.asc")

    def test_attempt_is_actually_selected_from_the_db(self):
        """A sort key that is never fetched cannot be enforced client-side either."""
        _shelved, params = self._run([])
        self.assertIn("attempt", params.get("select", ""))

    # ── the ceiling ──────────────────────────────────────────────────────────

    def test_the_most_attempted_task_is_not_shelved(self):
        # The concrete case: attempt 22 is the most expensive thing in the queue, so it is
        # the last thing shelving should discard.
        shelved, _ = self._run([
            {"id": "cheap", "slug": "never-tried", "confidence": None, "attempt": 0},
            {"id": "dear", "slug": "p6-earnings-only-interface", "confidence": None,
             "attempt": 22},
        ])
        self.assertIn("cheap", shelved)
        self.assertNotIn("dear", shelved)

    def test_a_task_exactly_at_the_ceiling_is_still_shelvable(self):
        # Strictly greater-than: the ceiling is the last shelvable attempt count, not the
        # first refused one. An off-by-one here silently protects a whole extra tier.
        shelved, _ = self._run(
            [{"id": "at", "slug": "at-ceiling", "confidence": None, "attempt": 3}], ceiling=3)
        self.assertEqual(shelved, ["at"])
        shelved, _ = self._run(
            [{"id": "over", "slug": "over-ceiling", "confidence": None, "attempt": 4}], ceiling=3)
        self.assertEqual(shelved, [])

    def test_the_ceiling_is_env_tunable_like_every_other_threshold(self):
        self.assertIsInstance(queue_velocity.SHELVE_ATTEMPT_CEILING, int)
        with patch.dict(os.environ, {"ORCH_QV_SHELVE_ATTEMPT_CEILING": "9"}):
            self.assertEqual(queue_velocity._env_int("ORCH_QV_SHELVE_ATTEMPT_CEILING", 3), 9)

    def test_a_missing_attempt_field_does_not_protect_a_task(self):
        # Fail-OPEN here on purpose, opposite to the usual fail-soft: if `attempt` is
        # absent the guard must not silently make every task unshelvable, which would
        # disable the I-action entirely and let the queue grow without bound.
        shelved, _ = self._run([
            {"id": "noattempt", "slug": "legacy-row", "confidence": None},
            {"id": "nullattempt", "slug": "null-row", "confidence": None, "attempt": None},
        ])
        self.assertEqual(sorted(shelved), ["noattempt", "nullattempt"])

    # ── guarantees the fix must not break ────────────────────────────────────

    def test_pinned_tasks_are_still_never_shelved(self):
        shelved, params = self._run([
            {"id": "pin", "slug": "express", "confidence": None, "attempt": 0, "pinned": True},
            {"id": "plain", "slug": "ordinary", "confidence": None, "attempt": 0},
        ])
        self.assertEqual(shelved, ["plain"])
        self.assertEqual(params.get("pinned"), "not.is.true")

    def test_a_recoverable_task_still_keeps_its_slot(self):
        with patch.object(queue_velocity.db, "select",
                          return_value=[{"id": "r", "slug": "s", "confidence": None, "attempt": 0}]), \
             patch.object(queue_velocity.db, "update") as upd, \
             patch.object(queue_velocity, "_recovery_action",
                          return_value=("recovered", "branch intact")):
            queue_velocity._shelve_lowest_ev(5)
        upd.assert_not_called()

    def test_an_infra_error_still_fails_soft_without_shelving(self):
        with patch.object(queue_velocity.db, "select",
                          return_value=[{"id": "r", "slug": "s", "confidence": None, "attempt": 0}]), \
             patch.object(queue_velocity.db, "update") as upd, \
             patch.object(queue_velocity, "_recovery_action",
                          return_value=("infra_error", "git timeout")):
            queue_velocity._shelve_lowest_ev(5)
        upd.assert_not_called()

    def test_a_failing_shelve_is_reported_rather_than_silently_counted(self):
        # A bare `except: pass` made a failed shelve look like a successful one, so the
        # I-action could report draining it had not done.
        with patch.object(queue_velocity.db, "select",
                          return_value=[{"id": "r", "slug": "boom", "confidence": None,
                                         "attempt": 0}]), \
             patch.object(queue_velocity.db, "update", side_effect=RuntimeError("db down")), \
             patch.object(queue_velocity, "_recovery_action", return_value=("shelve", "n/a")):
            self.assertEqual(queue_velocity._shelve_lowest_ev(5), 0)

    def test_a_db_failure_returns_zero_rather_than_raising(self):
        with patch.object(queue_velocity.db, "select", side_effect=RuntimeError("down")):
            self.assertEqual(queue_velocity._shelve_lowest_ev(5), 0)


if __name__ == "__main__":
    unittest.main()
