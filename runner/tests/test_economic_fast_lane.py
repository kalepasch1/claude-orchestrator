"""The fast lane must actually be fast: shorter SLA, dedicated capacity.

`apply_routing` already annotates the top revenue tasks with
lane="revenue-critical" and lane_scheduler boosts their priority. Priority alone
is not a fast lane — under saturation every lane competes for the same slots, so
a boosted task waits behind whatever is already running and the lane is only
fast while the fleet is idle, which is exactly when nobody needed it.

These tests cover the two properties that make it a lane rather than a label:
a tighter SLA, and capacity that nothing else can take.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import economic_scheduler as es  # noqa: E402


def task(task_id, lane=None, created_at=None):
    return {"id": task_id, "lane": lane, "created_at": created_at}


NOW = "2026-08-24T12:00:00+00:00"


class LaneSlaTest(unittest.TestCase):
    def test_the_revenue_lane_has_a_tighter_budget_than_the_default(self):
        # If it were not tighter there would be no reason to have the lane.
        self.assertLess(
            es.lane_sla_minutes(es.REVENUE_CRITICAL_LANE),
            es.lane_sla_minutes(None),
        )

    def test_an_unknown_lane_gets_the_default_budget_not_none(self):
        # A lane with no budget can never breach, which reads as "always fine".
        for lane in ("bulk", "", None, 42, object()):
            self.assertEqual(es.lane_sla_minutes(lane), es.DEFAULT_SLA_MINUTES)

    def test_a_fresh_revenue_task_is_inside_its_budget(self):
        status = es.sla_status(task("t", es.REVENUE_CRITICAL_LANE, "2026-08-24T11:30:00+00:00"), NOW)
        self.assertFalse(status["breached"])
        self.assertEqual(status["budget_minutes"], es.lane_sla_minutes(es.REVENUE_CRITICAL_LANE))
        self.assertAlmostEqual(status["age_minutes"], 30.0)

    def test_the_same_age_breaches_in_the_fast_lane_and_not_in_bulk(self):
        # The whole point: identical work, different promise.
        old = "2026-08-24T09:00:00+00:00"  # three hours
        self.assertTrue(es.sla_status(task("a", es.REVENUE_CRITICAL_LANE, old), NOW)["breached"])
        self.assertFalse(es.sla_status(task("b", "bulk", old), NOW)["breached"])

    def test_an_unreadable_timestamp_reports_unknown_rather_than_fine(self):
        # "We cannot tell" and "it is fine" are different answers.
        for created in (None, "", "last tuesday", 12345):
            status = es.sla_status(task("t", es.REVENUE_CRITICAL_LANE, created), NOW)
            self.assertTrue(status["unknown"], created)
            self.assertFalse(status["breached"])
            self.assertIsNone(status["age_minutes"])

    def test_a_task_created_in_the_future_is_not_negatively_aged(self):
        status = es.sla_status(task("t", es.REVENUE_CRITICAL_LANE, "2026-08-24T13:00:00+00:00"), NOW)
        self.assertEqual(status["age_minutes"], 0.0)
        self.assertFalse(status["breached"])

    def test_sla_status_never_raises_on_junk(self):
        for bad in (None, "string", 7, [], {"lane": object()}):
            self.assertIn("breached", es.sla_status(bad, NOW))

    def test_breaches_are_listed_worst_overrun_first(self):
        tasks = [
            task("mild", es.REVENUE_CRITICAL_LANE, "2026-08-24T10:30:00+00:00"),
            task("worst", es.REVENUE_CRITICAL_LANE, "2026-08-24T06:00:00+00:00"),
            task("fine", es.REVENUE_CRITICAL_LANE, "2026-08-24T11:45:00+00:00"),
            None,
        ]
        breaches = es.sla_breaches(tasks, NOW)
        self.assertEqual([b["id"] for b in breaches], ["worst", "mild"])


class ReservedCapacityTest(unittest.TestCase):
    def test_a_small_fleet_still_reserves_one_slot(self):
        # A reservation that rounds to zero is not a reservation.
        for total in (1, 2, 3):
            self.assertGreaterEqual(es.reserved_capacity(total), 1, total)

    def test_the_reservation_never_takes_the_whole_fleet(self):
        # A lane that can take everything is a stop-the-world, not a lane.
        for total in (2, 4, 8, 16, 100):
            self.assertLess(es.reserved_capacity(total), total, total)

    def test_the_reservation_grows_with_the_fleet(self):
        self.assertLessEqual(es.reserved_capacity(4), es.reserved_capacity(40))

    def test_no_capacity_reserves_nothing(self):
        for total in (0, -1, None, "eight", object()):
            self.assertEqual(es.reserved_capacity(total), 0, total)


class AdmissionTest(unittest.TestCase):
    def test_reserved_slots_go_to_revenue_critical_even_when_bulk_arrived_first(self):
        # This is the property priority-boosting alone does not give you.
        tasks = [task(f"bulk-{i}", "bulk") for i in range(10)]
        tasks.append(task("rev", es.REVENUE_CRITICAL_LANE))
        out = es.admit(tasks, total_lanes=4)
        self.assertIn("rev", [t["id"] for t in out["admitted"]])
        self.assertEqual(out["reserved_used"], 1)

    def test_bulk_work_is_slowed_but_never_starved(self):
        tasks = [task(f"rev-{i}", es.REVENUE_CRITICAL_LANE) for i in range(20)]
        tasks += [task(f"bulk-{i}", "bulk") for i in range(20)]
        out = es.admit(tasks, total_lanes=8)
        admitted_lanes = [t["lane"] for t in out["admitted"]]
        self.assertIn("bulk", admitted_lanes, "bulk work was completely starved")
        self.assertLessEqual(len(out["admitted"]), 8)

    def test_revenue_work_beyond_the_reservation_competes_normally(self):
        # The reservation is a floor, not a monopoly.
        tasks = [task(f"rev-{i}", es.REVENUE_CRITICAL_LANE) for i in range(10)]
        out = es.admit(tasks, total_lanes=4)
        self.assertEqual(len(out["admitted"]), 4)
        self.assertEqual(out["reserved_used"], es.reserved_capacity(4))

    def test_an_empty_queue_admits_nothing_and_does_not_raise(self):
        for tasks in (None, [], [None, "junk", 5]):
            out = es.admit(tasks, total_lanes=4)
            self.assertEqual(out["admitted"], [])

    def test_zero_capacity_admits_nothing(self):
        out = es.admit([task("rev", es.REVENUE_CRITICAL_LANE)], total_lanes=0)
        self.assertEqual(out["admitted"], [])
        self.assertEqual(out["reserved"], 0)

    def test_a_breached_revenue_task_takes_the_reserved_slot_first(self):
        # The lane exists for its own failures; clear those before fresh work.
        fresh = task("fresh", es.REVENUE_CRITICAL_LANE, "2026-08-24T11:55:00+00:00")
        breached = task("breached", es.REVENUE_CRITICAL_LANE, "2026-08-24T06:00:00+00:00")
        out = es.admit([fresh, breached], total_lanes=2, now_iso=NOW)
        self.assertEqual(out["admitted"][0]["id"], "breached")

    def test_starvation_is_reported_as_a_number(self):
        # So "the fast lane is starving the queue" is something to look at
        # rather than something to argue about.
        tasks = [task(f"rev-{i}", es.REVENUE_CRITICAL_LANE) for i in range(4)]
        tasks += [task(f"bulk-{i}", "bulk") for i in range(9)]
        out = es.admit(tasks, total_lanes=4)
        self.assertGreater(out["starved_bulk"], 0)

    def test_admission_writes_nothing(self):
        # Pure by construction: it decides, the caller acts.
        tasks = [task("rev", es.REVENUE_CRITICAL_LANE), task("bulk", "bulk")]
        before = [dict(t) for t in tasks]
        es.admit(tasks, total_lanes=2, now_iso=NOW)
        self.assertEqual(tasks, before)


if __name__ == "__main__":
    unittest.main()
