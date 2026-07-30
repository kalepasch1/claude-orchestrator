import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import machine_profile


class FakeResourceGovernor:
    def __init__(self, total, free, floor=2.0):
        self._total = total
        self._free = free
        self._floor = floor

    def total_gb(self):
        return self._total

    def ram_free_gb(self):
        return self._free

    def effective_floor_gb(self):
        return self._floor


class MachineProfileTest(unittest.TestCase):
    """Regression coverage for the hardcoded-hostname MACHINE_PROFILES bug: any hostname
    that didn't exactly match "Mac.lan" or "Mandys-MacBook-Pro.local" silently fell back
    to a generic 2-lane/16GB profile. machine_profile.profile() must instead compute a
    sane, non-trivial profile for ANY hostname purely from live specs."""

    def test_unrecognized_hostname_still_gets_a_real_profile(self):
        with patch.object(machine_profile, "_resource_governor",
                          return_value=FakeResourceGovernor(64.0, 40.0)), \
             patch.object(machine_profile, "installed_models", return_value=[]), \
             patch.dict(os.environ, {}, clear=False):
            p = machine_profile.profile("some-renamed-mac-nobody-hardcoded.local")
        self.assertEqual(p["hostname"], "some-renamed-mac-nobody-hardcoded.local")
        self.assertEqual(p["total_ram_gb"], 64.0)
        self.assertGreater(p["max_ollama_gb"], 0)
        self.assertGreaterEqual(p["max_ollama_lanes"], 1)
        self.assertEqual(p["source"], "dynamic")

    def test_bigger_ram_box_gets_more_capacity_than_smaller_one(self):
        with patch.object(machine_profile, "installed_models", return_value=[]), \
             patch.dict(os.environ, {}, clear=False):
            with patch.object(machine_profile, "_resource_governor",
                              return_value=FakeResourceGovernor(16.0, 10.0)):
                small = machine_profile.profile("small-mac")
            with patch.object(machine_profile, "_resource_governor",
                              return_value=FakeResourceGovernor(64.0, 40.0)):
                big = machine_profile.profile("big-mac")
        self.assertGreater(big["max_ollama_gb"], small["max_ollama_gb"])
        self.assertGreaterEqual(big["max_ollama_lanes"], small["max_ollama_lanes"])

    def test_heavy_models_are_relative_to_this_box_not_a_hardcoded_list(self):
        # codestral:22b (16GB per local_model_slots.RAM_GB) is exclusive on a small box...
        with patch.object(machine_profile, "installed_models", return_value=["codestral:22b"]), \
             patch.object(machine_profile, "_resource_governor",
                          return_value=FakeResourceGovernor(16.0, 10.0)), \
             patch.dict(os.environ, {}, clear=False):
            small = machine_profile.profile("small-mac")
        self.assertIn("codestral:22b", small["heavy_models"])
        # ...but shareable on a big box with plenty of headroom.
        with patch.object(machine_profile, "installed_models", return_value=["codestral:22b"]), \
             patch.object(machine_profile, "_resource_governor",
                          return_value=FakeResourceGovernor(96.0, 60.0)), \
             patch.dict(os.environ, {}, clear=False):
            big = machine_profile.profile("big-mac")
        self.assertNotIn("codestral:22b", big["heavy_models"])

    def test_env_exclusive_list_is_additive_not_a_replacement(self):
        # Regression for the actual bug found in runner/.env: ORCH_EXCLUSIVE_OLLAMA_MODELS
        # held Mac 1's list verbatim-copied onto Mac 2. It must only ever ADD caution, never
        # erase the dynamically computed heavy set for models that are actually light here.
        with patch.object(machine_profile, "installed_models", return_value=["llama3.2:3b"]), \
             patch.object(machine_profile, "_resource_governor",
                          return_value=FakeResourceGovernor(64.0, 40.0)), \
             patch.dict(os.environ, {"ORCH_EXCLUSIVE_OLLAMA_MODELS": "deepseek-coder-v2,codellama:34b"},
                        clear=False):
            p = machine_profile.profile("big-mac")
        # llama3.2:3b is tiny and stays out of heavy_models on a big box.
        self.assertNotIn("llama3.2:3b", p["heavy_models"])
        # the env-listed names are folded in as extra caution even though they aren't installed.
        self.assertIn("deepseek-coder-v2", p["heavy_models"])
        self.assertIn("codellama:34b", p["heavy_models"])

    def test_explicit_override_wins_for_matching_host_only(self):
        override = {"other-mac": {"max_ollama_lanes": 99}}
        with patch.object(machine_profile, "installed_models", return_value=[]), \
             patch.object(machine_profile, "_resource_governor",
                          return_value=FakeResourceGovernor(64.0, 40.0)), \
             patch.dict(os.environ, {"ORCH_MACHINE_PROFILE_OVERRIDES_JSON": __import__("json").dumps(override)},
                        clear=False):
            mine = machine_profile.profile("this-mac")
            other = machine_profile.profile("other-mac")
        self.assertEqual(mine["source"], "dynamic")
        self.assertEqual(other["source"], "override")
        self.assertEqual(other["max_ollama_lanes"], 99)

    def test_floor_delegates_to_resource_governor_not_a_second_hardcoded_default(self):
        # machine_profile used to re-read RAM_FLOOR_GB with its own hardcoded default (6.0),
        # which drifted from resource_governor's own default (2.0) the moment that module's
        # default changed. It must delegate to effective_floor_gb() so the two can never
        # silently disagree about how much RAM is reserved fleet-wide.
        with patch.object(machine_profile, "installed_models", return_value=[]), \
             patch.dict(os.environ, {}, clear=False):
            with patch.object(machine_profile, "_resource_governor",
                              return_value=FakeResourceGovernor(16.0, 10.0, floor=2.0)):
                tight_floor = machine_profile.profile("mac")
            with patch.object(machine_profile, "_resource_governor",
                              return_value=FakeResourceGovernor(16.0, 10.0, floor=8.0)):
                loose_floor = machine_profile.profile("mac")
        # A bigger reserved floor must leave strictly less budget for Ollama.
        self.assertGreater(tight_floor["max_ollama_gb"], loose_floor["max_ollama_gb"])

    def test_unreadable_specs_stay_conservative_not_generous(self):
        with patch.object(machine_profile, "_resource_governor", return_value=None), \
             patch.object(machine_profile, "installed_models", return_value=[]), \
             patch("subprocess.check_output", side_effect=Exception("no sysctl")), \
             patch.dict(os.environ, {}, clear=False):
            p = machine_profile.profile("unknown-box")
        self.assertIsNone(p["total_ram_gb"])
        self.assertLessEqual(p["max_ollama_gb"], 8.0)
        self.assertGreaterEqual(p["max_ollama_lanes"], 1)


if __name__ == "__main__":
    unittest.main()
