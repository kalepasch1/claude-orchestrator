import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_model_slots
import agentic_coders
import model_historical_canary
import resource_governor
import savings_meter


class FakeDB:
    def __init__(self):
        self.inserts = []
        self.rows = {}

    def insert(self, table, row, **kwargs):
        self.inserts.append((table, row))
        return [row]

    def select(self, table, params=None):
        return self.rows.get(table, [])


class TestLocalModelSlots(unittest.TestCase):
    def test_heavy_model_detection(self):
        self.assertTrue(local_model_slots.is_heavy("qwen3-coder:30b"))
        self.assertTrue(local_model_slots.is_heavy("gemma3:12b"))
        self.assertFalse(local_model_slots.is_heavy("tiny:1b"))

    def test_slot_unloads_other_heavy_models(self):
        fake = FakeDB()
        with patch.object(local_model_slots, "LOCK", os.path.join(tempfile.mkdtemp(), "slot.lock")), \
             patch.object(local_model_slots, "loaded_models", return_value=["qwen3-coder:30b", "llama3.1"]), \
             patch.object(local_model_slots, "unload", return_value=True) as unload, \
             patch.object(local_model_slots, "_free_ram_gb", return_value=20), \
             patch.dict(sys.modules, {"db": fake}):
            with local_model_slots.slot("gemma3:12b") as meta:
                self.assertTrue(meta["locked"])
        unload.assert_any_call("qwen3-coder:30b")
        unload.assert_any_call("gemma3:12b")

    def test_heavy_models_do_not_stay_resident_by_default(self):
        with patch.object(local_model_slots, "unload", return_value=True) as unload:
            self.assertTrue(local_model_slots.maybe_unload_after("qwen3-coder:30b"))
        unload.assert_called_once_with("qwen3-coder:30b")

    def test_agentic_ollama_uses_local_model_slot(self):
        entered = []

        class Slot:
            def __enter__(self):
                entered.append("enter")
                return {}
            def __exit__(self, exc_type, exc, tb):
                entered.append("exit")

        proc = MagicMock(returncode=0, stdout="done", stderr="")
        fake = FakeDB()
        with patch.object(agentic_coders, "_spec", return_value={
                "name": "ollama", "cmd": "aider --model ollama/llama3.1:latest --message {prompt}",
                "est_usd": 0.0,
             }), \
             patch.object(local_model_slots, "slot", return_value=Slot()) as slot, \
             patch.object(agentic_coders.subprocess, "run", return_value=proc), \
             patch.dict(sys.modules, {"db": fake}):
            out = agentic_coders.run("ollama", "make a tiny edit", "ollama/llama3.1:latest")

        self.assertEqual(out["returncode"], 0)
        slot.assert_called_once_with("llama3.1:latest", operation="agentic:ollama")
        self.assertEqual(entered, ["enter", "exit"])
        self.assertEqual([r[1]["kind"] for r in fake.inserts[:2]], ["agentic_coder_start", "agentic_coder_finish"])

    def test_unload_force_kills_stuck_ollama_server(self):
        killed = []
        ps = "  PID ARGS\n 123 /Applications/Ollama.app/Contents/Resources/llama-server --model blob\n"

        with patch.object(local_model_slots, "_post", side_effect=RuntimeError("api stuck")), \
             patch.object(local_model_slots.subprocess, "check_output", side_effect=[RuntimeError("curl failed"), ps]), \
             patch.object(local_model_slots.subprocess, "run") as run, \
             patch.object(local_model_slots, "loaded_models", side_effect=[
                 ["llama3.1:latest"], []
             ]), \
             patch.object(local_model_slots.os, "kill", side_effect=lambda pid, sig: killed.append((pid, sig))), \
             patch.object(local_model_slots.subprocess, "getoutput", return_value="  PID ARGS\n"):
            self.assertTrue(local_model_slots.unload("llama3.1:latest"))

        run.assert_called_once()
        self.assertEqual(killed[0][0], 123)


class TestSavingsMeter(unittest.TestCase):
    def test_records_savings_resource_event(self):
        fake = FakeDB()
        with patch.dict(sys.modules, {"db": fake}):
            out = savings_meter.record("prompt_result_cache", prompt="abcd" * 100, result_text="efgh" * 20)
        self.assertGreater(out["tokens"], 0)
        self.assertEqual(fake.inserts[0][0], "resource_events")
        self.assertEqual(fake.inserts[0][1]["kind"], "savings")


class TestResourceGovernorRam(unittest.TestCase):
    def test_vm_stat_parses_actual_page_size(self):
        vm = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free: 100.
