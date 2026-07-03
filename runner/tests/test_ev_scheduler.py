"""
test_ev_scheduler.py - EV-per-token ordering safety + determinism.

A) score() is deterministic and applies every boost/penalty from the spec.
B) rank_queue() orders high-MRR revenue work above zero-EV work.
C) apply_ranking() uses the tasks.priority column when it exists, falls back to a
   controls ev_ranking row when it doesn't, and to tasks.confidence when controls
   rejects key/value rows.
D) park_zero_ev() only parks near-zero-EV tasks with attempt>=2, caps at 20/run,
   and writes the exact park note.
All db calls are mocked — no network.
"""
import os, sys, json, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ev_scheduler
import db


def _ctx(**over):
    ctx = {"revenue_by_project": {"payapp": 900.0, "deadapp": 0.0},
           "surface_returns": {},
           "outcome_stats": {"payapp": {"success_rate": 0.8, "avg_usd": 0.5}},
           "approved_slugs": set()}
    ctx.update(over)
    return ctx


def _task(**over):
    t = {"id": "t1", "project": "payapp", "kind": "build", "prompt": "add a feature",
         "slug": "some-task", "transient_retries": 0, "attempt": 0}
    t.update(over)
    return t


class TestScore(unittest.TestCase):

    def test_deterministic(self):
        t, c = _task(), _ctx()
        self.assertEqual(ev_scheduler.score(t, c), ev_scheduler.score(t, c))

    def test_revenue_keyword_boosts_build_tasks(self):
        c = _ctx()
        plain = ev_scheduler.score(_task(prompt="refactor internals"), c)
        boosted = ev_scheduler.score(_task(prompt="improve PRICING page conversion"), c)
        self.assertAlmostEqual(boosted, plain * 1.5)

    def test_revenue_keyword_ignored_for_non_build(self):
        c = _ctx()
        plain = ev_scheduler.score(_task(kind="research", prompt="refactor"), c)
        research = ev_scheduler.score(_task(kind="research", prompt="study pricing"), c)
        self.assertAlmostEqual(research, plain)

    def test_approved_slug_doubles(self):
        base = ev_scheduler.score(_task(), _ctx())
        appr = ev_scheduler.score(_task(), _ctx(approved_slugs={"some-task"}))
        self.assertAlmostEqual(appr, base * 2.0)

    def test_retry_penalty(self):
        c = _ctx()
        base = ev_scheduler.score(_task(), c)
        flaky = ev_scheduler.score(_task(transient_retries=2), c)
        self.assertAlmostEqual(flaky, base * 0.3)
        one_retry = ev_scheduler.score(_task(transient_retries=1), c)
        self.assertAlmostEqual(one_retry, base)

    def test_zero_mrr_scores_zero(self):
        s = ev_scheduler.score(_task(project="deadapp"), _ctx())
        self.assertLess(s, ev_scheduler.ZERO_EV)

    def test_default_success_rate_and_cost(self):
        """Project with no outcome stats uses success_rate=0.7, avg_usd=0."""
        import math
        c = _ctx(outcome_stats={})
        s = ev_scheduler.score(_task(), c)
        self.assertAlmostEqual(s, math.log10(1 + 900.0) * 0.7 / 0.5)

    def test_positive_surface_return_boosts_kind(self):
        base = ev_scheduler.score(_task(), _ctx())
        boosted = ev_scheduler.score(_task(), _ctx(surface_returns={"build": 50.0}))
        self.assertAlmostEqual(boosted, base * 1.5)
        # negative deltas must NOT boost
        neg = ev_scheduler.score(_task(), _ctx(surface_returns={"build": -50.0}))
        self.assertAlmostEqual(neg, base)


class _MockDB(unittest.TestCase):
    """Base: swap db.select/insert/update for in-memory fakes."""

    def setUp(self):
        self.orig = (db.select, db.insert, db.update)
        self.updates, self.inserts = [], []

    def tearDown(self):
        db.select, db.insert, db.update = self.orig

    def install(self, select_fn, insert_exc=None):
        db.select = select_fn
        def _ins(table, row, upsert=False, **kw):
            if insert_exc:
                raise insert_exc
            self.inserts.append((table, row, upsert))
        db.insert = _ins
        db.update = lambda table, match, patch: self.updates.append((table, match, patch))


def _queue_select(tasks, priority_exists=False):
    def _select(table, params=None):
        params = params or {}
        if table == "tasks":
            if params.get("select") == "priority":
                if priority_exists:
                    return [{"priority": None}]
                raise RuntimeError("HTTP 400: column tasks.priority does not exist")
            return [dict(t) for t in tasks]
        if table == "projects":
            return [{"id": "p1", "name": "payapp"}, {"id": "p2", "name": "deadapp"}]
        return []
    return _select


