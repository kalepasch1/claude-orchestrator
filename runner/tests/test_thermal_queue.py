"""
test_thermal_queue.py — bottleneck multiplier and dep_fans accumulation.

A) A task that unblocks many queued dependents scores higher than an otherwise
   identical task with no dependents (bottleneck detection).
B) dep_fans counts correctly when multiple tasks share a dep slug.
C) dep_fans=None falls back gracefully (unblock_mult == 1.0, no crash).
D) run() produces a ranking where the bottleneck task is ranked first.
"""
import os, sys, json, math, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import thermal_queue
import db


# ── helpers ──────────────────────────────────────────────────────────────────

def _task(slug, deps=None, kind="build", pid="p1", priority=5):
    return {
        "id": slug,
        "slug": slug,
        "project_id": pid,
        "kind": kind,
        "priority": priority,
        "confidence": 0.5,
        "deps": deps or [],
        "created_at": "2026-01-01T00:00:00",
        "prompt": "do something",
    }


_EMPTY = {}   # no historical data — all defaults apply


# ── A: bottleneck task scores higher ─────────────────────────────────────────

class TestBottleneckMultiplier(unittest.TestCase):

    def _score(self, task, dep_fans):
        return thermal_queue._thermal_score(
            task, _EMPTY, _EMPTY, _EMPTY, _EMPTY, set(), dep_fans
        )

    def test_bottleneck_scores_higher_than_isolated(self):
        t = _task("root")
        isolated = self._score(t, {})
        # 5 queued tasks depend on "root"
        bottleneck = self._score(t, {"root": 5})
        self.assertGreater(bottleneck, isolated)

    def test_more_dependents_means_higher_score(self):
        t = _task("root")
        low = self._score(t, {"root": 1})
        mid = self._score(t, {"root": 5})
        high = self._score(t, {"root": 20})
        self.assertLess(low, mid)
        self.assertLess(mid, high)

    def test_unblock_mult_formula(self):
        t = _task("x")
        s_zero = self._score(t, {})
        s_ten = self._score(t, {"x": 10})
        expected_ratio = 1.0 + math.log1p(10)   # unblock_mult for count=10
        self.assertAlmostEqual(s_ten / s_zero, expected_ratio, places=6)

    def test_no_dep_fans_gives_mult_one(self):
        t = _task("x")
        baseline = self._score(t, {})
        no_fans = self._score(t, None)
        self.assertAlmostEqual(baseline, no_fans, places=9)


# ── B: dep_fans accumulation ─────────────────────────────────────────────────

class TestDepFansAccumulation(unittest.TestCase):

    def _build_dep_fans(self, queued):
        dep_fans = {}
        for t in queued:
            for dep_slug in (t.get("deps") or []):
                dep_fans[dep_slug] = dep_fans.get(dep_slug, 0) + 1
        return dep_fans

    def test_single_dependent(self):
        queued = [_task("child", deps=["parent"])]
        fans = self._build_dep_fans(queued)
        self.assertEqual(fans.get("parent"), 1)

    def test_multiple_dependents_on_same_slug(self):
        queued = [
            _task("c1", deps=["shared"]),
            _task("c2", deps=["shared"]),
            _task("c3", deps=["shared"]),
        ]
        fans = self._build_dep_fans(queued)
        self.assertEqual(fans["shared"], 3)

    def test_task_with_no_deps_not_in_fans(self):
        queued = [_task("solo")]
        fans = self._build_dep_fans(queued)
        self.assertNotIn("solo", fans)
        self.assertEqual(fans, {})

    def test_diamond_dep_shape(self):
        queued = [
            _task("b", deps=["a"]),
            _task("c", deps=["a"]),
            _task("d", deps=["b", "c"]),
        ]
        fans = self._build_dep_fans(queued)
        self.assertEqual(fans["a"], 2)
        self.assertEqual(fans["b"], 1)
        self.assertEqual(fans["c"], 1)


# ── D: run() ranks bottleneck task first ─────────────────────────────────────

class TestRunBottleneckRanking(unittest.TestCase):

    def setUp(self):
        self.orig_select = db.select
        self.orig_insert = db.insert
        self.inserts = []

    def tearDown(self):
        db.select = self.orig_select
        db.insert = self.orig_insert

    def test_bottleneck_task_ranked_first(self):
        # "root" is identical to "leaf" except 3 queued tasks depend on "root"
        queued = [
            {**_task("root"), "id": "root"},
            {**_task("leaf"), "id": "leaf"},
            {**_task("c1", deps=["root"]), "id": "c1"},
            {**_task("c2", deps=["root"]), "id": "c2"},
            {**_task("c3", deps=["root"]), "id": "c3"},
        ]

        def fake_select(table, params=None):
            params = params or {}
            if table == "tasks":
                state = params.get("state", "")
                if "QUEUED" in state:
                    return queued
                if "DONE" in state or "MERGED" in state:
                    return []
                return []
            if table == "projects":
                return [{"id": "p1", "concurrency_weight": 1.0}]
            if table == "outcomes":
                return []
            return []

        def fake_insert(table, row, upsert=False, **kw):
            self.inserts.append((table, row))

        db.select = fake_select
        db.insert = fake_insert

        result = thermal_queue.run()
        self.assertEqual(result["ranked"], 5)
        ranked_ids = json.loads(self.inserts[-1][1]["value"])
        self.assertEqual(ranked_ids[0], "root", "bottleneck task must rank first")
        # leaf has no dependents and should rank behind root
        self.assertGreater(ranked_ids.index("leaf"), ranked_ids.index("root"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