Pages wired down: 10.
Anonymous pages: 20.
Pages occupied by compressor: 5.
"""
        def fake_check_output(cmd, **kwargs):
            if cmd[:2] == ["sysctl", "-n"]:
                return b"1048576000"
            return vm.encode()
        with patch.object(resource_governor.subprocess, "check_output", side_effect=fake_check_output):
            pct, free = resource_governor._vm_stat()
        self.assertAlmostEqual(free, 1.0, delta=0.1)
        self.assertGreater(pct, 0)

    def test_govern_rechecks_ram_after_unloading_local_model(self):
        fake_slots = MagicMock()
        fake_slots.loaded_models.return_value = ["llama3.1:latest"]
        fake_slots.is_heavy.return_value = True
        fake_slots.unload.return_value = True
        fake_db = FakeDB()
        throttle = []

        with patch.object(resource_governor, "db", fake_db), \
             patch.object(resource_governor, "disk_pct", return_value=(10.0, 1000.0)), \
             patch.object(resource_governor, "ram_pct", return_value=50.0), \
             patch.object(resource_governor, "ram_free_gb", side_effect=[4.5, 15.0, 15.0, 15.0]), \
             patch.object(resource_governor, "pressure_should_block", return_value=False), \
             patch.object(resource_governor, "_global_pause_reason", return_value=None), \
             patch.object(resource_governor, "_predicted_disk_pct", return_value=(None, None)), \
             patch.object(resource_governor, "set_throttle", side_effect=lambda n: throttle.append(n) or n), \
             patch.object(resource_governor, "current_limit", return_value=1), \
             patch.object(resource_governor, "RAM_FLOOR_GB", 6.0), \
             patch.object(resource_governor, "PER_TASK_GB", 3.0), \
             patch.dict(sys.modules, {"local_model_slots": fake_slots}):
            gauge = resource_governor.govern()

        self.assertNotIn(1, throttle)
        self.assertIn(resource_governor.CEILING, throttle)
        self.assertEqual(gauge["ram_free_gb"], 15.0)

    def test_govern_lifts_throttle_when_final_ram_gauge_recovers(self):
        fake_db = FakeDB()
        throttle = []

        with patch.object(resource_governor, "db", fake_db), \
             patch.object(resource_governor, "disk_pct", return_value=(10.0, 1000.0)), \
             patch.object(resource_governor, "ram_pct", return_value=80.0), \
             patch.object(resource_governor, "ram_free_gb", return_value=14.0), \
             patch.object(resource_governor, "dashboard_gauge",
                          return_value={"ram_free_gb": 37.0, "ram_pct": 30.0}), \
             patch.object(resource_governor, "pressure_should_block", return_value=False), \
             patch.object(resource_governor, "_global_pause_reason", return_value=None), \
             patch.object(resource_governor, "_predicted_disk_pct", return_value=(None, None)), \
             patch.object(resource_governor, "set_throttle", side_effect=lambda n: throttle.append(n) or n), \
             patch.object(resource_governor, "RAM_FLOOR_GB", 6.0), \
             patch.object(resource_governor, "PER_TASK_GB", 3.0), \
             patch.object(resource_governor, "current_limit", side_effect=[8, 2, 10]):
            gauge = resource_governor.govern()

        self.assertIn(2, throttle)
        self.assertIn(10, throttle)
        self.assertEqual(gauge["ram_free_gb"], 37.0)


class TestHistoricalCanary(unittest.TestCase):
    def test_historical_canary_records_model_samples(self):
        fake = FakeDB()
        fake.rows["tasks"] = [{"slug": "merged-x", "kind": "build", "prompt": "Fix a Vercel build problem by updating the smallest file and test." * 5}]
        with patch.object(model_historical_canary, "db", fake), \
             patch.object(model_historical_canary.ollama_catalog, "candidates",
                          return_value=[{"model": "llama3.1", "cap": 6}]), \
             patch.object(model_historical_canary.model_gateway, "complete",
                          return_value={"text": "- Files: a\n- Test: b\n- Risk: c"}):
            res = model_historical_canary.run(limit_models=1, limit_tasks=1, timeout=1)
        self.assertEqual(res["ran"], 1)
        self.assertTrue(any(t == "app_operations" for t, _ in fake.inserts))

    def test_historical_canary_uses_canary_only_models(self):
        fake = FakeDB()
        fake.rows["tasks"] = [{"slug": "merged-y", "kind": "build", "prompt": "Fix a deployed app by changing a minimal route and test." * 5}]

        def candidates(include_canary_only=False):
            self.assertTrue(include_canary_only)
            return [{"model": "oroboroslabs/claude-fable-5Q", "cap": 6, "canary_only": True}]

        with patch.object(model_historical_canary, "db", fake), \
             patch.object(model_historical_canary.ollama_catalog, "candidates", side_effect=candidates), \
             patch.object(model_historical_canary.model_gateway, "complete",
                          side_effect=RuntimeError("model not pulled")):
            res = model_historical_canary.run(limit_models=1, limit_tasks=1, timeout=1)
        self.assertEqual(res["ran"], 1)
        row = fake.inserts[0][1]
        self.assertEqual(row["model"], "oroboroslabs/claude-fable-5Q")
        self.assertFalse(row["ok"])
        self.assertIn("model not pulled", row["verdict"])

    def test_historical_canary_can_target_specific_model(self):
        fake = FakeDB()
        fake.rows["tasks"] = [{"slug": "merged-z", "kind": "build", "prompt": "Fix a deployed app by changing a minimal route and test." * 5}]
        with patch.object(model_historical_canary, "db", fake), \
             patch.object(model_historical_canary.ollama_catalog, "candidates",
                          return_value=[
                              {"model": "llama3.1", "cap": 6},
                              {"model": "oroboroslabs/claude-fable-5Q", "cap": 6, "canary_only": True},
                          ]), \
             patch.object(model_historical_canary.model_gateway, "complete",
                          return_value={"text": "- Files: a\n- Test: b\n- Risk: c"}), \
             patch.dict(os.environ, {"ORCH_HISTORICAL_CANARY_MODELS_ONLY": "oroboroslabs/claude-fable-5Q"}, clear=False):
            model_historical_canary.run(limit_models=5, limit_tasks=1, timeout=1)
        self.assertEqual(fake.inserts[0][1]["model"], "oroboroslabs/claude-fable-5Q")


if __name__ == "__main__":
    unittest.main(verbosity=2)
