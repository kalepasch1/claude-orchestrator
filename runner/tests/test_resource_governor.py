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
                  "DISK_SOFT_PCT", "DISK_HARD_PCT", "RAM_HARD_PCT"):
            os.environ.pop(k, None)
        self.assertEqual(rg._ceiling(), 12)
        self.assertEqual(rg._per_task_gb(), 1.5)
        self.assertEqual(rg.effective_floor_gb(), 6.0)
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


if __name__ == "__main__":
    unittest.main()
