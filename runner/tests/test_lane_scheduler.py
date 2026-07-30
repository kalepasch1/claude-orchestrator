import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lane_scheduler


class LaneSchedulerProfileTest(unittest.TestCase):
    """lane_scheduler used to hardcode MACHINE_PROFILES by exact hostname and silently
    fall back to a generic 2-lane/16GB profile on any mismatch. It must now delegate to
    machine_profile.profile() and behave the same regardless of hostname."""

    def test_run_uses_machine_profile_and_publishes_capabilities(self):
        fake_db = MagicMock()
        fake_profile = {"hostname": "any-host", "max_ollama_lanes": 3, "max_ollama_gb": 24,
                        "heavy_models": [], "source": "dynamic"}
        fake_fleet_caps = MagicMock()
        with patch.object(lane_scheduler, "db", fake_db), \
             patch.object(lane_scheduler, "_profile", return_value=fake_profile), \
             patch.object(lane_scheduler, "_ollama_running_models", return_value=[]), \
             patch.object(lane_scheduler, "_kill_orphans", return_value=0), \
             patch.object(lane_scheduler, "_unload_idle_models", return_value=0), \
             patch.object(lane_scheduler, "_check_ram_pressure", return_value=True), \
             patch.dict(sys.modules, {"fleet_capabilities": fake_fleet_caps}):
            result = lane_scheduler.run()
        self.assertEqual(result["available_lanes"], 3)
        self.assertTrue(result["ram_ok"])
        fake_fleet_caps.publish.assert_called_once()

    def test_can_schedule_model_respects_dynamic_heavy_set(self):
        fake_profile = {"max_ollama_lanes": 2, "heavy_models": ["codestral:22b"]}
        with patch.object(lane_scheduler, "_profile", return_value=fake_profile), \
             patch.object(lane_scheduler, "_ollama_running_models", return_value=[]):
            self.assertTrue(lane_scheduler.can_schedule_model("codestral:22b"))

        with patch.object(lane_scheduler, "_profile", return_value=fake_profile), \
             patch.object(lane_scheduler, "_ollama_running_models",
                          return_value=[{"name": "codestral:22b", "size": "16GB"}]):
            self.assertFalse(lane_scheduler.can_schedule_model("llama3.2:3b"))

    def test_can_schedule_model_blocked_at_lane_capacity(self):
        fake_profile = {"max_ollama_lanes": 1, "heavy_models": []}
        with patch.object(lane_scheduler, "_profile", return_value=fake_profile), \
             patch.object(lane_scheduler, "_ollama_running_models",
                          return_value=[{"name": "llama3.2:3b", "size": "2GB"}]):
            self.assertFalse(lane_scheduler.can_schedule_model("llama3.2:3b"))

    def test_profile_falls_back_gracefully_if_machine_profile_import_fails(self):
        with patch.dict(sys.modules, {"machine_profile": None}):
            p = lane_scheduler._profile("some-host")
        self.assertEqual(p["hostname"], "some-host")
        self.assertEqual(p["max_ollama_lanes"], 2)


if __name__ == "__main__":
    unittest.main()
