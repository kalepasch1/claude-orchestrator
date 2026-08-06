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
        for k in ("MAX_PARALLEL_CEILING", "PER_TASK_GB", "RAM_FLOOR_GB",
                  "DISK_SOFT_PCT", "DISK_HARD_PCT", "RAM_HARD_PCT"):
            self._saved[k] = os.environ.get(k)

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
        for k in ("MAX_PARALLEL_CEILING", "PER_TASK_GB", "RAM_FLOOR_GB",
                  "ORCH_RAM_FLOOR_GB", "DISK_SOFT_PCT", "DISK_HARD_PCT", "RAM_HARD_PCT"):
            os.environ.pop(k, None)
        self.assertEqual(rg._ceiling(), 12)
        # Cowork/provider-side execution is intentionally lightweight locally;
        # these tuned defaults preserve full fleet throughput while the live
        # memory-pressure brake remains the authoritative safety control.
        self.assertEqual(rg._per_task_gb(), 0.15)
        # 2GB left the box thrashing under a full lane set; the fleet contract floor is 4GB.
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


class RamFloorContractTest(unittest.TestCase):
    """The floor is a fleet-wide contract value, not a per-host constant.

    fleet_control.load_config() pushes fleet_config rows into the environment as ORCH_ keys, so
    ORCH_RAM_FLOOR_GB is what every Mac must read. The legacy per-host RAM_FLOOR_GB stays
    honoured while hosts still set it, but the ORCH_ key wins.
    """

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("ORCH_RAM_FLOOR_GB", "RAM_FLOOR_GB")}
        self._saved_last_good = rg._last_good_ram_floor_gb
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        rg._last_good_ram_floor_gb = self._saved_last_good

    def test_default_floor_is_four_gb(self):
        self.assertEqual(rg.effective_floor_gb(), 4.0)

    def test_orch_key_is_read_live(self):
        os.environ["ORCH_RAM_FLOOR_GB"] = "6.0"
        self.assertEqual(rg.effective_floor_gb(), 6.0)
        os.environ["ORCH_RAM_FLOOR_GB"] = "3.5"
        self.assertEqual(rg.effective_floor_gb(), 3.5)

    def test_orch_key_wins_over_legacy_per_host_key(self):
        os.environ["RAM_FLOOR_GB"] = "2.0"
        os.environ["ORCH_RAM_FLOOR_GB"] = "5.0"
        self.assertEqual(rg.effective_floor_gb(), 5.0)

    def test_legacy_key_still_honoured_alone(self):
        os.environ["RAM_FLOOR_GB"] = "2.0"
        self.assertEqual(rg.effective_floor_gb(), 2.0)

    def test_unparseable_value_keeps_previous_safe_floor(self):
        """A typo in central config must not silently remove the crash brake."""
        os.environ["ORCH_RAM_FLOOR_GB"] = "6.0"
        self.assertEqual(rg.effective_floor_gb(), 6.0)
        os.environ["ORCH_RAM_FLOOR_GB"] = "not-a-number"
        self.assertEqual(rg.effective_floor_gb(), 6.0)

    def test_nonpositive_value_keeps_previous_safe_floor(self):
        os.environ["ORCH_RAM_FLOOR_GB"] = "5.0"
        self.assertEqual(rg.effective_floor_gb(), 5.0)
        os.environ["ORCH_RAM_FLOOR_GB"] = "0"
        self.assertEqual(rg.effective_floor_gb(), 5.0)

    def test_no_hardcoded_floor_literal_in_the_gate(self):
        """can_claim() must go through the tunable, not a literal of its own."""
        os.environ["ORCH_RAM_FLOOR_GB"] = "10.0"
        with patch.object(rg, "ram_free_gb", return_value=10.05), \
                patch.object(rg, "pressure_should_block", return_value=False):
            ok, reason = rg.can_claim()
        self.assertFalse(ok, "floor of 10GB with 10.05GB free must not admit a claim")
        self.assertIn("10.0", reason)


class LaneTargetTest(unittest.TestCase):
    """Mac 1 should run 6-8 lanes when RAM permits, not the 4 it was clamped to."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("ORCH_RAM_FLOOR_GB", "RAM_FLOOR_GB", "PER_TASK_GB", "MAX_PARALLEL_CEILING")}
        self._saved_last_good = rg._last_good_ram_floor_gb
        for k in self._saved:
            os.environ.pop(k, None)
        os.environ["PER_TASK_GB"] = "0.15"
        os.environ["MAX_PARALLEL_CEILING"] = "12"

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        rg._last_good_ram_floor_gb = self._saved_last_good

    def test_target_is_in_the_six_to_eight_band_when_ram_permits(self):
        for free_gb in (8.0, 16.0, 32.0, 48.0):
            with self.subTest(free_gb=free_gb):
                target = rg.lane_target(free_gb=free_gb)
                self.assertGreaterEqual(target, 6)
                self.assertLessEqual(target, 8)

    def test_plentiful_ram_does_not_exceed_the_band(self):
        self.assertEqual(rg.lane_target(free_gb=128.0), 8)

    def test_ceiling_still_clamps_the_target(self):
        os.environ["MAX_PARALLEL_CEILING"] = "3"
        self.assertEqual(rg.lane_target(free_gb=48.0), 3)

    def test_starved_host_throttles_below_the_band(self):
        """The band is a target, not a floor — a genuinely starved box must still throttle."""
        os.environ["ORCH_RAM_FLOOR_GB"] = "4.0"
        self.assertLess(rg.lane_target(free_gb=4.3), 6)
        self.assertGreaterEqual(rg.lane_target(free_gb=4.3), 1)

    def test_target_never_drops_below_one(self):
        os.environ["ORCH_RAM_FLOOR_GB"] = "8.0"
        self.assertEqual(rg.lane_target(free_gb=1.0), 1)

    def test_unreadable_ram_funds_the_low_end_of_the_band(self):
        with patch.object(rg, "ram_free_gb", return_value=None):
            self.assertEqual(rg.lane_target(), 6)

    def test_raised_floor_reduces_the_affordable_target(self):
        os.environ["PER_TASK_GB"] = "1.0"
        os.environ["ORCH_RAM_FLOOR_GB"] = "4.0"
        self.assertEqual(rg.lane_target(free_gb=11.0), 7)
        os.environ["ORCH_RAM_FLOOR_GB"] = "8.0"
        self.assertEqual(rg.lane_target(free_gb=11.0), 3)


if __name__ == "__main__":
    unittest.main()
