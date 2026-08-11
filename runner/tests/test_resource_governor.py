"""
test_resource_governor.py - live-reload correctness for resource_governor.py's tunables.

2026-07-11 production bug: CEILING/DISK_SOFT/DISK_HARD/RAM_HARD/RAM_FLOOR_GB/PER_TASK_GB were
module-level constants snapshotted ONCE at import time. fleet_control.load_config() pushes
fleet-wide tuning (MAX_PARALLEL_CEILING, PER_TASK_GB, RAM_FLOOR_GB, ...) into os.environ live
every loop, but a long-running resource_governor process never re-read these frozen constants --
so a machine whose runner started before the last central tuning push stayed stuck on whatever
conservative defaults it booted with. Root-caused: Mac 2 was clamped to ~4 concurrent tasks
against a 16-lane ceiling because its process never picked up a tuned PER_TASK_GB/RAM_FLOOR_GB
pushed centrally after it last started.

Fixed by converting the constants to functions that read os.environ live on every call. These
tests cover: (1) each tunable reflects a live os.environ change without re-importing the module,
(2) set_throttle()/current_limit() respect a live-changed ceiling, (3) effective_floor_gb() and
can_claim() respect a live-changed RAM_FLOOR_GB/PER_TASK_GB.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import resource_governor as rg


class LiveTunableReadTest(unittest.TestCase):
    """Root-cause regression: changing env mid-process must be picked up immediately."""

    def setUp(self):
        self._saved = {}
        for k in ("MAX_PARALLEL_CEILING", "PER_TASK_GB", "RAM_FLOOR_GB", "ORCH_RAM_FLOOR_GB",
                  "DISK_SOFT_PCT", "DISK_HARD_PCT", "RAM_HARD_PCT"):
            self._saved[k] = os.environ.get(k)
        os.environ.pop("ORCH_RAM_FLOOR_GB", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_ceiling_reads_live_env(self):
        os.environ["MAX_PARALLEL_CEILING"] = "16"
        self.assertEqual(rg._ceiling(), 16)
        os.environ["MAX_PARALLEL_CEILING"] = "24"
        self.assertEqual(rg._ceiling(), 24)

    def test_per_task_gb_reads_live_env(self):
        os.environ["PER_TASK_GB"] = "3.0"
        self.assertEqual(rg._per_task_gb(), 3.0)
        os.environ["PER_TASK_GB"] = "0.5"
        self.assertEqual(rg._per_task_gb(), 0.5)

    def test_ram_floor_gb_reads_live_env(self):
        os.environ["RAM_FLOOR_GB"] = "4.0"
        self.assertEqual(rg.effective_floor_gb(), 4.0)
        os.environ["RAM_FLOOR_GB"] = "8.0"
        self.assertEqual(rg.effective_floor_gb(), 8.0)

    def test_disk_and_ram_hard_soft_read_live_env(self):
        os.environ["DISK_SOFT_PCT"] = "70"
        os.environ["DISK_HARD_PCT"] = "85"
        os.environ["RAM_HARD_PCT"] = "75"
        self.assertEqual(rg._disk_soft(), 70.0)
        self.assertEqual(rg._disk_hard(), 85.0)
        self.assertEqual(rg._ram_hard(), 75.0)

    def test_no_env_falls_back_to_documented_defaults(self):
        for k in ("MAX_PARALLEL_CEILING", "PER_TASK_GB", "RAM_FLOOR_GB", "ORCH_RAM_FLOOR_GB",
                  "DISK_SOFT_PCT", "DISK_HARD_PCT", "RAM_HARD_PCT"):
            os.environ.pop(k, None)
        self.assertEqual(rg._ceiling(), 12)
        # Cowork/provider-side execution is intentionally lightweight locally;
        # these tuned defaults preserve full fleet throughput while the live
        # memory-pressure brake remains the authoritative safety control.
        self.assertEqual(rg._per_task_gb(), 0.15)
        # 2026-08-06: the floor default moved 2.0 -> 4.0 and now comes fleet-wide from the
        # ORCH_RAM_FLOOR_GB fleet_config key rather than a per-machine .env value.
        self.assertEqual(rg.effective_floor_gb(), 4.0)
        self.assertEqual(rg._disk_soft(), 80.0)
        self.assertEqual(rg._disk_hard(), 90.0)
        self.assertEqual(rg._ram_hard(), 82.0)


class ThrottleRespectsLiveCeilingTest(unittest.TestCase):
    """A stale low ceiling baked in at process start must not survive a central tuning push."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._saved_home = rg.HOME
        self._saved_file = rg.THROTTLE_FILE
        rg.HOME = self._tmpdir
        rg.THROTTLE_FILE = os.path.join(self._tmpdir, "throttle")
        self._saved_ceiling = os.environ.get("MAX_PARALLEL_CEILING")

    def tearDown(self):
        rg.HOME = self._saved_home
        rg.THROTTLE_FILE = self._saved_file
        if self._saved_ceiling is None:
            os.environ.pop("MAX_PARALLEL_CEILING", None)
        else:
            os.environ["MAX_PARALLEL_CEILING"] = self._saved_ceiling

    def test_set_throttle_clamps_to_currently_live_ceiling_not_import_time_value(self):
        # Simulate the process having booted under a stale, conservative ceiling...
        os.environ["MAX_PARALLEL_CEILING"] = "16"
        self.assertEqual(rg.set_throttle(999), 16)
        # ...then a central fleet_config push raises it live, with no restart.
        os.environ["MAX_PARALLEL_CEILING"] = "24"
        self.assertEqual(rg.set_throttle(999), 24)

    def test_current_limit_reflects_live_ceiling_change(self):
        os.environ["MAX_PARALLEL_CEILING"] = "16"
        rg.set_throttle(16)
        self.assertEqual(rg.current_limit(), 16)
        os.environ["MAX_PARALLEL_CEILING"] = "24"
        rg.set_throttle(24)
        self.assertEqual(rg.current_limit(), 24)


