import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import machine_profile
import fleet_capabilities


class FakeResourceGovernor:
    def __init__(self, total, free):
        self._total = total
        self._free = free

    def total_gb(self):
        return self._total

    def ram_free_gb(self):
        return self._free


class TwoMachineIntegrationTest(unittest.TestCase):
    """End-to-end simulation of the actual fleet shape (a memory-constrained Mac 1 and a
    bigger Mac 2) exercising machine_profile.py + fleet_capabilities.py together, without a
    live Supabase — this is what "both Macs working in tandem, no conflicts" reduces to at
    the code level: two independently-computed profiles that never bleed into each other,
    and a merged capability view a scheduler could safely read to pick the right box."""

    def _profile_for(self, hostname, total_gb, free_gb, models):
        with patch.object(machine_profile, "_resource_governor",
                          return_value=FakeResourceGovernor(total_gb, free_gb)), \
             patch.object(machine_profile, "installed_models", return_value=models), \
             patch.dict(os.environ, {}, clear=False):
            return machine_profile.profile(hostname)

    def test_two_real_shaped_machines_get_independent_correct_profiles(self):
        mac1 = self._profile_for("Mac.lan", 16.0, 8.0, ["llama3.2:3b", "deepseek-coder-v2:16b"])
        mac2 = self._profile_for("Mandys-MacBook-Pro.local", 64.0, 40.0,
                                 ["qwen3-coder:30b", "codestral:22b", "gemma3:12b", "llama3.2:3b"])
        # Mac 2 (more RAM) must end up with strictly more capacity than Mac 1 — the exact
        # invariant the old hardcoded dict was trying (and, on a hostname mismatch, failing) to express.
        self.assertGreater(mac2["max_ollama_gb"], mac1["max_ollama_gb"])
        self.assertGreaterEqual(mac2["max_ollama_lanes"], mac1["max_ollama_lanes"])
        # deepseek-coder-v2:16b (12GB) is exclusive on Mac 1's small budget...
        self.assertIn("deepseek-coder-v2:16b", mac1["heavy_models"])
        # ...but qwen3-coder:30b (24GB) still fits fine within Mac 2's much bigger budget.
        self.assertNotIn("qwen3-coder:30b", mac2["heavy_models"])
        # Hostnames never cross-contaminate each other's computed profile.
        self.assertEqual(mac1["hostname"], "Mac.lan")
        self.assertEqual(mac2["hostname"], "Mandys-MacBook-Pro.local")

    def test_capability_snapshots_from_both_machines_merge_without_collision(self):
        import time
        import json as _json
        mac1_payload = {
            "hostname": "Mac.lan", "max_ollama_lanes": 1, "max_ollama_gb": 8, "free_ram_gb": 5,
            "heavy_models": ["deepseek-coder-v2:16b"],
            "available_models": [{"model": "llama3.2:3b", "cap": 5}],
            "running_models": [], "updated_at": time.time(),
        }
        mac2_payload = {
            "hostname": "Mandys-MacBook-Pro.local", "max_ollama_lanes": 3, "max_ollama_gb": 24,
            "free_ram_gb": 30, "heavy_models": [],
            "available_models": [{"model": "qwen3-coder:30b", "cap": 9},
                                  {"model": "llama3.2:3b", "cap": 5}],
            "running_models": ["qwen3-coder:30b"], "updated_at": time.time(),
        }
        rows = [
            {"key": "ollama_capabilities_Mac.lan", "value": _json.dumps(mac1_payload)},
            {"key": "ollama_capabilities_Mandys-MacBook-Pro.local", "value": _json.dumps(mac2_payload)},
        ]
        caps = fleet_capabilities.all_capabilities(rows=rows)
        self.assertEqual(set(caps.keys()), {"Mac.lan", "Mandys-MacBook-Pro.local"})

        # A task that needs qwen3-coder:30b can ONLY be served by Mac 2 — Mac 1 never claims
        # work it can't actually run locally.
        hosts = fleet_capabilities.machines_with_model("qwen3-coder:30b", rows=rows)
        self.assertEqual([h["hostname"] for h in hosts], ["Mandys-MacBook-Pro.local"])

        # A task that only needs the small shared model can run on either — no forced
        # contention, and the one with more free capacity is preferred.
        hosts = fleet_capabilities.machines_with_model("llama3.2:3b", rows=rows)
        self.assertEqual(hosts[0]["hostname"], "Mandys-MacBook-Pro.local")  # 3 lanes, 1 used = 2 free
        self.assertEqual(hosts[1]["hostname"], "Mac.lan")  # 1 lane, 0 used = 1 free

    def test_should_claim_locally_prevents_double_work_on_shared_model(self):
        """Regression for the exact failure mode described in the fleet docs: two machines
        polling the same queue must not both try to run the same local-only task. This is
        the model-aware complement to db.claim_task()'s atomic PATCH (which already prevents
        a literal double-claim) — should_claim_locally() lets a machine self-select OUT
        before it ever attempts the claim, so the machine that actually has the model wins
        without a race."""
        rows_only_mac2_has_it = [{
            "key": "ollama_capabilities_Mandys-MacBook-Pro.local",
            "value": __import__("json").dumps({
                "hostname": "Mandys-MacBook-Pro.local", "max_ollama_lanes": 3,
                "available_models": [{"model": "qwen3-coder:30b", "cap": 9}],
                "running_models": [], "updated_at": __import__("time").time(),
            }),
        }]
        with patch.object(fleet_capabilities, "this_machine_has", return_value=False), \
             patch.object(fleet_capabilities, "machines_with_model",
                          return_value=fleet_capabilities.machines_with_model(
                              "qwen3-coder:30b", rows=rows_only_mac2_has_it)):
            # Mac 1 (doesn't have it) defers.
            self.assertFalse(fleet_capabilities.should_claim_locally("qwen3-coder:30b", hostname="Mac.lan"))
            # Mac 2 (does have it) proceeds.
            self.assertTrue(fleet_capabilities.should_claim_locally(
                "qwen3-coder:30b", hostname="Mandys-MacBook-Pro.local"))


if __name__ == "__main__":
    unittest.main()
