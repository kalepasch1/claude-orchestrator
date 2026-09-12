#!/usr/bin/env python3
"""Wiring tests: loops.py fires the db_steering handler and grows its fleet row;
prompt_assembler injects the database-steering brief as its own layer and stays
silent when there is none. Neither test touches a database or a model."""
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import loops  # noqa: E402
import prompt_assembler  # noqa: E402


class LoopsWiringTest(unittest.TestCase):
    def test_ensure_all_creates_the_fleet_row_once(self):
        inserted = []
        state = {"loops": []}

        def select(table, params=None):
            if table == "projects":
                return [{"name": "apparently-law"}]
            if table == "loops":
                return list(state["loops"])
            return []

        def insert(table, row, upsert=False):
            inserted.append(row)
            state["loops"].append({"project": row["project"], "type": row["type"]})
            return [row]

        with patch.object(loops.db, "select", select), patch.object(loops.db, "insert", insert):
            loops.ensure_all()
            loops.ensure_all()
        fleet = [r for r in inserted if r["type"] == "db_steering"]
        self.assertEqual(len(fleet), 1)
        self.assertEqual(fleet[0]["project"], loops.FLEET_LOOP_PROJECT)
        self.assertTrue(fleet[0]["enabled"])
        self.assertEqual(fleet[0]["config"], {"loop": "db_steering"})
        self.assertIn("db_steering", loops.FLEET_LOOPS)

    def test_run_due_dispatches_db_steering_handler(self):
        calls = []
        fake = types.ModuleType("db_steering")
        fake.run = lambda: calls.append("ran")
        loop_row = {"id": "L1", "project": "claude-orchestrator", "type": "db_steering",
                    "cadence_seconds": 600, "enabled": True, "last_run": None}

        def select(table, params=None):
            if table == "projects":
                return []
            if table == "loops":
                return [dict(loop_row)]
            if table == "tasks":
                return []
            return []
        updates = []
        with patch.dict(sys.modules, {"db_steering": fake}), \
                patch.object(loops.db, "select", select), \
                patch.object(loops.db, "insert", lambda *a, **k: [{}]), \
                patch.object(loops.db, "update", lambda t, m, p: updates.append((t, m, p))):
            fired = loops.run_due()
        self.assertEqual(calls, ["ran"])
        self.assertEqual(fired, 1)
        self.assertTrue(any(m.get("id") == "L1" and "last_run" in p for t, m, p in updates))


class PromptAssemblerLayerTest(unittest.TestCase):
    def _assemble(self, brief):
        fake = types.ModuleType("db_steering")
        fake.steering_brief = lambda project: brief if project == "apparently-law" else ""
        with patch.dict(sys.modules, {"db_steering": fake}), \
                patch.object(prompt_assembler, "_log_assembly", lambda *a, **k: None), \
                patch.object(prompt_assembler, "_project_brief", lambda p, r: ""):
            return prompt_assembler.assemble("add a column to matters", project="apparently-law",
                                             repo="/nonexistent", use_retrieval=False)

    def test_brief_is_injected_as_its_own_layer(self):
        out = self._assemble("## Database steering (live findings for apparently-law)\n- [HIGH] rls off: public.matters\n\n")
        self.assertIn("db_steering", out["layers"])
        self.assertIn("rls off: public.matters", out["prompt"])
        # the brief precedes the task body so the agent reads the constraint before the ask
        self.assertLess(out["prompt"].index("rls off"), out["prompt"].index("add a column to matters"))

    def test_no_brief_no_layer(self):
        out = self._assemble("")
        self.assertNotIn("db_steering", out["layers"])
        self.assertNotIn("Database steering", out["prompt"])

    def test_brief_failure_is_silent(self):
        fake = types.ModuleType("db_steering")

        def boom(project):
            raise RuntimeError("control plane down")
        fake.steering_brief = boom
        with patch.dict(sys.modules, {"db_steering": fake}), \
                patch.object(prompt_assembler, "_log_assembly", lambda *a, **k: None):
            out = prompt_assembler.assemble("x", project="apparently-law", repo="/nonexistent", use_retrieval=False)
        self.assertNotIn("db_steering", out["layers"])
        self.assertIn("x", out["prompt"])


if __name__ == "__main__":
    unittest.main()