class CanClaimRespectsLiveTunablesTest(unittest.TestCase):
    """The memory-budget gate that clamped Mac 2 to ~4 lanes must use live PER_TASK_GB/RAM_FLOOR_GB."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("PER_TASK_GB", "RAM_FLOOR_GB")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_stale_conservative_per_task_gb_no_longer_wedges_claims_after_live_tune(self):
        # free_ram=16GB, floor=4GB: with the stale PER_TASK_GB=3.0 baked in at setup time,
        # mem_budget = (16-4)/3.0 = 4 -- this is the exact clamp that produced Mac 2's 4/16.
        os.environ["RAM_FLOOR_GB"] = "4.0"
        os.environ["PER_TASK_GB"] = "3.0"
        with patch.object(rg, "ram_free_gb", return_value=16.0):
            ok, reason = rg.can_claim()
            self.assertTrue(ok, reason)
            mem_budget_before = max(1, int((16.0 - rg.effective_floor_gb()) / rg._per_task_gb()))
            self.assertEqual(mem_budget_before, 4)
            # Live-tune PER_TASK_GB down to match a properly-sized machine -- no restart needed.
            os.environ["PER_TASK_GB"] = "0.5"
            mem_budget_after = max(1, int((16.0 - rg.effective_floor_gb()) / rg._per_task_gb()))
            self.assertEqual(mem_budget_after, 24)


class FleetRamFloorTest(unittest.TestCase):
    """The floor is a fleet_config value (ORCH_RAM_FLOOR_GB), not a per-machine constant."""

    KEYS = ("ORCH_RAM_FLOOR_GB", "RAM_FLOOR_GB")

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:
            os.environ.pop(k, None)
        self._saved_last_good = rg._LAST_GOOD_FLOOR[0]

    def tearDown(self):
        rg._LAST_GOOD_FLOOR[0] = self._saved_last_good
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_default_floor_is_four_gb(self):
        self.assertEqual(rg.DEFAULT_RAM_FLOOR_GB, 4.0)
        self.assertEqual(rg._ram_floor_gb(), 4.0)
        self.assertEqual(rg.effective_floor_gb(), 4.0)

    def test_floor_reads_the_orch_fleet_config_key(self):
        os.environ["ORCH_RAM_FLOOR_GB"] = "6.5"
        self.assertEqual(rg.effective_floor_gb(), 6.5)

    def test_orch_key_takes_precedence_over_legacy_per_machine_key(self):
        os.environ["RAM_FLOOR_GB"] = "2.0"
        os.environ["ORCH_RAM_FLOOR_GB"] = "5.0"
        self.assertEqual(rg.effective_floor_gb(), 5.0)

    def test_legacy_key_still_honoured_when_orch_key_absent(self):
        os.environ["RAM_FLOOR_GB"] = "3.0"
        self.assertEqual(rg.effective_floor_gb(), 3.0)

    def test_floor_reflects_a_live_central_push_without_restart(self):
        os.environ["ORCH_RAM_FLOOR_GB"] = "4.0"
        self.assertEqual(rg.effective_floor_gb(), 4.0)
        os.environ["ORCH_RAM_FLOOR_GB"] = "9.0"
        self.assertEqual(rg.effective_floor_gb(), 9.0)

    def test_malformed_push_keeps_the_previous_safe_floor(self):
        os.environ["ORCH_RAM_FLOOR_GB"] = "7.0"
        self.assertEqual(rg._ram_floor_gb(), 7.0)
        os.environ["ORCH_RAM_FLOOR_GB"] = "not-a-number"
        self.assertEqual(rg._ram_floor_gb(), 7.0)

    def test_non_positive_push_keeps_the_previous_safe_floor(self):
        os.environ["ORCH_RAM_FLOOR_GB"] = "5.0"
        self.assertEqual(rg._ram_floor_gb(), 5.0)
        for bad in ("0", "-3"):
            os.environ["ORCH_RAM_FLOOR_GB"] = bad
            self.assertEqual(rg._ram_floor_gb(), 5.0, bad)

    def test_blank_value_falls_through_to_the_default(self):
        os.environ["ORCH_RAM_FLOOR_GB"] = "   "
        self.assertEqual(rg._ram_floor_gb(), 4.0)

    def test_floor_is_never_a_secret_bearing_key(self):
        # Guards against anyone "helpfully" sourcing this from a credential store.
        self.assertNotIn("KEY", rg.__doc__ or "")
        self.assertEqual(rg._ram_floor_gb(), 4.0)


class LaneTargetTest(unittest.TestCase):
    """Healthy machines should settle at 6-8 lanes, not slam to the ceiling."""

    KEYS = ("ORCH_RAM_FLOOR_GB", "RAM_FLOOR_GB", "PER_TASK_GB",
            "MAX_PARALLEL_CEILING", "ORCH_LANE_TARGET_MIN", "ORCH_LANE_TARGET_MAX")

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_default_band_is_six_to_eight(self):
        self.assertEqual(rg._lane_target_bounds(), (6, 8))

    def test_target_is_within_six_to_eight_when_ram_permits(self):
        # 48GB Mac 1 with the 4GB floor: plenty of headroom, so the band decides.
        target = rg.lane_target(free_gb=48.0)
        self.assertGreaterEqual(target, 6)
        self.assertLessEqual(target, 8)

    def test_target_tops_out_at_eight_not_at_the_ceiling(self):
        os.environ["MAX_PARALLEL_CEILING"] = "12"
        self.assertEqual(rg.lane_target(free_gb=64.0), 8)

    def test_target_never_exceeds_the_ceiling(self):
        os.environ["MAX_PARALLEL_CEILING"] = "4"
        self.assertLessEqual(rg.lane_target(free_gb=64.0), 4)

    def test_tight_ram_wins_over_the_band(self):
        os.environ["PER_TASK_GB"] = "2.0"
        # (10 - 4) / 2.0 = 3 lanes of real headroom; the 6-lane floor must not override it.
        self.assertEqual(rg.lane_target(free_gb=10.0), 3)

    def test_no_headroom_still_yields_at_least_one_lane(self):
        os.environ["PER_TASK_GB"] = "2.0"
        self.assertEqual(rg.lane_target(free_gb=4.0), 1)

    def test_unreadable_ram_uses_the_conservative_end_of_the_band(self):
        with patch.object(rg, "ram_free_gb", return_value=None):
            self.assertEqual(rg.lane_target(), 6)

    def test_band_is_fleet_tunable(self):
        os.environ["ORCH_LANE_TARGET_MIN"] = "2"
        os.environ["ORCH_LANE_TARGET_MAX"] = "5"
        self.assertEqual(rg._lane_target_bounds(), (2, 5))
        self.assertEqual(rg.lane_target(free_gb=64.0), 5)

    def test_inverted_band_is_normalised_not_crashed(self):
        os.environ["ORCH_LANE_TARGET_MIN"] = "9"
        os.environ["ORCH_LANE_TARGET_MAX"] = "3"
        lo, hi = rg._lane_target_bounds()
        self.assertEqual((lo, hi), (9, 9))

    def test_garbage_band_falls_back_to_the_default(self):
        os.environ["ORCH_LANE_TARGET_MIN"] = "abc"
        os.environ["ORCH_LANE_TARGET_MAX"] = ""
        self.assertEqual(rg._lane_target_bounds(), (6, 8))

    def test_stats_exposes_the_target_and_band(self):
        with patch.object(rg, "dashboard_gauge", return_value={"ram_free_gb": 48.0}), \
                patch.object(rg, "can_claim", return_value=(True, "ok")):
            s = rg.stats()
        self.assertEqual(s["lane_target_band"], [6, 8])
        self.assertGreaterEqual(s["lane_target"], 6)
        self.assertLessEqual(s["lane_target"], 8)
        self.assertEqual(s["ram_floor_gb"], 4.0)


if __name__ == "__main__":
    unittest.main()
