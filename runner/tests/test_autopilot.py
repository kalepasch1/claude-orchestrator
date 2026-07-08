import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autopilot


class AutopilotTest(unittest.TestCase):

    def test_snapshot_counts_recovery_improvement_and_canary_pressure(self):
        rows = [
            {"id": "r1", "slug": "recover-missing-branch-a", "state": "QUEUED"},
            {"id": "i1", "slug": "improve-routing", "state": "QUEUED"},
            {"id": "c1", "slug": "canary-ollama-1", "state": "RUNNING"},
            {"id": "b1", "slug": "blocked-task", "state": "BLOCKED"},
        ]
        db = MagicMock()
        db.select.return_value = rows

        with patch.object(autopilot, "db", db):
            snap = autopilot.snapshot(limit=10)

        self.assertEqual(snap["queued"], 2)
        self.assertEqual(snap["recovery_queued"], 1)
        self.assertEqual(snap["improvements_queued"], 1)
        self.assertEqual(snap["canaries_active"], 1)
        self.assertEqual(snap["blocked_like"], 1)
        self.assertEqual(snap["sampled_queued"], 2)

    def test_snapshot_prefers_exact_queue_counts_over_sample(self):
        rows = [
            {"id": "new1", "slug": "recent-work", "state": "QUEUED"},
        ]
        exact = {
            "states": {"QUEUED": 901, "RUNNING": 4, "BLOCKED": 8, "CONFLICT": 2, "TESTFAIL": 1},
            "total_tasks": 1200,
            "queued": 901,
            "running": 4,
            "blocked_like": 11,
            "quarantined": 0,
            "recovery_queued": 28,
            "improvements_queued": 12,
            "canaries_active": 6,
            "release_fix_queued": 5,
            "release_fix_running": 1,
        }
        db = MagicMock()
        db.select.return_value = rows
        counters = types.SimpleNamespace(exact_counts=lambda db_client: exact)

        with patch.object(autopilot, "db", db), \
             patch.dict(sys.modules, {"queue_counters": counters}):
            snap = autopilot.snapshot(limit=1)

        self.assertEqual(snap["queued"], 901)
        self.assertEqual(snap["sampled_queued"], 1)
        self.assertEqual(snap["running"], 4)
        self.assertEqual(snap["blocked_like"], 11)
        self.assertEqual(snap["total_tasks"], 1200)
        self.assertEqual(snap["recovery_queued"], 28)
        self.assertTrue(snap["deep_backlog"])

    def test_run_invokes_pressure_agents_and_cheap_improvement_replenisher(self):
        calls = []

        def fake_mod(name, **methods):
            return types.SimpleNamespace(**methods)

        modules = {
            "resource_governor": fake_mod("resource_governor",
                govern=lambda: calls.append(("resources", None)) or {"throttle": 12}),
            "startup_selfcheck": fake_mod("startup_selfcheck",
                run=lambda runner_id="autopilot": calls.append(("selfcheck", runner_id)) or {"status": "ok"}),
            "integration_sweeper": fake_mod("integration_sweeper",
                sweep=lambda **kw: calls.append(("recovery", kw)) or {"recovery_queued": 1}),
            "queue_janitor": fake_mod("queue_janitor",
                run=lambda: calls.append(("janitor", None)) or 0),
            "auto_remediate": fake_mod("auto_remediate",
                run=lambda **kw: calls.append(("remediate", kw)) or {"requeued": 1}),
            "ev_scheduler": fake_mod("ev_scheduler",
                run=lambda: calls.append(("rank", None)) or {"ranked": 4}),
            "prewarm": fake_mod("prewarm",
                run=lambda: calls.append(("prewarm", None)) or 2),
            "route_evidence": fake_mod("route_evidence",
                run=lambda: calls.append(("evidence", None)) or {"backfill": {"updated": 1}}),
            "coder_canary": fake_mod("coder_canary",
                run=lambda **kw: calls.append(("canary", kw)) or {"queued": 1}),
            "improvement_miner": fake_mod("improvement_miner",
                run=lambda: calls.append(("improve", os.environ.get("IMPROVE_USE_MODEL"))) or {"queued": 2}),
            "portfolio_governor": fake_mod("portfolio_governor",
                run=lambda **kw: calls.append(("portfolio", kw)) or {"ok": True}),
        }

        rows = [
            {"id": "r1", "slug": "recover-missing-branch-a", "state": "QUEUED"},
            {"id": "i1", "slug": "improve-one", "state": "QUEUED"},
            {"id": "b1", "slug": "blocked-task", "state": "BLOCKED"},
            {"id": "run1", "slug": "running-task", "state": "RUNNING"},
        ]
        db = MagicMock()

        def select(table, params=None):
            if table == "tasks":
                return rows
            if table in ("app_revenue", "approvals"):
                return []
            return []

        db.select.side_effect = select

        with patch.object(autopilot, "db", db), \
             patch.object(autopilot, "_load_state", return_value={"agents": {}, "snapshots": []}), \
             patch.object(autopilot, "_save_state"), \
             patch.object(autopilot, "IMPROVE_FLOOR", 3), \
             patch.dict(sys.modules, modules), \
             patch.dict(os.environ, {}, clear=False):
            out = autopilot.run(force=True)

        called = {c[0] for c in calls}
        self.assertIn("resources", called)
        self.assertNotIn("selfcheck", called)
        self.assertIn("recovery", called)
        self.assertIn("janitor", called)
        self.assertIn("remediate", called)
        self.assertIn("rank", called)
        self.assertIn("prewarm", called)
        self.assertIn("evidence", called)
        self.assertIn("canary", called)
        self.assertIn("improve", called)
        self.assertIn("portfolio", called)
        self.assertTrue(all(a["ok"] for a in out["agents"]))
        self.assertTrue(any(a["agent"] == "selfcheck" and a.get("skipped") == "external_scheduler" for a in out["agents"]))
        self.assertIn(("improve", "false"), calls)

    def test_drain_stall_agent_runs_billing_guard_when_paused_with_queue(self):
        calls = []

        def fake_mod(**methods):
            return types.SimpleNamespace(**methods)

        modules = {
            "billing_guard": fake_mod(run=lambda: calls.append(("billing_guard", None)) or {"ok": True, "resumed": True}),
            "queue_janitor": fake_mod(run=lambda: calls.append(("janitor", None)) or 0),
            "resource_governor": fake_mod(govern=lambda: calls.append(("resources", None)) or {"throttle": 2}),
            "ev_scheduler": fake_mod(run=lambda: calls.append(("rank", None)) or {"ranked": 1}),
            "prewarm": fake_mod(run=lambda: calls.append(("prewarm", None)) or 1),
            "task_dedup": fake_mod(apply=lambda: calls.append(("dedup", None)) or {"collapsed": 0}),
            "portfolio_governor": fake_mod(run=lambda **kw: calls.append(("portfolio", kw)) or {"ok": True}),
        }
        rows = [{"id": "q1", "slug": "queued-task", "state": "QUEUED"}]
        db = MagicMock()

        def select(table, params=None):
            if table == "tasks":
                return rows
            if table == "controls":
                return [{"paused": True, "reason": "billing_guard: API key present", "updated_by": "billing_guard"}]
            if table in ("app_revenue", "approvals", "releases"):
                return []
            return []

        db.select.side_effect = select
        with patch.object(autopilot, "db", db), \
             patch.object(autopilot, "_exact_queue_counts", return_value={
                 "states": {"QUEUED": 1},
                 "queued": 1,
                 "running": 0,
                 "blocked_like": 0,
                 "total_tasks": 1,
             }), \
             patch.object(autopilot, "_load_state", return_value={"agents": {}, "snapshots": []}), \
             patch.object(autopilot, "_save_state"), \
             patch.dict(sys.modules, modules), \
             patch.dict(os.environ, {}, clear=False):
            out = autopilot.run(force=True)

        self.assertIn(("billing_guard", None), calls)
        self.assertIn(("janitor", None), calls)
        self.assertTrue(any(a["agent"] == "drain_stall" and a["ok"] for a in out["agents"]))


if __name__ == "__main__":
    unittest.main()
