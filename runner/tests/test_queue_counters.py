import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_counters


class FakeDb:
    def __init__(self):
        self.calls = []

    def count(self, table, params=None):
        self.calls.append((table, params or {}))
        params = params or {}
        state = params.get("state")
        slug = params.get("slug", "")
        if slug == "like.recover-missing-branch-%" and state == "eq.QUEUED":
            return 28
        if slug == "like.improve-%" and state == "eq.QUEUED":
            return 12
        if slug == "like.canary-%" and state == "in.(QUEUED,RUNNING)":
            return 6
        if slug in {
            "like.relfix-%",
            "like.qafix-%",
            "like.deployfix-%",
            "like.buildfix-%",
            "like.copyfix-%",
        } and state == "eq.QUEUED":
            return 2
        if slug in {
            "like.relfix-%",
            "like.qafix-%",
            "like.deployfix-%",
            "like.buildfix-%",
            "like.copyfix-%",
        } and state == "eq.RUNNING":
            return 1
        if state:
            return {
                "eq.QUEUED": 901,
                "eq.RUNNING": 4,
                "eq.RETRY": 3,
                "eq.BLOCKED": 8,
                "eq.CONFLICT": 2,
                "eq.TESTFAIL": 1,
                "eq.QUARANTINED": 5,
            }.get(state, 0)
        return 1200


class QueueCountersTest(unittest.TestCase):

    def test_exact_counts_include_full_state_and_prefix_pressure(self):
        out = queue_counters.exact_counts(db_client=FakeDb())

        self.assertEqual(out["states"]["QUEUED"], 901)
        self.assertEqual(out["queued"], 901)
        self.assertEqual(out["running"], 4)
        self.assertEqual(out["active_like"], 908)
        self.assertEqual(out["blocked_like"], 11)
        self.assertEqual(out["total_tasks"], 1200)
        self.assertEqual(out["unknown_state_total"], 276)
        self.assertEqual(out["recovery_queued"], 28)
        self.assertEqual(out["improvements_queued"], 12)
        self.assertEqual(out["canaries_active"], 6)
        self.assertEqual(out["release_fix_queued"], 10)
        self.assertEqual(out["release_fix_running"], 5)


if __name__ == "__main__":
    unittest.main()