class TestRankQueue(_MockDB):

    def test_high_mrr_revenue_work_ranks_first(self):
        tasks = [
            {"id": "low", "project_id": "p2", "kind": "chore", "prompt": "tidy",
             "slug": "tidy", "state": "QUEUED", "created_at": "2026-01-01"},
            {"id": "high", "project_id": "p1", "kind": "build",
             "prompt": "improve conversion funnel", "slug": "conv",
             "state": "QUEUED", "created_at": "2026-01-02"},
        ]
        self.install(_queue_select(tasks))
        ids = ev_scheduler.rank_queue(ctx=_ctx())
        self.assertEqual(ids[0], "high")
        self.assertEqual(ids[-1], "low")

    def test_ties_broken_deterministically_by_created_at(self):
        tasks = [
            {"id": "b", "project_id": "p1", "kind": "build", "prompt": "x",
             "slug": "b", "created_at": "2026-01-02"},
            {"id": "a", "project_id": "p1", "kind": "build", "prompt": "x",
             "slug": "a", "created_at": "2026-01-01"},
        ]
        self.install(_queue_select(tasks))
        self.assertEqual(ev_scheduler.rank_queue(ctx=_ctx()), ["a", "b"])


class TestApplyRanking(_MockDB):

    def _tasks(self, n=3):
        return [{"id": f"t{i}", "project_id": "p1", "kind": "build",
                 "prompt": "grow revenue", "slug": f"s{i}",
                 "created_at": f"2026-01-0{i+1}"} for i in range(n)]

    def test_priority_column_used_when_present(self):
        self.install(_queue_select(self._tasks(), priority_exists=True))
        scored = ev_scheduler._scored_queue(ctx=_ctx())
        res = ev_scheduler.apply_ranking(scored)
        self.assertEqual(res["storage"], "priority")
        self.assertEqual(len(self.updates), 3)
        # best task gets priority 1 (lower = claimed first)
        table, match, patch = self.updates[0]
        self.assertEqual(table, "tasks")
        self.assertEqual(patch, {"priority": 1})
        self.assertEqual(self.inserts, [], "no controls row when priority column exists")

    def test_controls_fallback_when_no_priority_column(self):
        self.install(_queue_select(self._tasks()))
        res = ev_scheduler.apply_ranking(ev_scheduler._scored_queue(ctx=_ctx()))
        self.assertEqual(res["storage"], "controls")
        self.assertEqual(len(self.inserts), 1)
        table, row, upsert = self.inserts[0]
        self.assertEqual(table, "controls")
        self.assertEqual(row["key"], "ev_ranking")
        self.assertTrue(upsert, "controls ev_ranking row must be upserted")
        self.assertEqual(len(json.loads(row["value"])), 3)
        self.assertEqual(self.updates, [])

    def test_confidence_last_resort_when_controls_rejects(self):
        self.install(_queue_select(self._tasks()),
                     insert_exc=RuntimeError("HTTP 400: column controls.key missing"))
        res = ev_scheduler.apply_ranking(ev_scheduler._scored_queue(ctx=_ctx()))
        self.assertEqual(res["storage"], "confidence")
        self.assertEqual(len(self.updates), 3)
        for _, _, patch in self.updates:
            self.assertIn("confidence", patch)
            self.assertTrue(0.0 <= patch["confidence"] <= 1.0)

    def test_priority_writes_capped_at_top_n(self):
        self.install(_queue_select(self._tasks(60)), )
        # force priority path
        db.select = _queue_select(self._tasks(60), priority_exists=True)
        res = ev_scheduler.apply_ranking(ev_scheduler._scored_queue(ctx=_ctx()))
        self.assertEqual(res["storage"], "priority")
        self.assertEqual(len(self.updates), ev_scheduler.TOP_N)


class TestParkZeroEV(_MockDB):

    def _zero_task(self, i, attempt=2):
        return {"id": f"z{i}", "project_id": "p2", "kind": "chore", "prompt": "x",
                "slug": f"z{i}", "attempt": attempt, "created_at": f"2026-01-01T{i:02d}"}

    def test_parks_only_zero_ev_with_enough_attempts(self):
        tasks = [self._zero_task(0, attempt=2),
                 self._zero_task(1, attempt=0),  # too few attempts — keep
                 {"id": "good", "project_id": "p1", "kind": "build", "prompt": "x",
                  "slug": "good", "attempt": 5, "created_at": "2026-01-02"}]
        self.install(_queue_select(tasks))
        parked = ev_scheduler.park_zero_ev(ev_scheduler._scored_queue(ctx=_ctx()))
        self.assertEqual(parked, 1)
        table, match, patch = self.updates[0]
        self.assertEqual(match, {"id": "z0"})
        self.assertEqual(patch["state"], "BLOCKED")
        self.assertEqual(patch["note"], ev_scheduler.PARK_NOTE)

    def test_park_cap_respected(self):
        tasks = [self._zero_task(i) for i in range(30)]
        self.install(_queue_select(tasks))
        parked = ev_scheduler.park_zero_ev(ev_scheduler._scored_queue(ctx=_ctx()))
        self.assertEqual(parked, ev_scheduler.PARK_CAP)

    def test_run_never_raises(self):
        def _boom(*a, **kw):
            raise RuntimeError("db down")
        self.install(_boom)
        db.select = _boom
        res = ev_scheduler.run()
        self.assertIn("ranked", res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
