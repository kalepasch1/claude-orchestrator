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
                "name": "ollama", "cmd": "aider --model ollama/llama3.1:latest --yes --no-auto-commit --message {prompt}",
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
        ps = "  PID ARGS\n 123 /Applications/Ollama.app/Contents/Resources/llama-server --model blob\