import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_capabilities


def _row(hostname, models, lanes=2, running=None, free_ram=20, updated_at=None, key=None):
    import json
    import time
    payload = {
        "hostname": hostname,
        "max_ollama_lanes": lanes,
        "max_ollama_gb": 16,
        "free_ram_gb": free_ram,
        "heavy_models": [],
        "available_models": [{"model": m, "cap": 7} for m in models],
        "running_models": running or [],
        "updated_at": time.time() if updated_at is None else updated_at,
    }
    return {"key": key or f"ollama_capabilities_{hostname}", "value": json.dumps(payload)}


class FleetCapabilitiesTest(unittest.TestCase):
    """This is the actual cross-Mac awareness the fleet was missing: nothing previously
    published which locally-pulled models each box has, so a task wanting a local model
    was a coin flip between the Mac that has it and the Mac that doesn't."""

    def test_machines_with_model_only_returns_hosts_that_have_it(self):
        rows = [
            _row("mac1", ["llama3.2:3b"]),
            _row("mac2", ["qwen3-coder:30b", "llama3.2:3b"]),
        ]
        hosts = fleet_capabilities.machines_with_model("qwen3-coder:30b", rows=rows)
        self.assertEqual([h["hostname"] for h in hosts], ["mac2"])

    def test_machines_with_model_prefers_more_free_lanes(self):
        rows = [
            _row("mac1", ["qwen3-coder:30b"], lanes=3, running=["qwen3-coder:30b", "x", "y"]),  # 0 free
            _row("mac2", ["qwen3-coder:30b"], lanes=3, running=[]),  # 3 free
        ]
        hosts = fleet_capabilities.machines_with_model("qwen3-coder:30b", rows=rows)
        self.assertEqual(hosts[0]["hostname"], "mac2")

    def test_best_machine_for_returns_none_when_nobody_has_it(self):
        rows = [_row("mac1", ["llama3.2:3b"])]
        self.assertIsNone(fleet_capabilities.best_machine_for("qwen3-coder:30b", rows=rows))

    def test_stale_snapshot_is_ignored(self):
        rows = [_row("mac1", ["qwen3-coder:30b"], updated_at=0.0)]  # ancient
        self.assertEqual(fleet_capabilities.all_capabilities(rows=rows), {})
        self.assertIsNone(fleet_capabilities.best_machine_for("qwen3-coder:30b", rows=rows))

    def test_should_claim_locally_true_when_this_box_already_has_it(self):
        with patch.object(fleet_capabilities, "this_machine_has", return_value=True):
            self.assertTrue(fleet_capabilities.should_claim_locally("qwen3-coder:30b"))

    def test_should_claim_locally_false_when_nobody_has_it(self):
        with patch.object(fleet_capabilities, "this_machine_has", return_value=False), \
             patch.object(fleet_capabilities, "machines_with_model", return_value=[]):
            self.assertFalse(fleet_capabilities.should_claim_locally("qwen3-coder:30b"))

    def test_should_claim_locally_defers_to_peer_that_has_it(self):
        with patch.object(fleet_capabilities, "this_machine_has", return_value=False), \
             patch.object(fleet_capabilities, "machines_with_model",
                          return_value=[{"hostname": "mac2", "free_lanes": 2, "free_ram_gb": 30}]):
            self.assertFalse(fleet_capabilities.should_claim_locally("qwen3-coder:30b", hostname="mac1"))
            self.assertTrue(fleet_capabilities.should_claim_locally("qwen3-coder:30b", hostname="mac2"))

    def test_snapshot_publishes_profile_and_available_models(self):
        fake_profile = MagicMock()
        fake_profile.profile.return_value = {
            "max_ollama_lanes": 3, "max_ollama_gb": 24, "free_ram_gb": 20, "heavy_models": [],
        }
        fake_catalog = MagicMock()
        fake_catalog.candidates.return_value = [{"model": "qwen3-coder:30b", "cap": 9}]
        with patch.dict(sys.modules, {"machine_profile": fake_profile, "ollama_catalog": fake_catalog}):
            snap = fleet_capabilities.snapshot(hostname="mac2", running_models=["qwen3-coder:30b"])
        self.assertEqual(snap["hostname"], "mac2")
        self.assertEqual(snap["max_ollama_lanes"], 3)
        self.assertEqual(snap["available_models"], [{"model": "qwen3-coder:30b", "cap": 9}])
        self.assertEqual(snap["running_models"], ["qwen3-coder:30b"])

    def test_publish_upserts_into_controls_with_hostname_keyed_row(self):
        fake_db = MagicMock()
        with patch.object(fleet_capabilities, "snapshot",
                          return_value={"hostname": "mac2", "updated_at": 1.0}), \
             patch.object(fleet_capabilities, "_db", return_value=fake_db):
            ok = fleet_capabilities.publish(hostname="mac2")
        self.assertTrue(ok)
        args, kwargs = fake_db.insert.call_args
        self.assertEqual(args[0], "controls")
        self.assertEqual(args[1]["key"], "ollama_capabilities_mac2")
        self.assertTrue(kwargs.get("upsert"))

    def test_publish_fails_soft_on_db_error(self):
        fake_db = MagicMock()
        fake_db.insert.side_effect = RuntimeError("network down")
        with patch.object(fleet_capabilities, "snapshot",
                          return_value={"hostname": "mac2", "updated_at": 1.0}), \
             patch.object(fleet_capabilities, "_db", return_value=fake_db):
            ok = fleet_capabilities.publish(hostname="mac2")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
