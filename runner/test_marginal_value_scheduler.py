#!/usr/bin/env python3
"""Tests for marginal_value_scheduler.py"""
import os, sys, unittest, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import types

db_stub = types.ModuleType("db")
db_stub.select = lambda *a, **kw: []
db_stub.update = lambda *a, **kw: None
db_stub.insert = lambda *a, **kw: None
sys.modules.setdefault("db", db_stub)

import marginal_value_scheduler as mvs

def _ctx():
    return {"revenue_by_project": {"proj-a": 1000, "proj-b": 1000, "unknown": 100},
            "outcome_stats": {"proj-a": {"success_rate": 0.8, "avg_usd": 0.5},
                              "proj-b": {"success_rate": 0.8, "avg_usd": 0.5},
                              "unknown": {"success_rate": 0.8, "avg_usd": 0.5}},
            "surface_returns": {}, "approved_slugs": set()}


class TestScoreMarginal(unittest.TestCase):
    def _task(self, pid="proj-a", kind="build", prompt="fix bug"):
        return {"project_id": pid, "project": pid, "kind": kind, "prompt": prompt,
                "slug": "t1", "deps": [], "attempt": 0, "transient_retries": 0,
                "remediation_count": 0, "note": ""}

    def test_score_decreases(self):
        s0 = mvs.score_marginal(self._task(), _ctx(), {})
        s1 = mvs.score_marginal(self._task(), _ctx(), {"proj-a": 1})
        self.assertGreater(s0, s1)

    def test_different_projects_independent(self):
        s0 = mvs.score_marginal(self._task("proj-a"), _ctx(), {"proj-b": 5})
        s1 = mvs.score_marginal(self._task("proj-a"), _ctx(), {})
        self.assertAlmostEqual(s0, s1)

    def test_zero_active_no_penalty(self):
        s0 = mvs.score_marginal(self._task(), _ctx(), {})
        s1 = mvs.score_marginal(self._task(), _ctx(), {"proj-a": 0})
        self.assertAlmostEqual(s0, s1)

    def test_positive(self):
        self.assertGreater(mvs.score_marginal(self._task(), _ctx(), {"proj-a": 100}), 0)

    def test_decay_exponent(self):
        os.environ["ORCH_MARGINAL_DECAY"] = "1.0"
        s_high = mvs.score_marginal(self._task(), _ctx(), {"proj-a": 2})
        os.environ["ORCH_MARGINAL_DECAY"] = "0.1"
        s_low = mvs.score_marginal(self._task(), _ctx(), {"proj-a": 2})
        self.assertGreater(s_low, s_high)
        os.environ["ORCH_MARGINAL_DECAY"] = "0.5"

    def test_missing_project_id(self):
        t = self._task()
        del t["project_id"]
        s = mvs.score_marginal(t, _ctx(), {})
        self.assertGreater(s, 0)

    def test_rank_disabled(self):
        os.environ["ORCH_MARGINAL_ENABLED"] = "false"
        r = mvs.rank(ctx=_ctx())
        self.assertFalse(r.get("enabled", True))
        os.environ["ORCH_MARGINAL_ENABLED"] = "true"

    def test_rank_empty(self):
        r = mvs.rank(ctx=_ctx())
        self.assertEqual(r.get("ranked"), 0)

if __name__ == "__main__":
    unittest.main()
