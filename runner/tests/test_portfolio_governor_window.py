"""The governor ranks projects against each other, so its inputs must be comparable.

`_project_stats` windowed by ROWS ("most recent 300 outcomes"), which is not a window at
all: a busy app's 300 outcomes might be two days of work while a quiet app's are six
months. `plan()` then sorted those success rates and costs into terciles and handed out
fleet concurrency on the result — comparing this week's performance against last spring's.

The database layer had been shouting about it 844 times into governor.err:

    TRUNCATED SCAN portfolio_governor.py:26 -> outcomes returned exactly its limit (300)
    ordered by created_at.desc. Anything past the cap is invisible to this caller.

These tests pin the fix: one time window for everybody, the row cap reported rather than
silently applied, and thin projects left alone instead of ranked on nothing.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_governor as gov  # noqa: E402


class FakeDB(object):
    """Records the params every select() was called with, and replays canned rows."""

    def __init__(self, outcomes_by_project=None, projects=None):
        self.outcomes = outcomes_by_project or {}
        self.projects = projects or []
        self.calls = []
        self.updates = []

    def select(self, table, params=None):
        params = params or {}
        self.calls.append((table, params))
        if table == "projects":
            return list(self.projects)
        if table == "outcomes":
            name = (params.get("project") or "eq.").split("eq.", 1)[-1]
            rows = list(self.outcomes.get(name, []))
            limit = int(params.get("limit") or 10**9)
            return rows[:limit]
        return []

    def update(self, table, where, patch):
        self.updates.append((table, where, patch))


def outcomes(n, integrated=True, usd=1.0):
    return [{"integrated": integrated, "usd": usd} for _ in range(n)]


class WindowIsTimeBounded(unittest.TestCase):
    def setUp(self):
        self.real_db = gov.db
        self.fake = FakeDB(outcomes_by_project={"alpha": outcomes(50)})
        gov.db = self.fake

    def tearDown(self):
        gov.db = self.real_db

    def test_the_outcomes_query_is_filtered_by_created_at(self):
        gov._project_stats("alpha")
        _table, params = self.fake.calls[0]
        self.assertIn("created_at", params,
                      "without a time filter the sample spans however long 300 rows happen "
                      "to cover, which differs per project")
        self.assertTrue(params["created_at"].startswith("gte."))

    def test_the_row_cap_is_still_applied_as_a_safety_valve(self):
        gov._project_stats("alpha")
        _table, params = self.fake.calls[0]
        self.assertEqual(params.get("limit"), str(gov.WINDOW))

    def test_the_caller_can_pin_the_window_start(self):
        gov._project_stats("alpha", since="2026-01-01T00:00:00")
        _table, params = self.fake.calls[0]
        self.assertEqual(params["created_at"], "gte.2026-01-01T00:00:00")

    def test_window_start_moves_back_by_the_configured_days(self):
        import datetime
        now = datetime.datetime(2026, 8, 20, 12, 0, 0)
        start = gov._window_start(now=now)
        expected = (now - datetime.timedelta(days=gov.WINDOW_DAYS)).isoformat()
        self.assertEqual(start, expected)

    def test_stats_report_the_window_they_were_measured_over(self):
        st = gov._project_stats("alpha")
        self.assertEqual(st["window_days"], gov.WINDOW_DAYS)


class TruncationIsReportedNotHidden(unittest.TestCase):
    def setUp(self):
        self.real_db = gov.db
        gov.db = FakeDB(outcomes_by_project={
            "busy": outcomes(gov.WINDOW + 500),   # more than the cap, inside the window
            "calm": outcomes(25),
        })

    def tearDown(self):
        gov.db = self.real_db

    def test_a_bound_row_cap_is_flagged(self):
        self.assertTrue(gov._project_stats("busy")["truncated"])

    def test_an_unbound_query_is_not_flagged(self):
        self.assertFalse(gov._project_stats("calm")["truncated"])


class EveryProjectGetsTheSameWindow(unittest.TestCase):
    """The property the whole fix exists for."""

    def setUp(self):
        self.real_db = gov.db
        self.fake = FakeDB(
            outcomes_by_project={"alpha": outcomes(40), "beta": outcomes(40)},
            projects=[{"id": "1", "name": "alpha", "concurrency_weight": 1},
                      {"id": "2", "name": "beta", "concurrency_weight": 1}],
        )
        gov.db = self.fake

    def tearDown(self):
        gov.db = self.real_db

    def test_one_cutoff_is_shared_across_the_whole_pass(self):
        gov.plan()
        cutoffs = {p["created_at"] for t, p in self.fake.calls
                   if t == "outcomes" and "created_at" in p and str(p.get("limit")) == str(gov.WINDOW)}
        self.assertEqual(len(cutoffs), 1,
                         "projects ranked against each other must share a window boundary; "
                         f"saw {len(cutoffs)} distinct cutoffs")


class ThinProjectsAreNotRanked(unittest.TestCase):
    def setUp(self):
        self.real_db = gov.db
        self.fake = FakeDB(
            outcomes_by_project={"rich": outcomes(40), "sparse": outcomes(2)},
            projects=[{"id": "1", "name": "rich", "concurrency_weight": 1},
                      {"id": "2", "name": "sparse", "concurrency_weight": 2}],
        )
        gov.db = self.fake

    def tearDown(self):
        gov.db = self.real_db

    def test_a_project_below_the_sample_floor_is_left_out_of_the_ranking(self):
        names = {s["name"] for s in gov.plan()}
        self.assertIn("rich", names)
        self.assertNotIn("sparse", names,
                         "ranking an app on 2 outcomes against one with 40 is not a comparison")

    def test_an_unscored_project_keeps_its_weight(self):
        gov.run(apply=True)
        touched = {w.get("id") for _t, w, _p in self.fake.updates}
        self.assertNotIn("2", touched, "an unscored project must not have its capacity changed")

    def test_no_outcomes_at_all_yields_no_stats(self):
        self.assertIsNone(gov._project_stats("never-heard-of-it"))


class RunStillWorks(unittest.TestCase):
    def setUp(self):
        self.real_db = gov.db
        self.fake = FakeDB(
            outcomes_by_project={
                "cheap": outcomes(30, integrated=True, usd=0.0),
                "pricey": outcomes(30, integrated=False, usd=5.0),
                "middle": outcomes(30, integrated=True, usd=2.0),
            },
            projects=[{"id": "1", "name": "cheap", "concurrency_weight": 1},
                      {"id": "2", "name": "pricey", "concurrency_weight": 3},
                      {"id": "3", "name": "middle", "concurrency_weight": 1}],
        )
        gov.db = self.fake

    def tearDown(self):
        gov.db = self.real_db

    def test_the_high_value_project_is_ranked_above_the_expensive_one(self):
        scored = {s["name"]: s for s in gov.plan()}
        self.assertGreater(scored["cheap"]["ev"], scored["pricey"]["ev"])

    def test_weights_stay_inside_the_documented_band(self):
        for s in gov.plan():
            self.assertGreaterEqual(s["new_weight"], 1)
            self.assertLessEqual(s["new_weight"], 3)

    def test_apply_false_changes_nothing(self):
        gov.run(apply=False)
        self.assertEqual(self.fake.updates, [])


if __name__ == "__main__":
    unittest.main()
